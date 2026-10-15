from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.account_avatar_upload import (
    create_account_avatar_upload_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


SECRET = 'native-avatar-upload-secret'


class FakeAvatarData:
    def __init__(self, *, error=None, commit_error=None):
        self.error = error
        self.commit_error = commit_error
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def save(self, file, user, _app):
        self.calls.append((file.filename, file.read(), user.id))
        return ('library/images/avatars_users/new.png', self.error)

    def avatar_url(self, path):
        return '/' + path

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1


def make_client(*, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        SESSION_COOKIE_NAME='session',
        REMEMBER_COOKIE_NAME='remember_token',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=167,
        is_active=True,
        state=True,
        is_authenticated=True,
        avatarpath='old.png',
    )
    login_manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        session_protection='basic',
    )
    router = create_account_avatar_upload_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 167 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '167' else None,
        login_manager=login_manager,
        data_access=data or FakeAvatarData(),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def browser_headers():
    session = {'_user_id': '167:fp', '_fresh': True}
    csrf = generate_csrf_token(session, SECRET)
    return {
        'Cookie': 'session=' + dump_session_cookie(session, SECRET),
        'X-CSRFToken': csrf,
    }


def test_avatar_upload_extracts_file_and_preserves_success_payload():
    data = FakeAvatarData()
    client = make_client(data=data)

    response = client.post(
        '/api/account/avatar',
        headers=browser_headers(),
        files={'avatar': ('face.png', b'image-bytes', 'image/png')},
    )

    assert response.status_code == 200
    assert response.json() == {
        'avatar_path': 'library/images/avatars_users/new.png',
        'avatar_url': '/library/images/avatars_users/new.png',
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == [('face.png', b'image-bytes', 167)]
    assert data.commits == 1
    assert data.rollbacks == 0
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_missing_avatar_uses_existing_error_envelope():
    data = FakeAvatarData()
    response = make_client(data=data).post(
        '/api/account/avatar', headers=browser_headers(), data={'other': 'value'}
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'Choose an image first.'
    assert data.calls == []
    assert data.commits == 0


def test_invalid_content_type_is_treated_as_missing_file():
    response = make_client().post(
        '/api/account/avatar',
        headers={**browser_headers(), 'Content-Type': 'application/json'},
        content=b'{"avatar":"anything"}',
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'Choose an image first.'


def test_invalid_csrf_rejects_upload_before_file_adapter():
    data = FakeAvatarData()
    response = make_client(data=data).post(
        '/api/account/avatar',
        files={'avatar': ('face.png', b'image-bytes', 'image/png')},
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert data.calls == []
    assert data.commits == 0


def test_avatar_commit_failure_rolls_back_and_hides_internal_detail():
    data = FakeAvatarData(commit_error=RuntimeError('private database detail'))
    response = make_client(data=data).post(
        '/api/account/avatar',
        headers=browser_headers(),
        files={'avatar': ('face.png', b'image-bytes', 'image/png')},
    )

    assert response.status_code == 500
    assert response.json()['error'] == "Couldn't save that avatar. Try a different image."
    assert 'private database detail' not in response.text
    assert data.commits == 1
    assert data.rollbacks == 1


def test_legacy_profile_edit_get_redirects_to_avatar_settings():
    client = make_client()
    client.cookies.set('session', dump_session_cookie({'_user_id': '167:fp'}, SECRET))
    response = client.get('/settings_profile_edit', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/library?account=avatar'


def test_legacy_profile_edit_post_accepts_hidden_csrf_and_redirects():
    data = FakeAvatarData()
    client = make_client(data=data)
    session = {'_user_id': '167:fp', '_fresh': True}
    token = generate_csrf_token(session, SECRET)
    client.cookies.set('session', dump_session_cookie(session, SECRET))
    response = client.post(
        '/settings_profile_edit',
        data={'csrf_token': token},
        files={'avatar': ('face.png', b'image-bytes', 'image/png')},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/library?account=avatar'
    assert data.calls == [('face.png', b'image-bytes', 167)]
    assert data.commits == 1


def test_legacy_profile_edit_post_rejects_missing_hidden_csrf():
    data = FakeAvatarData()
    client = make_client(data=data)
    client.cookies.set('session', dump_session_cookie({'_user_id': '167:fp'}, SECRET))
    response = client.post(
        '/settings_profile_edit',
        files={'avatar': ('face.png', b'image-bytes', 'image/png')},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert data.calls == []
    assert data.commits == 0
