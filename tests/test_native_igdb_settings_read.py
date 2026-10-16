from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.igdb_settings_read import create_igdb_settings_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.utils.igdb_settings import igdb_public_state


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-igdb-read-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='igdb-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    saved = []
    router = create_igdb_settings_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=SimpleNamespace(
            read=lambda: {'settings': {
                'igdb_client_id': 'client-id', 'secret_present': True, 'last_tested': None,
            }},
            save=lambda payload: saved.append(payload) or {'settings': {
                'igdb_client_id': payload['igdb_client_id'],
                'secret_present': bool(payload['igdb_client_secret']),
            }},
            test_connection=lambda: {'settings': {
                'igdb_client_id': 'client-id', 'secret_present': True,
            }},
        ),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    )
    client.saved = saved
    return client


def test_igdb_settings_read_keeps_secret_free_envelope_and_head():
    client = _client()
    response = client.get('/api/admin/igdb/settings')
    head = client.head('/api/admin/igdb/settings')
    assert response.status_code == 200
    assert response.json()['settings']['secret_present'] is True
    assert 'igdb_client_secret' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_igdb_settings_requires_admin():
    response = _client(role='user').get('/api/admin/igdb/settings', follow_redirects=False)
    assert response.status_code == 302


def test_igdb_public_state_never_returns_secret():
    state = igdb_public_state(SimpleNamespace(
        igdb_client_id='client-id', igdb_client_secret='secret', igdb_last_tested=None,
    ))
    assert state == {
        'igdb_client_id': 'client-id', 'secret_present': True, 'last_tested': None,
    }
    assert 'igdb_client_secret' not in state
    assert state['igdb_client_id'] != 'secret'


def test_igdb_settings_write_validates_csrf_and_keeps_secret_hidden():
    client = _client()
    missing_csrf = client.put(
        '/api/admin/igdb/settings',
        json={'igdb_client_id': 'changed', 'igdb_client_secret': ''},
    )
    saved = client.put(
        '/api/admin/igdb/settings',
        json={'igdb_client_id': 'changed', 'igdb_client_secret': 'private'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid = client.put(
        '/api/admin/igdb/settings',
        json={'unexpected': True},
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert missing_csrf.status_code == 400
    assert saved.status_code == 200
    assert saved.json()['settings']['igdb_client_id'] == 'changed'
    assert 'private' not in saved.text
    assert invalid.status_code == 400
    assert client.saved == [{'igdb_client_id': 'changed', 'igdb_client_secret': 'private'}]


def test_igdb_connection_test_checks_csrf_and_reports_only_safe_state():
    client = _client()
    invalid_csrf = client.post('/api/admin/igdb/test')
    tested = client.post(
        '/api/admin/igdb/test', headers={'X-CSRFToken': client.csrf_token}
    )
    assert invalid_csrf.status_code == 400
    assert tested.status_code == 200
    assert tested.json()['message'] == 'IGDB connection successful.'
    assert tested.json()['settings']['secret_present'] is True
    assert 'igdb_client_secret' not in tested.text


def test_legacy_igdb_form_save_preserves_status_and_hidden_secret():
    client = _client()
    saved = client.post(
        '/admin/igdb_settings',
        json={'igdb_client_id': 'updated-id', 'igdb_client_secret': 'private'},
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert saved.status_code == 200
    assert saved.json()['status'] == 'success'
    assert saved.json()['message'] == 'IGDB settings updated successfully'
    assert 'private' not in saved.text
    assert client.saved == [{'igdb_client_id': 'updated-id', 'igdb_client_secret': 'private'}]


def test_legacy_igdb_test_path_uses_native_safe_connection_projection():
    client = _client()
    tested = client.post('/admin/test_igdb', headers={'X-CSRFToken': client.csrf_token})

    assert tested.status_code == 200
    assert tested.json()['message'] == 'IGDB connection successful.'
    assert 'igdb_client_secret' not in tested.text


def test_legacy_integrations_igdb_aliases_use_native_save_and_test():
    client = _client()
    saved = client.post(
        '/admin/integrations/igdb/save',
        json={'igdb_client_id': 'alias-id', 'igdb_client_secret': 'alias-secret'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    tested = client.post(
        '/admin/integrations/igdb/test', headers={'X-CSRFToken': client.csrf_token},
    )

    assert saved.status_code == 200
    assert saved.json()['status'] == 'success'
    assert client.saved == [{'igdb_client_id': 'alias-id', 'igdb_client_secret': 'alias-secret'}]
    assert tested.status_code == 200
    assert tested.json()['message'] == 'IGDB connection successful.'
