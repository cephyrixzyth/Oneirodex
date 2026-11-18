"""Editing a game through ``PUT /api/admin/manual-identify/<uuid>``, end to end.

This is the endpoint the admin app's edit page saves through. The checks cover
access, the saved fields, provider links riding the same commit, and links the
editor does not own surviving a save.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex.models import Developer, Game, GameURL, Library, SystemEvents, User
from oneirodex.platform import LibraryPlatform

CUSTOM_ID_FLOOR = 2_000_000_420  # custom IDs skip IGDB taxonomy lookups


def _user(db_session, role):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'{role}_{suffix}', email=f'{role}_{suffix}@example.com',
        password_hash='placeholder', role=role, user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'oneirodex.utils.security.get_allowed_base_directories', lambda *_a, **_k: [str(tmp_path)],
    )
    monkeypatch.setattr('oneirodex.utils.scanning.is_scan_job_running', lambda: False)
    folder = tmp_path / 'Game Folder'
    folder.mkdir()
    (folder / 'game.bin').write_bytes(b'data')
    return folder


@pytest.fixture
def game(db_session, storage):
    library = Library(name=f'Edit Library {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    row = Game(
        uuid=str(uuid4()), igdb_id=CUSTOM_ID_FLOOR + int(uuid4().int % 1_000_000),
        name='Original Name', library_uuid=library.uuid, full_disk_path=str(storage),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _body(game, **changes):
    body = {
        'igdb_id': game.igdb_id, 'name': 'Updated Name',
        'full_disk_path': game.full_disk_path, 'library_uuid': game.library_uuid,
        'summary': 'Updated summary', 'provider_urls': {},
    }
    body.update(changes)
    return body


def _put(client, game, body):
    return client.put(f'/api/admin/manual-identify/{game.uuid}', json=body)


def _links(db_session, game):
    db_session.expire_all()
    rows = db_session.execute(select(GameURL).filter_by(game_uuid=game.uuid)).scalars()
    return {row.url_type: row.url for row in rows}


def test_signed_out_and_member_edits_are_refused(client, db_session, game):
    signed_out = _put(client, game, _body(game))
    assert signed_out.status_code == 302 and '/login' in signed_out.headers['Location']
    _login(client, _user(db_session, 'user'))
    assert _put(client, game, _body(game)).status_code == 403
    db_session.expire_all()
    assert db_session.get(Game, game.id).name == 'Original Name'


def test_admin_edit_saves_fields_creates_a_developer_and_logs_it(client, db_session, game):
    admin = _user(db_session, 'admin')
    _login(client, admin)
    developer = f'New Studio {uuid4().hex[:6]}'

    response = _put(client, game, _body(game, developer=developer))

    assert response.status_code == 200, response.get_json()
    db_session.expire_all()
    saved = db_session.get(Game, game.id)
    assert saved.name == 'Updated Name'
    assert saved.summary == 'Updated summary'
    assert saved.date_identified is not None
    assert saved.developer.name == developer
    assert db_session.execute(select(Developer).filter_by(name=developer)).scalar_one()
    assert db_session.execute(
        select(SystemEvents).filter_by(audit_user=admin.id).where(
            SystemEvents.event_text.contains('Updated Name'),
        )
    ).first() is not None


def test_overlong_name_is_refused_with_field_detail(client, db_session, game):
    _login(client, _user(db_session, 'admin'))
    response = _put(client, game, _body(game, name='x' * 501))
    assert response.status_code == 422
    assert 'name' in response.get_json()['detail']


def test_provider_links_are_saved_with_the_edit(client, db_session, game):
    _login(client, _user(db_session, 'admin'))
    response = _put(client, game, _body(game, provider_urls={
        'steam': 'https://store.steampowered.com/app/620/',
        'gog': 'https://www.gog.com/game/portal_2',
    }))
    assert response.status_code == 200, response.get_json()
    links = _links(db_session, game)
    assert links['steam'] == 'https://store.steampowered.com/app/620/'
    assert links['gog'] == 'https://www.gog.com/game/portal_2'


def test_a_non_http_provider_link_never_replaces_a_good_one(client, db_session, game):
    db_session.add(GameURL(game_uuid=game.uuid, url_type='steam', url='https://good.example/'))
    db_session.commit()
    _login(client, _user(db_session, 'admin'))

    _put(client, game, _body(game, provider_urls={'steam': 'javascript:alert(1)'}))

    assert _links(db_session, game).get('steam') == 'https://good.example/'


def test_links_the_editor_does_not_own_survive_a_save(client, db_session, game):
    db_session.add(GameURL(game_uuid=game.uuid, url_type='youtube', url='https://youtu.be/keep'))
    db_session.commit()
    _login(client, _user(db_session, 'admin'))

    assert _put(client, game, _body(game)).status_code == 200

    assert _links(db_session, game).get('youtube') == 'https://youtu.be/keep'
