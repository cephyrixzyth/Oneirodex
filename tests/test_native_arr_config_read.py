from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.arr_config_read import create_arr_config_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.utils.arr_connectors import public_arr_config


def _client(*, role='admin', enabled=True):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-arr-config-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='arr-user', role=role,
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
    router = create_arr_config_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=SimpleNamespace(
            read=lambda **_kwargs: {
                'prowlarr_url': 'https://indexer.example',
                'prowlarr_api_key_set': True,
                'qbittorrent_password_set': True,
            },
            save=lambda payload, **_kwargs: saved.append(payload),
        ),
        module_enabled=lambda **_kwargs: enabled,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY']))
    client.saved_payloads = saved
    return client


def test_arr_config_read_keeps_redacted_bare_payload_and_head():
    client = _client()
    response = client.get('/api/arr/config')
    head = client.head('/api/arr/config')

    assert response.status_code == 200
    assert response.json() == {
        'prowlarr_url': 'https://indexer.example',
        'prowlarr_api_key_set': True,
        'qbittorrent_password_set': True,
    }
    assert 'prowlarr_api_key' not in response.json()
    assert 'qbittorrent_password' not in response.json()
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_arr_config_read_keeps_disabled_and_admin_gates():
    disabled = _client(enabled=False).get('/api/arr/config')
    forbidden = _client(role='user').get('/api/arr/config', follow_redirects=False)
    assert disabled.status_code == 403
    assert disabled.json()['error'] == 'Arr module is disabled'
    assert forbidden.status_code == 302


def test_public_arr_config_only_exposes_credential_presence():
    output = public_arr_config({
        'prowlarr_url': 'https://indexer.example',
        'prowlarr_api_key': 'secret-key',
        'qbittorrent_password': 'secret-password',
    })
    assert output['prowlarr_api_key_set'] is True
    assert output['qbittorrent_password_set'] is True
    assert 'prowlarr_api_key' not in output
    assert 'qbittorrent_password' not in output


def test_arr_config_put_checks_csrf_keeps_public_projection_and_module_gate():
    client = _client()
    payload = {'prowlarr_url': 'https://new-indexer.example', 'prowlarr_api_key': 'new-secret'}
    missing_csrf = client.put('/api/arr/config', json=payload)
    saved = client.put(
        '/api/arr/config', json=payload, headers={'X-CSRFToken': client.csrf_token}
    )
    disabled_client = _client(enabled=False)
    disabled = disabled_client.put(
        '/api/arr/config', json=payload, headers={'X-CSRFToken': disabled_client.csrf_token}
    )
    assert missing_csrf.status_code == 400
    assert saved.status_code == 200
    assert saved.json()['status'] == 'saved'
    assert saved.json()['config']['prowlarr_api_key_set'] is True
    assert 'new-secret' not in saved.text
    assert client.saved_payloads == [payload]
    assert disabled.status_code == 403
