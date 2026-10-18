from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.igdb_settings_read import create_igdb_settings_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.utils.igdb_settings import igdb_public_state


def _client(*, role='admin', legacy_save=None, legacy_test=None, existing_secret_length=20):
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
    data_access = SimpleNamespace(
        read=lambda: {'settings': {
            'igdb_client_id': 'client-id', 'secret_present': True, 'last_tested': None,
        }},
        existing_secret_length=lambda: existing_secret_length,
        save=lambda payload: saved.append(payload) or {'settings': {
            'igdb_client_id': payload['igdb_client_id'],
            'secret_present': bool(payload['igdb_client_secret']),
        }},
        test_connection=lambda: {'settings': {
            'igdb_client_id': 'client-id', 'secret_present': True,
        }},
    )
    if legacy_save is not None:
        data_access.save_legacy = legacy_save
    data_access.test_connection_legacy = legacy_test or (lambda: {
        'status': 'success', 'message': 'IGDB API test successful',
    })

    router = create_igdb_settings_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=data_access,
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


def test_legacy_igdb_form_post_bypasses_modern_api_validation():
    calls = []
    client = _client(legacy_save=lambda payload: calls.append(payload))
    payload = {'igdb_client_id': '', 'igdb_client_secret': ''}

    response = client.post(
        '/admin/igdb_settings', json=payload,
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 200
    assert calls == [payload]
    assert client.saved == []
    assert response.json() == {
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
        'status': 'success',
        'message': 'IGDB settings updated successfully',
    }


def test_integrations_igdb_save_matches_legacy_minimum_and_success_message():
    client = _client()
    headers = {'X-CSRFToken': client.csrf_token}
    short = client.post(
        '/admin/integrations/igdb/save',
        json={'igdb_client_id': 'short', 'igdb_client_secret': 'short'},
        headers=headers,
    )
    saved = client.post(
        '/admin/integrations/igdb/save',
        json={'igdb_client_id': 'client-id-at-least-20', 'igdb_client_secret': 'client-secret-at-least-20'},
        headers=headers,
    )

    assert short.status_code == 400
    assert short.json()['error'] == 'Client ID and Secret must be at least 20 characters long'
    assert saved.status_code == 200
    assert saved.json()['message'] == 'IGDB settings saved successfully'
    assert 'status' not in saved.json()
    assert client.saved == [{
        'igdb_client_id': 'client-id-at-least-20',
        'igdb_client_secret': 'client-secret-at-least-20',
    }]


def test_integrations_igdb_save_allows_blank_secret_when_saved_secret_exists():
    client = _client()
    response = client.post(
        '/admin/integrations/igdb/save',
        json={'igdb_client_id': 'client-id-at-least-20', 'igdb_client_secret': ''},
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'IGDB settings saved successfully'
    assert 'status' not in response.json()
    assert client.saved == [{
        'igdb_client_id': 'client-id-at-least-20', 'igdb_client_secret': '',
    }]


def test_integrations_igdb_save_rejects_blank_replacement_of_short_saved_secret():
    client = _client(existing_secret_length=8)
    response = client.post(
        '/admin/integrations/igdb/save',
        json={'igdb_client_id': 'client-id-at-least-20', 'igdb_client_secret': ''},
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'Client ID and Secret must be at least 20 characters long'
    assert client.saved == []


def test_legacy_igdb_save_preserves_blank_secret_and_accepts_empty_client_id(monkeypatch):
    from oneirodex.runtime_native import db_session
    from oneirodex.runtime_native.igdb_settings_read import IgdbSettingsData
    from oneirodex.utils import global_settings

    settings = SimpleNamespace(
        igdb_client_id='old-id', igdb_client_secret='saved-secret',
    )
    session = SimpleNamespace(commits=0)
    session.commit = lambda: setattr(session, 'commits', session.commits + 1)
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=session))
    monkeypatch.setattr(global_settings, 'global_settings_row_or_create', lambda: settings)

    IgdbSettingsData().save_legacy({
        'igdb_client_id': '', 'igdb_client_secret': '',
    })

    assert settings.igdb_client_id == ''
    assert settings.igdb_client_secret == 'saved-secret'
    assert session.commits == 1


def test_legacy_igdb_post_matches_flask_json_parse_edges():
    client = _client()
    malformed = client.post(
        '/admin/igdb_settings', data='not-json',
        headers={'X-CSRFToken': client.csrf_token, 'Content-Type': 'application/json'},
    )
    assert malformed.status_code == 400
    assert malformed.text == (
        '<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n'
        '<h1>Bad Request</h1>\n'
        '<p>The browser (or proxy) sent a request that this server could not understand.</p>\n'
    )

    wrong_type = client.post(
        '/admin/igdb_settings', data='{}',
        headers={'X-CSRFToken': client.csrf_token, 'Content-Type': 'text/plain'},
    )
    assert wrong_type.status_code == 415
    assert 'The server does not support the media type transmitted in the request.' in wrong_type.text

    null_value = client.post(
        '/admin/igdb_settings', content='null',
        headers={'X-CSRFToken': client.csrf_token, 'Content-Type': 'application/json'},
    )
    assert null_value.status_code == 500
    assert '500 Internal Server Error' in null_value.text


def test_legacy_igdb_test_path_preserves_v118_success_body():
    client = _client()
    tested = client.post('/admin/test_igdb', headers={'X-CSRFToken': client.csrf_token})

    assert tested.status_code == 200
    assert tested.json() == {
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
        'status': 'success',
        'message': 'IGDB API test successful',
    }


def test_legacy_igdb_test_path_preserves_v118_missing_and_invalid_results():
    missing = _client(legacy_test=lambda: None)
    response = missing.post('/admin/test_igdb', headers={'X-CSRFToken': missing.csrf_token})
    assert response.status_code == 400
    assert response.json()['message'] == 'IGDB settings not configured'

    invalid = _client(legacy_test=lambda: False)
    response = invalid.post('/admin/test_igdb', headers={'X-CSRFToken': invalid.csrf_token})
    assert response.status_code == 500
    assert response.json()['message'] == 'Invalid API response'


def test_integrations_igdb_test_path_preserves_v118_unconfigured_message():
    client = _client(legacy_test=lambda: None)
    response = client.post(
        '/admin/integrations/igdb/test',
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 400
    assert response.json()['message'] == (
        'IGDB settings not configured. Please save your settings first.'
    )


def test_integrations_igdb_test_path_preserves_v118_invalid_response():
    client = _client(legacy_test=lambda: False)
    response = client.post(
        '/admin/integrations/igdb/test',
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 500
    assert response.json()['message'] == 'Invalid API response'


def test_legacy_integrations_igdb_aliases_use_native_save_and_test():
    client = _client()
    saved = client.post(
        '/admin/integrations/igdb/save',
        json={
            'igdb_client_id': 'alias-client-id-20chars',
            'igdb_client_secret': 'alias-secret-20-chars',
        },
        headers={'X-CSRFToken': client.csrf_token},
    )
    tested = client.post(
        '/admin/integrations/igdb/test', headers={'X-CSRFToken': client.csrf_token},
    )

    assert saved.status_code == 200
    assert saved.json()['message'] == 'IGDB settings saved successfully'
    assert client.saved == [{
        'igdb_client_id': 'alias-client-id-20chars',
        'igdb_client_secret': 'alias-secret-20-chars',
    }]
    assert tested.status_code == 200
    assert tested.json()['message'] == 'IGDB API test successful'
    assert 'status' not in tested.json()
