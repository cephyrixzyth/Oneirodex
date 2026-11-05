"""Wave 2a — PC extras discovery + duplicate glance/fix APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import DuplicateFixLog, Game, Library, UnmatchedFolder, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.pc_extras import (
    classify_pc_extra_folder,
    discover_pc_extra_folders,
    discover_pc_sidecar_dlc,
    is_pc_library_platform,
)


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'dupeadm_{uid[:8]}',
        email=f'dupeadm_{uid[:8]}@example.com',
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
    library = Library(name=f'DupeLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def test_classify_pc_extra_folder_kinds():
    assert classify_pc_extra_folder('DLC') == 'dlc'
    assert classify_pc_extra_folder('extras') == 'extra'
    assert classify_pc_extra_folder('Bonus Content') == 'extra'
    assert classify_pc_extra_folder('manuals') == 'manual'
    assert classify_pc_extra_folder('Savegames') is None


def test_is_pc_library_platform():
    assert is_pc_library_platform(LibraryPlatform.PCWIN) is True
    assert is_pc_library_platform(LibraryPlatform.PCDOS) is True
    assert is_pc_library_platform(LibraryPlatform.PS2) is False


def test_discover_pc_extra_folders(tmp_path):
    game = tmp_path / 'Cool Game'
    game.mkdir()
    (game / 'DLC').mkdir()
    (game / 'extras').mkdir()
    (game / 'Updates').mkdir()
    (game / 'bin').mkdir()

    found = discover_pc_extra_folders(
        str(game),
        configured_extras_name='extras',
        configured_updates_name='Updates',
    )
    names = {item['name'] for item in found}
    assert 'DLC' in names
    assert 'extras' not in names  # configured extras skipped (caller handles)
    assert 'Updates' not in names
    assert 'bin' not in names


def test_discover_pc_sidecar_dlc(tmp_path):
    root = tmp_path / 'pc'
    root.mkdir()
    game = root / 'FooBar'
    game.mkdir()
    (root / 'FooBar DLC').mkdir()
    (root / 'FooBar-DLC-Pack').mkdir()
    (root / 'Other Game').mkdir()

    found = discover_pc_sidecar_dlc(str(game), game_name='FooBar')
    names = {item['name'] for item in found}
    assert 'FooBar DLC' in names
    assert 'FooBar-DLC-Pack' in names
    assert 'Other Game' not in names


def test_list_duplicates_and_fix(client, app, db_session, admin, lib):
    identified = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    game = Game(
        uuid=str(uuid4()),
        name='Same Title',
        library_uuid=lib.uuid,
        full_disk_path='/games/Same Title',
        size=1048576,
        date_identified=identified,
    )
    db_session.add(game)
    db_session.flush()

    failed = datetime(2025, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    folder = UnmatchedFolder(
        id=str(uuid4()),
        library_uuid=lib.uuid,
        folder_path='/games/Same Title (copy)',
        failed_time=failed,
        content_type='Games',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='title_vs_library_name',
        match_score=0.95,
    )
    db_session.add(folder)
    db_session.commit()

    _login(client, app, admin)

    listed = client.get('/api/unmatched_folders/duplicates')
    assert listed.status_code == 200
    body = listed.get_json()
    assert body['count'] >= 1
    row = next(d for d in body['duplicates'] if d['id'] == folder.id)
    assert row['match_reason'] == 'title_vs_library_name'
    assert len(row['titles']) >= 2
    assert row['candidates'][0]['uuid'] == game.uuid
    assert row['candidates'][0]['path'] == '/games/Same Title'
    # UID-016 disk meta on duplicate payload + candidate
    assert 'size_bytes' in row and row['size_bytes'] is None
    assert row['folder_mtime'] == failed.replace(tzinfo=None).isoformat()
    assert row['failed_time'] == failed.replace(tzinfo=None).isoformat()
    cand = row['candidates'][0]
    assert cand['size_bytes'] == 1048576
    assert cand['date_identified'] == identified.replace(tzinfo=None).isoformat()
    assert cand['folder_mtime'] == identified.replace(tzinfo=None).isoformat()
    assert cand['mtime'] == identified.replace(tzinfo=None).isoformat()
    assert row['matched_game']['size_bytes'] == 1048576
    assert row['matched_game']['date_identified'] == identified.replace(tzinfo=None).isoformat()
    assert row['titles'][0]['folder_mtime'] == failed.replace(tzinfo=None).isoformat()
    assert row['titles'][1]['size_bytes'] == 1048576

    fixed = client.post(
        f'/api/unmatched_folders/{folder.id}/fix',
        json={'action': 'ignore', 'notes': 'wave2a test'},
    )
    assert fixed.status_code == 200
    assert fixed.get_json()['action'] == 'ignore'
    assert fixed.get_json()['result_status'] == 'Ignore'

    logs = client.get('/api/unmatched_folders/fix_logs')
    assert logs.status_code == 200
    log_body = logs.get_json()
    assert log_body['count'] >= 1
    assert any(entry['action'] == 'ignore' for entry in log_body['logs'])

    db_session.refresh(folder)
    assert folder.status == 'Ignore'


def test_fix_merge_clears_row(client, app, db_session, admin, lib):
    game = Game(
        uuid=str(uuid4()),
        name='Merge Me',
        library_uuid=lib.uuid,
        full_disk_path='/games/Merge Me',
        size=10,
    )
    db_session.add(game)
    folder_id = str(uuid4())
    folder = UnmatchedFolder(
        id=folder_id,
        library_uuid=lib.uuid,
        folder_path='/games/Merge Me Dup',
        failed_time=datetime.now(timezone.utc),
        content_type='Games',
        status='Duplicate',
        matched_game_uuid=game.uuid,
        match_reason='same_path',
        match_score=1.0,
    )
    db_session.add(folder)
    db_session.commit()

    _login(client, app, admin)
    resp = client.post(f'/api/unmatched_folders/{folder_id}/fix', json={'action': 'merge'})
    assert resp.status_code == 200
    assert resp.get_json()['result_status'] == 'cleared'
    assert db_session.get(UnmatchedFolder, folder_id) is None
    assert db_session.execute(
        select(DuplicateFixLog).filter_by(action='merge')
    ).scalars().first() is not None


def test_path_open_returns_string_only_within_configured_roots(client, app, admin, tmp_path, monkeypatch):
    allowed_root = tmp_path / 'library'
    allowed_root.mkdir()
    target = allowed_root / 'reveal_me'
    target.mkdir()
    monkeypatch.setattr(
        'oneirodex.utils.client_commands._open_path_allowed_bases',
        lambda: [str(allowed_root)],
    )
    _login(client, app, admin)
    resp = client.get('/api/path/open', query_string={'path': str(target)})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['path'] == str(target)
    assert data['exists'] is True
    assert data['is_dir'] is True
    assert data['open_via'] == 'desktop'

    outside_path = tmp_path / 'outside'
    outside_path.mkdir()
    denied = client.get('/api/path/open', query_string={'path': str(outside_path)})
    assert denied.status_code == 403
    assert str(outside_path) not in denied.get_data(as_text=True)
