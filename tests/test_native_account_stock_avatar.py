from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.account_stock_avatar import create_account_stock_avatar_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


SECRET = 'native-stock-avatar-secret'


class FakeStockAvatarData:
    def __init__(self, *, result=None, commit_error=None):
        self.result = result or ('/static/avatars/oneirodex.svg', None)
        self.commit_error = commit_error
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def set_stock(self, avatar_id, user, flask_app):
        self.calls.append((avatar_id, user.id))
        return self.result

    def avatar_url(self, path):
        return f'{path}?theme=dark'

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1


def make_client(*, data=None, user=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY=SECRET, TESTING=True, WTF_CSRF_ENABLED=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    actor = user or SimpleNamespace(
        id=167,
        user_id='member-167',
        name='member-one',
        role='user',
        is_active=True,
        state=True,
        is_authenticated=True,
    )
    token = SimpleNamespace(
        token_hash=hashlib.sha256(b'secretpart').hexdigest(),
        user_id=167,
        revoked_at=None,
        last_used_at=None,
        is_expired=lambda _now: False,
        scopes=['account:write'],
    )
    touch_calls = []
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_account_stock_avatar_router(
        flask_app,
        find_user=lambda user_id: actor if user_id == 167 else None,
        find_token=lambda prefix: token if prefix == 'token-prefix' else None,
        commit_token_touch=touch_calls.append,
        load_user_id=lambda value: actor if value.split(':', 1)[0] == '167' else None,
        login_manager=manager,
        data_access=data or FakeStockAvatarData(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.native_actor = actor
    client.native_token = token
    client.native_touch_calls = touch_calls
    return client


def signed_session(*, secret=SECRET):
    state = {'_user_id': '167:fp', '_fresh': True}
    csrf = generate_csrf_token(state, secret)
    return dump_session_cookie(state, secret), csrf


def _assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()['ok'] is False
    assert response.json()['error_code'] == code
    assert response.json()['success'] is False


def test_stock_avatar_post_returns_legacy_projection_and_commits():
    data = FakeStockAvatarData()
    client = make_client(data=data)
    cookie, csrf = signed_session()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/avatar/stock',
        json={'id': ' oneirodex '},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        'avatar_path': '/static/avatars/oneirodex.svg',
        'avatar_url': '/static/avatars/oneirodex.svg?theme=dark',
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == [('oneirodex', 167)]
    assert data.commits == 1
    assert data.rollbacks == 0


def test_bearer_authenticated_user_can_select_avatar_with_csrf_session():
    data = FakeStockAvatarData()
    client = make_client(data=data)
    csrf_state = {}
    csrf = generate_csrf_token(csrf_state, SECRET)
    client.cookies.set('session', dump_session_cookie(csrf_state, SECRET))

    response = client.post(
        '/api/account/avatar/stock',
        json={'id': 'oneirodex'},
        headers={
            'Authorization': 'Bearer gt_token-prefix_secretpart',
            'X-CSRFToken': csrf,
        },
    )

    assert response.status_code == 200
    assert data.calls == [('oneirodex', 167)]
    assert client.native_touch_calls
    assert client.native_token.last_used_at is not None


def test_csrf_is_required_before_auth_or_mutation():
    data = FakeStockAvatarData()
    client = make_client(data=data)

    response = client.post('/api/account/avatar/stock', json={'id': 'oneirodex'})

    _assert_error(response, 400, 'bad_request')
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert data.calls == []
    assert data.commits == 0


def test_anonymous_with_valid_csrf_uses_flask_login_redirect_and_flash():
    data = FakeStockAvatarData()
    client = make_client(data=data)
    state = {}
    csrf = generate_csrf_token(state, SECRET)
    client.cookies.set('session', dump_session_cookie(state, SECRET))

    response = client.post(
        '/api/account/avatar/stock?from=account',
        json={'id': 'oneirodex'},
        headers={'X-CSRFToken': csrf},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Faccount%2Favatar%2Fstock%3Ffrom%3Daccount'
    assert data.calls == []
    assert 'session' in response.cookies


def test_invalid_body_matches_shared_validation_envelope():
    data = FakeStockAvatarData()
    client = make_client(data=data)
    cookie, csrf = signed_session()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/avatar/stock',
        json={'id': '   '},
        headers={'X-CSRFToken': csrf},
    )

    _assert_error(response, 422, 'unprocessable')
    assert response.json()['error'] == 'Invalid request.'
    assert 'id' in response.json()['detail']
    assert data.calls == []


def test_unknown_stock_id_returns_bad_request_without_commit():
    data = FakeStockAvatarData(result=(None, 'That is not one of the avatars we ship.'))
    client = make_client(data=data)
    cookie, csrf = signed_session()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/avatar/stock',
        json={'id': 'not-shipped'},
        headers={'X-CSRFToken': csrf},
    )

    _assert_error(response, 400, 'bad_request')
    assert response.json()['error'] == 'That is not one of the avatars we ship.'
    assert data.calls == [('not-shipped', 167)]
    assert data.commits == 0


def test_commit_failure_rolls_back_and_uses_legacy_internal_error():
    data = FakeStockAvatarData(commit_error=RuntimeError('private db detail'))
    client = make_client(data=data)
    cookie, csrf = signed_session()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/avatar/stock',
        json={'id': 'oneirodex'},
        headers={'X-CSRFToken': csrf},
    )

    _assert_error(response, 500, 'internal')
    assert response.json()['error'] == "Couldn't save that avatar. Try a different image."
    assert 'private db detail' not in response.text
    assert data.commits == 1
    assert data.rollbacks == 1
