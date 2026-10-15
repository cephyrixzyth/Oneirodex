from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import status_reads as native_status
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie
from oneirodex.runtime_native.status_reads import create_status_reads_router


class FakeStatusData:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def status(self, *, config=None):
        self.calls += 1
        return self.payload


def make_client(*, role='admin', authenticated=True, adapters=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-status-reads-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=89, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    payloads = adapters or {
        'storage': FakeStatusData({
            'helpers_enabled': True, 'allow_apply': False, 'games_path': '/games',
            'games_exists': True, 'games_readable': True, 'games_writable': False,
            'degrade_reason': 'Apply disabled (ALLOW_HARDLINK_APPLY=false); games path is read-only',
        }),
        'malware': FakeStatusData({
            'enabled': True, 'block_on_hit': True,
            'heuristics': {'enabled': True, 'block_on_match': True},
            'clamav': {'available': False, 'reachable': False},
            'settings': {'clamav_host': 'clamav'}, 'note': 'Local status only',
        }),
        'rtc': FakeStatusData({'enabled': True, 'url': 'wss://rtc.example.test'}),
    }
    router = create_status_reads_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 89 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '89' else None,
        login_manager=manager,
        storage_data=payloads['storage'],
        malware_data=payloads['malware'],
        rtc_data=payloads['rtc'],
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '89:fp'}, 'native-status-reads-secret')
        )
    return client, payloads


def test_storage_and_malware_admin_status_return_exact_bare_payloads():
    client, data = make_client()
    for path, name in (
        ('/api/storage/status', 'storage'),
        ('/api/admin/malware-scan/status', 'malware'),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.json() == data[name].payload
        assert 'ok' not in response.json()
        assert data[name].calls == 1


def test_rtc_status_is_available_to_any_authenticated_member():
    client, data = make_client(role='user')
    response = client.get('/api/rtc/status')
    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data['rtc'].payload
    assert data['rtc'].calls == 1


def test_admin_status_routes_redirect_non_admin_with_danger_flash():
    client, data = make_client(role='user')
    for path, name in (
        ('/api/storage/status', 'storage'),
        ('/api/admin/malware-scan/status', 'malware'),
    ):
        response = client.get(path + '?from=settings', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'] == '/login'
        session = load_session_cookie(
            response.cookies['session'], 'native-status-reads-secret', max_age=31_536_000
        )
        assert session['_flashes'][-1] == ('danger', 'You must be an admin to access this page.')
        assert data[name].calls == 0


def test_admin_status_routes_require_admin_scope_on_api_tokens(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_status, 'request_auth_context', lambda *_args, **_kwargs: context)
    client, data = make_client()
    for path, name in (
        ('/api/storage/status', 'storage'),
        ('/api/admin/malware-scan/status', 'malware'),
    ):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json() == {
            'ok': False,
            'error': 'This token does not have the admin scope',
            'error_code': 'forbidden',
            'message': 'This token does not have the admin scope',
            'success': False,
        }
        assert data[name].calls == 0


def test_anonymous_status_reads_redirect_with_login_flash_and_next():
    client, data = make_client(authenticated=False)
    for path, name in (
        ('/api/storage/status', 'storage'),
        ('/api/admin/malware-scan/status', 'malware'),
        ('/api/rtc/status', 'rtc'),
    ):
        response = client.get(path + '?from=member', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'] == '/login?next=' + path.replace('/', '%2F') + '%3Ffrom%3Dmember'
        session = load_session_cookie(
            response.cookies['session'], 'native-status-reads-secret', max_age=31_536_000
        )
        assert session['_flashes'][-1] == ('message', 'Please log in to access this page.')
        assert data[name].calls == 0


def test_head_supports_all_three_status_routes():
    client, data = make_client()
    for path, name in (
        ('/api/storage/status', 'storage'),
        ('/api/admin/malware-scan/status', 'malware'),
        ('/api/rtc/status', 'rtc'),
    ):
        get_response = client.get(path)
        head_response = client.head(path)
        assert head_response.status_code == 200
        assert head_response.content == b''
        assert head_response.headers['content-length'] == str(len(get_response.content))
        assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
        assert data[name].calls == 2
