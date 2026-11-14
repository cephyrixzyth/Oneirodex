"""Wave 17 — unmatched list filters, matched_game nest, soft amend, batch APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import Game, Library, UnmatchedFolder, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'w17adm_{uid[:8]}',
        email=f'w17adm_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def lib(db_session):
    library = Library(name=f'W17Lib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def _folder(db_session, lib, *, path, status='Unmatched', **kwargs):
    row = UnmatchedFolder(
        id=str(uuid4()),
        library_uuid=lib.uuid,
        folder_path=path,
        failed_time=datetime.now(timezone.utc),
        content_type='Games',
        status=status,
        **kwargs,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_list_filters_q_why_kind_library(client, app, db_session, admin, lib):
    other = Library(name=f'W17Other_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(other)
    db_session.flush()

    keep = _folder(
        db_session, lib,
        path='/games/Alpha Soft Title',
        status='Unmatched',
        match_reason='title_below_threshold',
        suggested_kind='tool',
        search_name='Alpha Soft',
    )
    _folder(
        db_session, lib,
        path='/games/Beta Dup',
        status='Duplicate',
        match_reason='same_path',
    )
    _folder(
        db_session, other,
        path='/games/Alpha Soft OtherLib',
        status='Unmatched',
        suggested_kind='tool',
    )

    _login(client, app, admin)

    by_q = client.get('/api/unmatched_folders', query_string={'q': 'Alpha Soft'})
    assert by_q.status_code == 200
    q_ids = {r['id'] for r in by_q.get_json()}
    assert keep.id in q_ids
    assert all('Alpha Soft' in (r.get('folder_path') or '') or r.get('search_name') == 'Alpha Soft'
               for r in by_q.get_json() if r['id'] == keep.id)

    # Scoped by library, like the suggested_kind query below. An exact-set
    # assertion over every unmatched folder in the database picks up any row
    # another file left behind with the same `why`.
    by_why = client.get('/api/unmatched_folders', query_string={
        'why': 'title_below_threshold',
        'library_uuid': lib.uuid,
    })
    assert by_why.status_code == 200
    assert {r['id'] for r in by_why.get_json()} == {keep.id}

    by_kind = client.get('/api/unmatched_folders', query_string={
        'suggested_kind': 'tool',
        'library_uuid': lib.uuid,
    })
    assert by_kind.status_code == 200
    assert {r['id'] for r in by_kind.get_json()} == {keep.id}

    by_status = client.get('/api/unmatched_folders', query_string={'status': 'Duplicate'})
    assert by_status.status_code == 200
    assert all(r['status'] == 'Duplicate' for r in by_status.get_json())


def test_list_nests_matched_game(client, app, db_session, admin, lib):
    game = Game(
        uuid=str(uuid4()),
        name='Library Hit',
        library_uuid=lib.uuid,
        full_disk_path='/games/Library Hit',
        size=10,
        igdb_id=424242,
    )
    db_session.add(game)
    db_session.flush()

    dup = _folder(
        db_session, lib,
        path='/games/Library Hit (copy)',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='title_vs_library_name',
        match_score=0.97,
    )
    plain = _folder(db_session, lib, path='/games/No Match Yet', status='Unmatched')

    _login(client, app, admin)
    resp = client.get('/api/unmatched_folders')
    assert resp.status_code == 200
    rows = {r['id']: r for r in resp.get_json()}

    assert rows[dup.id]['matched_game'] is not None
    assert rows[dup.id]['matched_game']['uuid'] == game.uuid
    assert rows[dup.id]['matched_game']['name'] == 'Library Hit'
    assert rows[dup.id]['matched_game']['path'] == '/games/Library Hit'
    assert rows[dup.id]['matched_game']['igdb_id'] == 424242
    assert rows[dup.id]['match_score'] == 0.97
    assert rows[dup.id]['match_reason'] == 'title_vs_library_name'
    assert rows[plain.id]['matched_game'] is None


def test_list_search_matches_linked_game_name_and_path(client, app, db_session, admin, lib):
    game = Game(
        uuid=str(uuid4()),
        name='Searchable Linked Title',
        library_uuid=lib.uuid,
        full_disk_path='/games/linked-title-search-path',
        size=10,
        igdb_id=424243,
    )
    db_session.add(game)
    db_session.flush()
    row = _folder(
        db_session,
        lib,
        path='/games/Unmatched Copy',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='title_vs_library_name',
    )
    _login(client, app, admin)

    by_name = client.get('/api/unmatched_folders', query_string={'q': 'Searchable Linked Title'})
    by_path = client.get('/api/unmatched_folders', query_string={'q': 'linked-title-search-path'})
    by_platform = client.get('/api/unmatched_folders', query_string={'q': 'PCWIN'})

    assert by_name.status_code == 200
    assert by_path.status_code == 200
    assert by_platform.status_code == 200
    assert row.id in {item['id'] for item in by_name.get_json()}
    assert row.id in {item['id'] for item in by_path.get_json()}
    assert row.id in {item['id'] for item in by_platform.get_json()}


def test_amend_name_soft_only(client, app, db_session, admin, lib):
    folder = _folder(db_session, lib, path='/games/Raw.Folder.Name-REPACK')
    original_path = folder.folder_path
    _login(client, app, admin)

    resp = client.post(
        f'/api/unmatched_folders/{folder.id}/name',
        json={'search_name': 'Clean Title', 'display_name': 'Clean Title (UI)'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['disk_rename'] is False
    assert body['search_name'] == 'Clean Title'
    assert body['display_name'] == 'Clean Title (UI)'
    assert body['folder_path'] == original_path
    assert body['folder_name'] == 'Raw.Folder.Name-REPACK'
    assert body['effective_search_name'] == 'Clean Title'

    db_session.refresh(folder)
    assert folder.folder_path == original_path
    assert folder.search_name == 'Clean Title'
    assert folder.display_name == 'Clean Title (UI)'

    listed = client.get('/api/unmatched_folders', query_string={'q': 'Clean Title'})
    assert any(r['id'] == folder.id for r in listed.get_json())
    row = next(r for r in listed.get_json() if r['id'] == folder.id)
    assert row['folder_name'] == 'Raw.Folder.Name-REPACK'
    assert row['search_name'] == 'Clean Title'


def test_batch_clear_mark_fix_amend(client, app, db_session, admin, lib):
    a = _folder(db_session, lib, path='/games/Clear Me A')
    b = _folder(db_session, lib, path='/games/Clear Me B')
    c = _folder(db_session, lib, path='/games/Mark Me Tool')
    game = Game(
        uuid=str(uuid4()),
        name='Dup Target',
        library_uuid=lib.uuid,
        full_disk_path='/games/Dup Target',
        size=5,
    )
    db_session.add(game)
    db_session.flush()
    d1 = _folder(
        db_session, lib,
        path='/games/Dup One',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='same_path',
        match_score=1.0,
    )
    d2 = _folder(
        db_session, lib,
        path='/games/Dup Two',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='title_vs_library_name',
        match_score=0.9,
    )
    e = _folder(db_session, lib, path='/games/Amend Me')

    _login(client, app, admin)

    clear = client.post('/api/unmatched_folders/batch/clear', json={'ids': [a.id, b.id, 'missing-id']})
    assert clear.status_code == 200
    clear_body = clear.get_json()
    assert clear_body['cleared'] == 2
    assert clear_body['failed'] == 1
    assert clear_body['disk_io'] is False
    assert db_session.get(UnmatchedFolder, a.id) is None
    assert db_session.get(UnmatchedFolder, b.id) is None

    mark = client.post(
        '/api/unmatched_folders/batch/mark_kind',
        json={'ids': [c.id], 'item_kind': 'tool'},
    )
    assert mark.status_code == 200
    mark_body = mark.get_json()
    assert mark_body['marked'] == 1
    assert mark_body['results'][0]['ok'] is True
    assert db_session.get(UnmatchedFolder, c.id) is None
    created = db_session.execute(
        select(Game).filter_by(uuid=mark_body['results'][0]['game_uuid'])
    ).scalars().first()
    assert created is not None
    assert created.item_kind == 'tool'

    fix = client.post(
        '/api/unmatched_folders/batch/fix',
        json={'ids': [d1.id, d2.id], 'action': 'ignore'},
    )
    assert fix.status_code == 200
    fix_body = fix.get_json()
    assert fix_body['fixed'] == 2
    assert fix_body['action'] == 'ignore'
    db_session.refresh(d1)
    db_session.refresh(d2)
    assert d1.status == 'Ignore'
    assert d2.status == 'Ignore'

    amend = client.post(
        '/api/unmatched_folders/batch/amend',
        json={'ids': [e.id], 'search_name': 'Batch Soft', 'display_name': 'Batch Soft UI'},
    )
    assert amend.status_code == 200
    amend_body = amend.get_json()
    assert amend_body['amended'] == 1
    assert amend_body['disk_rename'] is False
    db_session.refresh(e)
    assert e.search_name == 'Batch Soft'
    assert e.display_name == 'Batch Soft UI'
    assert e.folder_path == '/games/Amend Me'


def test_batch_ids_cap(client, app, admin):
    _login(client, app, admin)
    ids = [str(uuid4()) for _ in range(101)]
    resp = client.post('/api/unmatched_folders/batch/clear', json={'ids': ids})
    assert resp.status_code == 400
    assert resp.get_json()['cap'] == 100


def test_list_and_export_include_disk_meta_keys(client, app, db_session, admin, lib):
    """UID-016 compare: size/mtime keys present (null-safe) on list + JSON export."""
    identified = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    created = datetime(2023, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
    failed = datetime(2025, 3, 10, 14, 0, 0, tzinfo=timezone.utc)

    game = Game(
        uuid=str(uuid4()),
        name='Sized Hit',
        library_uuid=lib.uuid,
        full_disk_path='/games/Sized Hit',
        size=1048576,
        igdb_id=900000 + (uuid4().int % 90000),
        date_identified=identified,
        date_created=created,
        rom_region='USA',
        rom_languages='en',
    )
    db_session.add(game)
    db_session.flush()

    dup = UnmatchedFolder(
        id=str(uuid4()),
        library_uuid=lib.uuid,
        folder_path='/games/Sized Hit (USA)',
        failed_time=failed,
        content_type='Games',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='title_vs_library_name',
        match_score=0.96,
    )
    plain = UnmatchedFolder(
        id=str(uuid4()),
        library_uuid=lib.uuid,
        folder_path='/games/No Size Yet',
        failed_time=None,
        content_type='Games',
        status='Unmatched',
    )
    db_session.add_all([dup, plain])
    db_session.commit()

    _login(client, app, admin)

    listed = client.get('/api/unmatched_folders')
    assert listed.status_code == 200
    rows = {r['id']: r for r in listed.get_json()}

    folder_keys = (
        'size_bytes', 'folder_size_bytes', 'folder_mtime', 'mtime', 'modified_at', 'failed_time',
    )
    game_keys = ('size_bytes', 'date_identified', 'date_created', 'folder_mtime', 'mtime')

    for row_id in (dup.id, plain.id):
        row = rows[row_id]
        for key in folder_keys:
            assert key in row, f'missing {key} on list row'
        # UnmatchedFolder has no size column — always null
        assert row['size_bytes'] is None
        assert row['folder_size_bytes'] is None

    assert rows[dup.id]['folder_mtime'] == failed.replace(tzinfo=None).isoformat()
    assert rows[dup.id]['mtime'] == failed.replace(tzinfo=None).isoformat()
    assert rows[dup.id]['modified_at'] == failed.replace(tzinfo=None).isoformat()
    assert rows[dup.id]['failed_time'] == failed.replace(tzinfo=None).isoformat()
    assert rows[plain.id]['folder_mtime'] is None
    assert rows[plain.id]['failed_time'] is None

    mg = rows[dup.id]['matched_game']
    assert mg is not None
    for key in game_keys:
        assert key in mg, f'missing {key} on matched_game'
    assert mg['size_bytes'] == 1048576
    assert mg['date_identified'] == identified.replace(tzinfo=None).isoformat()
    assert mg['date_created'] == created.replace(tzinfo=None).isoformat()
    assert mg['folder_mtime'] == identified.replace(tzinfo=None).isoformat()
    assert mg['mtime'] == identified.replace(tzinfo=None).isoformat()
    # BE-DET region/lang intact
    assert mg['rom_region'] == 'USA'
    assert mg['rom_languages'] == 'en'
    assert rows[plain.id]['matched_game'] is None
    assert 'rom_region' in rows[dup.id]
    assert 'rom_languages' in rows[dup.id]

    exported = client.get('/api/unmatched_folders/export', query_string={'format': 'json'})
    assert exported.status_code == 200
    export_rows = {r['id']: r for r in exported.get_json()}
    for key in folder_keys:
        assert key in export_rows[dup.id]
    assert export_rows[dup.id]['matched_game']['size_bytes'] == 1048576
    assert export_rows[dup.id]['matched_game']['date_identified'] == identified.replace(tzinfo=None).isoformat()
    assert 'rom_region' in export_rows[dup.id]
    assert 'rom_languages' in export_rows[dup.id]
