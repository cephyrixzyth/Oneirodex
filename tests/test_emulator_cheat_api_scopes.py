"""API-token scopes for shared RetroArch cheat files."""

from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.api_tokens import generate_api_token
from oneirodex.utils.emulator_cheats import create_cheat_file


@pytest.fixture
def cheat_api_data(app, db_session, configured_install, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path / 'cheats'))
    uid = str(uuid4())
    owner = User(
        name=f'cheat_owner_{uid[:8]}',
        email=f'{uid}@example.test',
        password_hash='unused-test-password-hash',
        role='user',
        user_id=uid,
        state=True,
        is_email_verified=True,
    )
    library = Library(name=f'NES {uid[:8]}', platform=LibraryPlatform.NES)
    db_session.add_all([owner, library])
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name='Scope test game',
        library_uuid=library.uuid,
        full_disk_path=None,
        size=0,
    )
    db_session.add(game)
    db_session.commit()
    return owner, game, tmp_path / 'cheats'


def _bearer(owner, scopes):
    _row, raw = generate_api_token(owner, 'cheat scope test', scopes)
    return {'Authorization': f'Bearer {raw}'}


def test_read_only_library_token_can_read_but_cannot_mutate_cheats(
    client, cheat_api_data,
):
    owner, game, root = cheat_api_data
    headers = _bearer(owner, ['read:library'])
    stored = create_cheat_file(
        game.uuid,
        name='Existing codes',
        codes=[{'code': '01 02'}],
    )

    listed = client.get(f'/api/games/{game.uuid}/cheats', headers=headers)
    assert listed.status_code == 200
    assert listed.get_json()['cheats'][0]['name'] == stored['name']
    downloaded = client.get(
        f'/api/games/{game.uuid}/cheats/{stored["name"]}', headers=headers,
    )
    assert downloaded.status_code == 200
    assert b'01+02' in downloaded.data

    created = client.post(
        f'/api/games/{game.uuid}/cheats',
        headers=headers,
        json={'name': 'forbidden', 'codes': [{'code': 'DEAD'}]},
    )
    assert created.status_code == 403
    assert created.get_json()['error_code'] == 'forbidden'
    deleted = client.delete(
        f'/api/games/{game.uuid}/cheats/{stored["name"]}', headers=headers,
    )
    assert deleted.status_code == 403
    assert deleted.get_json()['error_code'] == 'forbidden'
    assert (root / game.uuid / stored['name']).is_file()


def test_write_library_token_can_create_and_delete_cheats(client, cheat_api_data):
    owner, game, root = cheat_api_data
    headers = _bearer(owner, ['read:library', 'write:library'])

    created = client.post(
        f'/api/games/{game.uuid}/cheats',
        headers=headers,
        json={'name': 'allowed', 'codes': [{'code': 'BEEF'}]},
    )
    assert created.status_code == 201
    filename = created.get_json()['name']
    assert (root / game.uuid / filename).is_file()

    deleted = client.delete(
        f'/api/games/{game.uuid}/cheats/{filename}', headers=headers,
    )
    assert deleted.status_code == 200
    assert not (root / game.uuid / filename).exists()


def test_browser_session_keeps_cheat_write_access(client, cheat_api_data):
    owner, game, root = cheat_api_data
    with client.session_transaction() as session:
        session['_user_id'] = str(owner.id)
        session['_fresh'] = True

    created = client.post(
        f'/api/games/{game.uuid}/cheats',
        json={'name': 'browser allowed', 'codes': [{'code': 'C0DE'}]},
    )
    assert created.status_code == 201
    assert (root / game.uuid / created.get_json()['name']).is_file()
