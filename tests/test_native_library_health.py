from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import library_health as native_health
from oneirodex.runtime_native.library_health import create_library_health_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeLibraryHealthData:
    def __init__(self):
        self.calls = []
        self.payload = {
            'count': 2,
            'average_score': 85.5,
            'grade_counts': {'good': 1, 'fair': 1},
            'top_issues': [{'code': 'missing_cover', 'count': 1}],
            'worst': [{'uuid': 'game-2', 'score': 71}],
            'library_uuid': 'library-a',
            'checked_at': '2026-10-13T00:00:00+00:00',
        }

    def summarize(self, *, limit, library_uuid):
        self.calls.append((limit, library_uuid))
        return self.payload


def make_client(*, role='admin', authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-library-health-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=53, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_library_health_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 53 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '53' else None,
        login_manager=manager,
        data_access=data or FakeLibraryHealthData(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '53:fp'}, 'native-library-health-secret')
        )
    return client


def test_admin_get_returns_exact_bare_summary_json():
    data = FakeLibraryHealthData()
    response = make_client(data=data).get('/api/health/library')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert 'ok' not in response.json()
    assert data.calls == [(200, None)]


def test_query_limit_uuid_trim_invalid_fallback_cap_and_first_duplicate_value():
    data = FakeLibraryHealthData()
    client = make_client(data=data)
    for query, expected in [
        ('?limit=bad&library_uuid=%20%20', (200, None)),
        ('?limit=9999&library_uuid=%20abc-123%20', (2000, 'abc-123')),
        ('?limit=25&limit=900&library_uuid=first&library_uuid=second', (25, 'first')),
        ('?limit=0&library_uuid=', (0, None)),
    ]:
        response = client.get('/api/health/library' + query)
        assert response.status_code == 200
        assert data.calls[-1] == expected


def test_negative_limit_keeps_legacy_value_without_lower_clamp():
    data = FakeLibraryHealthData()
    response = make_client(data=data).get('/api/health/library?limit=-3')
    assert response.status_code == 200
    assert data.calls == [(-3, None)]


def test_non_admin_receives_existing_forbidden_envelope_and_data_is_not_called():
    data = FakeLibraryHealthData()
    response = make_client(role='user', data=data).get('/api/health/library')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'Admin required',
        'error_code': 'forbidden',
        'message': 'Admin required',
        'success': False,
    }
    assert data.calls == []


def test_admin_bearer_without_admin_scope_is_forbidden(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_health, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeLibraryHealthData()
    response = make_client(data=data).get('/api/health/library')
    assert response.status_code == 403
    assert response.json()['error'] == 'Admin required'
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == []


def test_anonymous_request_redirects_with_login_flash_and_next():
    data = FakeLibraryHealthData()
    response = make_client(authenticated=False, data=data).get(
        '/api/health/library?limit=10', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Fhealth%2Flibrary%3Flimit%3D10'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-library-health-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == []


def test_head_has_same_headers_and_content_length_but_empty_body():
    data = FakeLibraryHealthData()
    client = make_client(data=data)
    get_response = client.get('/api/health/library')
    head_response = client.head('/api/health/library')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == [(200, None), (200, None)]
