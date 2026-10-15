from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.acquire_status import create_acquire_status_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeStatusData:
    def __init__(self):
        self.users = []

    def status(self, user):
        self.users.append(user)
        return {
            'enabled': True,
            'arr_enabled': True,
            'debrid_enabled': False,
            'debrid': {'enabled': False},
            'can_send': user.role == 'admin',
            'clients': ['qbittorrent', 'transmission', 'sabnzbd', 'nzbget'],
            'native_ready': True,
            'hubs_ready': False,
            'indexers_ready': True,
            'indexer_warnings': ['one indexer is unavailable'],
            'native_count': 2,
            'native_ready_count': 1,
            'message': 'Acquisition ready (native indexers / hubs / debrid configured by admin).',
        }


def make_client(*, authenticated=True, data=None, login_view='login'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-acquire-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login')
    user = SimpleNamespace(id=17, role='admin', is_active=True, state=True)
    manager = SimpleNamespace(
        login_view=login_view,
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_acquire_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 17 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '17' else None,
        login_manager=manager,
        data_access=data or FakeStatusData(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '17:fp'}, 'native-acquire-secret')
        )
    return client


def test_status_returns_legacy_payload_with_shared_api_envelope():
    data = FakeStatusData()
    response = make_client(data=data).get('/api/acquire/status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    body = response.json()
    assert body == {
        'enabled': True,
        'arr_enabled': True,
        'debrid_enabled': False,
        'debrid': {'enabled': False},
        'can_send': True,
        'clients': ['qbittorrent', 'transmission', 'sabnzbd', 'nzbget'],
        'native_ready': True,
        'hubs_ready': False,
        'indexers_ready': True,
        'indexer_warnings': ['one indexer is unavailable'],
        'native_count': 2,
        'native_ready_count': 1,
        'message': 'Acquisition ready (native indexers / hubs / debrid configured by admin).',
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.users[0].id == 17


def test_anonymous_status_uses_flask_login_redirect_and_signed_flash_session():
    response = make_client(authenticated=False).get(
        '/api/acquire/status?from=member', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Facquire%2Fstatus%3Ffrom%3Dmember'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'httponly' in response.headers['set-cookie'].lower()
    session_cookie = response.cookies['session']
    session = load_session_cookie(
        session_cookie, 'native-acquire-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]


def test_status_never_calls_data_for_unauthenticated_requests():
    data = FakeStatusData()
    response = make_client(authenticated=False, data=data).get(
        '/api/acquire/status', follow_redirects=False
    )
    assert response.status_code == 302
    assert data.users == []


def test_status_head_matches_get_headers_without_a_body():
    client = make_client()
    get_response = client.get('/api/acquire/status')
    head_response = client.head('/api/acquire/status')

    assert head_response.status_code == get_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))

