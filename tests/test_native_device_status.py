from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import device_status as native_device_status
from oneirodex.runtime_native.device_status import (
    AmbientLightingStatusData,
    ChallengeSolverStatusData,
    create_device_status_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token, load_session_cookie,
)


class FakeDeviceStatus:
    def __init__(self, payload):
        self.payload = payload
        self.probes = []
        self.configs = []

    def status(self, *, probe, config=None):
        self.probes.append(probe)
        return {**self.payload, 'probe_requested': probe}

    def read_config(self, *, config=None):
        return {'enabled': False, 'secret_configured': True}

    def save_config(self, payload, *, config=None):
        self.configs.append(payload)
        return {'enabled': payload.get('enabled', False), 'secret_configured': True}


def make_client(*, role='admin', authenticated=True, adapters=None, forbid_app_context=False):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-device-status-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    if forbid_app_context:
        def app_context_is_forbidden():
            raise AssertionError('native device status route pushed a Flask app context')

        flask_app.app_context = app_context_is_forbidden
    user = SimpleNamespace(
        id=97, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    data = adapters or {
        'challenge': FakeDeviceStatus({'enabled': True, 'provider': 'local'}),
        'ambient': FakeDeviceStatus({'enabled': False, 'device': None}),
    }
    router = create_device_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 97 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '97' else None,
        login_manager=manager,
        challenge_data=data['challenge'],
        ambient_data=data['ambient'],
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '97:fp'}, 'native-device-status-secret')
        )
    return client, data


def test_both_admin_status_routes_return_the_bare_adapter_payload():
    client, data = make_client()
    for path, name, payload in (
        ('/api/admin/challenge-solver/status', 'challenge', {'enabled': True, 'provider': 'local'}),
        ('/api/admin/ambient-lighting/status', 'ambient', {'enabled': False, 'device': None}),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.json() == {**payload, 'probe_requested': False}
        assert 'ok' not in response.json()
        assert data[name].probes == [False]


def test_admin_status_route_does_not_push_request_wide_flask_app_context():
    client, _data = make_client(forbid_app_context=True)
    for path in (
        '/api/admin/challenge-solver/status',
        '/api/admin/ambient-lighting/status',
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()['probe_requested'] is False


def test_probe_parsing_matches_first_value_lowercase_without_whitespace_trimming():
    client, data = make_client()
    cases = [
        ('?probe=1', True),
        ('?probe=TrUe', True),
        ('?probe=YES', True),
        ('?probe= true', False),
        ('?probe=on', False),
        ('?probe=0&probe=yes', False),
    ]
    for query, expected in cases:
        response = client.get('/api/admin/challenge-solver/status' + query)
        assert response.status_code == 200
        assert response.json()['probe_requested'] is expected
    assert data['challenge'].probes == [expected for _, expected in cases]


def test_anonymous_requests_redirect_with_next_and_login_flash():
    client, data = make_client(authenticated=False)
    for path, name in (
        ('/api/admin/challenge-solver/status', 'challenge'),
        ('/api/admin/ambient-lighting/status', 'ambient'),
    ):
        response = client.get(path + '?probe=yes', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'] == '/login?next=' + path.replace('/', '%2F') + '%3Fprobe%3Dyes'
        session = load_session_cookie(
            response.cookies['session'], 'native-device-status-secret', max_age=31_536_000
        )
        assert session['_flashes'][-1] == ('message', 'Please log in to access this page.')
        assert data[name].probes == []


def test_non_admins_redirect_with_danger_flash_and_no_probe():
    client, data = make_client(role='user')
    for path, name in (
        ('/api/admin/challenge-solver/status', 'challenge'),
        ('/api/admin/ambient-lighting/status', 'ambient'),
    ):
        response = client.get(path + '?probe=yes', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'] == '/login'
        session = load_session_cookie(
            response.cookies['session'], 'native-device-status-secret', max_age=31_536_000
        )
        assert session['_flashes'][-1] == ('danger', 'You must be an admin to access this page.')
        assert data[name].probes == []


def test_admin_tokens_need_admin_scope(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_device_status, 'request_auth_context', lambda *_args, **_kwargs: context)
    client, data = make_client()
    for path, name in (
        ('/api/admin/challenge-solver/status', 'challenge'),
        ('/api/admin/ambient-lighting/status', 'ambient'),
    ):
        response = client.get(path + '?probe=yes')
        assert response.status_code == 403
        assert response.json()['error'] == 'This token does not have the admin scope'
        assert response.json()['error_code'] == 'forbidden'
        assert data[name].probes == []


def test_head_keeps_headers_and_content_length_for_both_routes():
    client, data = make_client()
    for path, name in (
        ('/api/admin/challenge-solver/status', 'challenge'),
        ('/api/admin/ambient-lighting/status', 'ambient'),
    ):
        get_response = client.get(path)
        head_response = client.head(path)
        assert head_response.status_code == 200
        assert head_response.content == b''
        assert head_response.headers['content-length'] == str(len(get_response.content))
        assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
        assert data[name].probes[-2:] == [False, False]


def test_status_adapters_accept_config_without_a_flask_context(monkeypatch):
    from oneirodex.utils import ambient_lighting, challenge_solver

    monkeypatch.setattr(challenge_solver, '_arr_cfg', lambda: {})
    monkeypatch.setattr(ambient_lighting, '_lighting_cfg', lambda: {})

    challenge = ChallengeSolverStatusData().status(
        probe=False, config={'ENABLE_CHALLENGE_SOLVER': False}
    )
    ambient = AmbientLightingStatusData().status(
        probe=False, config={'ENABLE_AMBIENT_LIGHTING': False}
    )

    assert challenge['enabled'] is False
    assert challenge['env_enabled'] is False
    assert ambient['enabled'] is False
    assert ambient['env_enabled'] is False


def test_device_config_reads_writes_and_probe_actions_preserve_contract():
    client, data = make_client()
    path = '/api/admin/ambient-lighting/config'
    read = client.get(path)
    assert read.status_code == 200
    assert read.json() == {'enabled': False, 'secret_configured': True}

    missing_csrf = client.put(path, json={'enabled': True})
    assert missing_csrf.status_code == 400
    assert data['ambient'].configs == []

    session = {'_user_id': '97:fp'}
    csrf = generate_csrf_token(session, 'native-device-status-secret')
    client.cookies.clear()
    client.cookies.set('session', dump_session_cookie(session, 'native-device-status-secret'))
    headers = {'X-CSRFToken': csrf}
    written = client.put(path, json={'enabled': True}, headers=headers)
    probed = client.post('/api/admin/ambient-lighting/test', headers=headers)
    assert written.status_code == 200, written.text
    assert written.json() == {
        'enabled': True, 'secret_configured': True, 'status': 'saved',
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert probed.status_code == 200
    assert probed.json()['probe_requested'] is True
    assert data['ambient'].configs == [{'enabled': True}]
    assert data['ambient'].probes == [True]


def test_device_config_head_preserves_legacy_non_get_validation():
    client, _data = make_client()
    for path in (
        '/api/admin/ambient-lighting/config',
        '/api/admin/challenge-solver/config',
    ):
        response = client.head(path)
        assert response.status_code == 400
        assert response.content == b''
        assert response.headers['content-length'] == '118'
