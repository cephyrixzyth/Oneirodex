from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from types import SimpleNamespace

from oneirodex.runtime_native.account_preferences import create_account_preferences_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakePreferencesData:
    def __init__(self):
        self.reads = []
        self.updates = []
        self.payload = {
            'preferences': {'theme': 'default', 'tile_size': '50'},
            'choices': {'themes': [{'id': 'default', 'label': 'Default'}]},
            'member_engine_choice': 'system',
            'is_admin': False,
        }

    def choices(self, user):
        self.reads.append(user.id)
        return self.payload

    def update(self, user, payload):
        self.updates.append((user.id, payload))
        return {'preferences': {**self.payload['preferences'], **payload}}, 200


def make_client(data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-preferences-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    actor = SimpleNamespace(
        id=167, user_id='member-167', name='member-one', role='user',
        is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_account_preferences_router(
        flask_app,
        find_user=lambda user_id: actor if user_id == 167 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: actor if value.split(':', 1)[0] == '167' else None,
        login_manager=manager,
        data_access=data or FakePreferencesData(),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), actor


def signed_session(*, csrf=False):
    state = {'_user_id': '167:fp', '_fresh': True}
    token = generate_csrf_token(state, 'native-preferences-secret') if csrf else None
    return dump_session_cookie(state, 'native-preferences-secret'), token


def test_preferences_get_preserves_payload_and_signed_session_access():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, _ = signed_session()
    client.cookies.set('session', cookie)

    response = client.get('/api/account/preferences')

    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json()['preferences'] == data.payload['preferences']
    assert data.reads == [167]


def test_preferences_head_has_get_length_without_body():
    client, _actor = make_client()
    cookie, _ = signed_session()
    client.cookies.set('session', cookie)
    get = client.get('/api/account/preferences')
    head = client.head('/api/account/preferences')

    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))


def test_preferences_put_requires_flask_compatible_csrf_and_updates():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, csrf = signed_session(csrf=True)
    client.cookies.set('session', cookie)

    response = client.put(
        '/api/account/preferences',
        json={'tile_size': '72', 'show_tile_titles': False},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['preferences']['tile_size'] == '72'
    assert data.updates == [(167, {'tile_size': '72', 'show_tile_titles': False})]


def test_preferences_put_rejects_missing_csrf_before_data_access():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, _ = signed_session()
    client.cookies.set('session', cookie)

    response = client.put('/api/account/preferences', json={'theme': 'default'})

    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert data.updates == []


def test_preferences_put_matches_pydantic_body_error_envelope():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, csrf = signed_session(csrf=True)
    client.cookies.set('session', cookie)

    response = client.put(
        '/api/account/preferences',
        json={'unrecognized': 'value'},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 422
    assert response.json()['error_code'] == 'unprocessable'
    assert response.json()['detail'] == {'unrecognized': 'Extra inputs are not permitted'}
    assert data.updates == []


def test_preferences_anonymous_uses_flask_login_redirect_and_flash():
    client, _actor = make_client()

    response = client.get('/api/account/preferences?from=account', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Faccount%2Fpreferences%3Ffrom%3Daccount'
    assert 'session' in response.cookies


def test_legacy_preferences_form_accepts_hidden_csrf_and_preserves_json_contract():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, csrf = signed_session(csrf=True)
    client.cookies.set('session', cookie)

    response = client.post(
        '/settings_panel',
        data={
            'csrf_token': csrf,
            '_full_form': '1',
            'theme': 'default',
            'icon_pack': 'outline',
            'font': 'system-ui',
            'tile_size': '72',
        },
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'Preferences updated successfully!'
    assert data.updates == [(167, {
        'theme': 'default',
        'icon_pack': 'outline',
        'font': 'system-ui',
        'tile_size': '72',
        'show_tile_titles': False,
    })]


def test_legacy_preferences_form_rejects_missing_hidden_csrf():
    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, _csrf = signed_session()
    client.cookies.set('session', cookie)

    response = client.post('/settings_panel', data={'tile_size': '72'})

    assert response.status_code == 400
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is missing.</p>' in response.content
    assert data.updates == []


def test_legacy_preferences_form_uses_first_repeated_field_value():
    from urllib.parse import urlencode

    data = FakePreferencesData()
    client, _actor = make_client(data)
    cookie, csrf = signed_session(csrf=True)
    client.cookies.set('session', cookie)

    response = client.post(
        '/settings_panel',
        content=urlencode([
            ('csrf_token', csrf),
            ('tile_size', '55'),
            ('tile_size', '72'),
        ]),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )

    assert response.status_code == 200
    assert data.updates == [(167, {'tile_size': '55'})]
