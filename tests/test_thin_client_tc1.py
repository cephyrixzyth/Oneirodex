"""TC-1 thin client protocol — scopes, device_kind, capabilities, command gating."""

import json
from uuid import uuid4

import pytest
from flask import g
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import ClientDevice, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.api_tokens import TOKEN_SCOPE_PRESETS, VALID_SCOPES, generate_api_token
from oneirodex.utils.client_capabilities import resolve_client_capabilities
from oneirodex.utils import client_commands as cc


@pytest.fixture
def user(db_session):
    uid = str(uuid4())
    row = User(
        name=f'thinuser_{uid[:8]}',
        email=f'thin_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def library(db_session):
    lib = Library(name=f'ThinLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


@pytest.fixture
def game(db_session, library):
    row = Game(
        uuid=str(uuid4()),
        name='Thin Test Game',
        library_uuid=library.uuid,
        full_disk_path='/tmp/' + uuid4().hex,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_valid_scopes_include_thin_client():
    assert 'read:social' in VALID_SCOPES
    assert 'write:presence' in VALID_SCOPES
    thin = TOKEN_SCOPE_PRESETS['thin']
    assert 'write:download' not in thin['scopes']
    assert set(thin['scopes']) <= VALID_SCOPES


def test_thin_capabilities_deny_lifecycle():
    caps = resolve_client_capabilities(
        'thin',
        api_token=type('T', (), {'has_scope': lambda self, s: s in {
            'read:library', 'read:social', 'write:presence',
        }})(),
    )
    assert caps['device_kind'] == 'thin'
    assert 'download' in caps['denies']
    assert 'install' in caps['denies']
    assert 'browse' in caps['allows']
    assert 'social' in caps['allows']


def test_companion_capabilities_allow_lifecycle_with_download_scope(client, db_session, user):
    _, raw = generate_api_token(user, 'Companion', ['read:library', 'write:download'])
    headers = {'Authorization': f'Bearer {raw}'}
    response = client.get(
        '/api/client/capabilities?device_kind=companion',
        headers=headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['device_kind'] == 'companion'
    assert 'download' in body['allows']
    assert 'download' not in body['denies']


def test_thin_token_cannot_initiate_download(client, db_session, user, game):
    _, raw = generate_api_token(
        user,
        'Thin seat',
        TOKEN_SCOPE_PRESETS['thin']['scopes'],
    )
    headers = {'Authorization': f'Bearer {raw}', 'Content-Type': 'application/json'}

    response = client.post(
        f'/api/downloads/games/{game.uuid}',
        headers=headers,
        data=json.dumps({}),
    )
    assert response.status_code == 403
    assert 'write:download' in response.get_json()['error']


def test_thin_preset_via_tokens_api(client, db_session, user):
    _, raw = generate_api_token(user, 'Bootstrap', ['read:library'])
    headers = {'Authorization': f'Bearer {raw}', 'Content-Type': 'application/json'}

    listed = client.get('/api/tokens', headers=headers)
    assert listed.status_code == 200
    body = listed.get_json()
    assert 'scope_presets' in body
    assert body['scope_presets']['thin']['label'] == 'Thin client'
    assert 'write:download' not in body['scope_presets']['thin']['scopes']

    # A token only mints tokens within its own scopes: this one lacks
    # read:social and write:presence, so the thin preset is refused.
    refused = client.post(
        '/api/tokens',
        headers=headers,
        data=json.dumps({'name': 'Living room', 'preset': 'thin'}),
    )
    assert refused.status_code == 403
    assert set(refused.get_json()['detail']['denied_scopes']) == {'read:social', 'write:presence'}

    _, raw = generate_api_token(user, 'Bootstrap', TOKEN_SCOPE_PRESETS['thin']['scopes'])
    headers['Authorization'] = f'Bearer {raw}'
    # Requests here share one app context: drop the first token's cached caller.
    g.pop('_login_user', None)
    g.pop('api_token', None)
    created = client.post(
        '/api/tokens',
        headers=headers,
        data=json.dumps({'name': 'Living room', 'preset': 'thin'}),
    )
    assert created.status_code == 201
    token_row = created.get_json()['token']
    assert set(token_row['scopes']) == set(TOKEN_SCOPE_PRESETS['thin']['scopes'])


def test_heartbeat_persists_device_kind(client, app, db_session, user):
    _login(client, app, user)
    response = client.post(
        '/api/client/heartbeat',
        json={'device_id': 'thin-seat-1', 'device_kind': 'thin', 'device_name': 'HTPC'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['device_kind'] == 'thin'
    assert payload['allows']
    assert 'download' in payload['denies']
    assert payload['commands'] == []

    row = db_session.execute(
        select(ClientDevice).filter_by(user_id=user.id, device_id='thin-seat-1')
    ).scalars().one()
    assert row.device_kind == 'thin'
    assert row.device_name == 'HTPC'


def test_thin_bearer_heartbeat_skips_command_queue(client, app, db_session, user, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    cc.enqueue_client_command(user.id, 'game-x', 'install')

    _, raw = generate_api_token(user, 'Thin', TOKEN_SCOPE_PRESETS['thin']['scopes'])
    headers = {'Authorization': f'Bearer {raw}', 'Content-Type': 'application/json'}

    response = client.post(
        '/api/client/heartbeat',
        headers=headers,
        json={'device_id': 'thin-2', 'device_kind': 'thin'},
    )
    assert response.status_code == 200
    assert response.get_json()['commands'] == []


def test_companion_token_receives_commands(client, app, db_session, user, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    cc.enqueue_client_command(user.id, 'game-y', 'install')

    _, raw = generate_api_token(user, 'Desk', ['read:library', 'write:download'])
    headers = {'Authorization': f'Bearer {raw}', 'Content-Type': 'application/json'}

    response = client.post(
        '/api/client/heartbeat',
        headers=headers,
        json={'device_id': 'desk-1', 'device_kind': 'companion'},
    )
    assert response.status_code == 200
    commands = response.get_json()['commands']
    assert len(commands) == 1
    assert commands[0]['action'] == 'install'


def test_companion_kind_without_download_scope_skips_commands(client, db_session, user, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    cc.enqueue_client_command(user.id, 'game-z', 'update')

    _, raw = generate_api_token(user, 'Thin bearer', TOKEN_SCOPE_PRESETS['thin']['scopes'])
    headers = {'Authorization': f'Bearer {raw}', 'Content-Type': 'application/json'}

    response = client.post(
        '/api/client/heartbeat',
        headers=headers,
        json={'device_id': 'mislabeled', 'device_kind': 'companion'},
    )
    assert response.status_code == 200
    assert response.get_json()['commands'] == []
