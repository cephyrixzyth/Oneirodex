from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import quality_profiles as native_profiles
from oneirodex.runtime_native.quality_profiles import create_quality_profiles_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token, load_session_cookie


class FakeQualityProfilesData:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'version': 2,
            'active_id': 'balanced',
            'profiles': [
                {'id': 'balanced', 'name': 'Balanced', 'min_seeders': 2, 'min_size_mb': 10},
                {'id': 'strict', 'name': 'Strict', 'min_seeders': 5, 'min_size_mb': 50},
            ],
            'min_seeders': 2,
            'min_size_mb': 10,
            'id': 'balanced',
            'name': 'Balanced',
        }

    def list(self):
        self.calls += 1
        return self.payload

    def create(self, payload):
        return {'id': payload.get('id', 'new'), 'name': payload.get('name', 'New')}

    def save(self, payload):
        return {'id': 'balanced', 'name': payload.get('name', 'Balanced')}

    def set_active(self, profile_id):
        return {'version': 2, 'active_id': profile_id, 'profiles': []}

    def get_one(self, profile_id):
        return {'id': profile_id, 'name': 'Example'}

    def update(self, profile_id, payload):
        return {'id': profile_id, 'name': payload.get('name', 'Updated')}

    def delete(self, profile_id):
        return {'deleted': profile_id}

    def score(self, *, title, size_bytes, profile_id):
        return {'title': title, 'size_bytes': size_bytes, 'profile_id': profile_id}


def make_client(*, role='admin', authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-quality-profiles-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_quality_profiles_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '71' else None,
        login_manager=manager,
        data_access=data or FakeQualityProfilesData(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        session_data = {'_user_id': '71:fp', '_fresh': True}
        client.csrf_token = generate_csrf_token(session_data, 'native-quality-profiles-secret')
        client.cookies.set(
            'session', dump_session_cookie(session_data, 'native-quality-profiles-secret')
        )
    return client


def test_admin_get_returns_exact_bare_profile_list_payload():
    data = FakeQualityProfilesData()
    response = make_client(data=data).get('/api/quality-profiles')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert 'ok' not in response.json()
    assert data.calls == 1


def test_anonymous_request_redirects_with_login_flash_and_next():
    data = FakeQualityProfilesData()
    response = make_client(authenticated=False, data=data).get(
        '/api/quality-profiles?from=settings', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Fquality-profiles%3Ffrom%3Dsettings'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-quality-profiles-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_non_admin_redirects_with_danger_flash_without_next_or_data_access():
    data = FakeQualityProfilesData()
    response = make_client(role='user', data=data).get(
        '/api/quality-profiles?from=settings', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-quality-profiles-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_admin_token_without_admin_scope_gets_existing_forbidden_envelope(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_profiles, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeQualityProfilesData()
    response = make_client(data=data).get('/api/quality-profiles')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'This token does not have the admin scope',
        'error_code': 'forbidden',
        'message': 'This token does not have the admin scope',
        'success': False,
    }
    assert data.calls == 0


def test_head_preserves_headers_and_content_length_without_body():
    data = FakeQualityProfilesData()
    client = make_client(data=data)
    get_response = client.get('/api/quality-profiles')
    head_response = client.head('/api/quality-profiles')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == 2


def test_quality_profile_crud_active_and_score_actions_preserve_contracts():
    data = FakeQualityProfilesData()
    client = make_client(data=data)
    no_csrf = client.post('/api/quality-profiles', json={'name': 'Fast'})
    created = client.post(
        '/api/quality-profiles', json={'name': 'Fast'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    saved = client.put(
        '/api/quality-profiles', json={'name': 'Balanced Plus'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    active = client.post(
        '/api/quality-profiles/active', json={'active_id': 'strict'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid_active = client.put(
        '/api/quality-profiles/active', json={},
        headers={'X-CSRFToken': client.csrf_token},
    )
    detail = client.get('/api/quality-profiles/strict')
    updated = client.patch(
        '/api/quality-profiles/strict', json={'name': 'Very Strict'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    deleted = client.delete(
        '/api/quality-profiles/strict', headers={'X-CSRFToken': client.csrf_token}
    )
    score = client.post(
        '/api/quality-profiles/score', json={'title': 'Game 1080p', 'size_bytes': 1000},
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert no_csrf.status_code == 400
    assert created.status_code == 201 and created.json() == {'id': 'new', 'name': 'Fast'}
    assert saved.status_code == 200 and saved.json()['name'] == 'Balanced Plus'
    assert active.status_code == 200 and active.json()['active_id'] == 'strict'
    assert invalid_active.status_code == 422
    assert detail.status_code == 200 and detail.json()['id'] == 'strict'
    assert updated.status_code == 200 and updated.json()['name'] == 'Very Strict'
    assert deleted.status_code == 200 and deleted.json()['deleted'] == 'strict'
    assert score.status_code == 200 and score.json()['size_bytes'] == 1000
