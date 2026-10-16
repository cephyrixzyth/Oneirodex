from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from flask_login import encode_cookie

from oneirodex.runtime_native.account_password import create_account_password_router
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
    load_session_cookie,
)


SECRET = 'native-account-password-secret'


class FakeUser:
    def __init__(self):
        self.id = 167
        self.is_active = True
        self.state = True
        self.password_hash = 'old-hash'
        self.password = 'OldPassword1!'

    def get_id(self):
        fingerprint = hashlib.sha256(self.password_hash.encode()).hexdigest()[:16]
        return f'{self.id}:{fingerprint}'

    def check_password(self, value):
        return value == self.password

    def set_password(self, value):
        self.password = value
        self.password_hash = 'new-' + value


class FakePasswordData:
    def __init__(self, user, *, commit_error=None):
        self.user = user
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    def get_user(self, user_id):
        return self.user if user_id == self.user.id else None

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1


def make_client(*, data=None):
    user = data.user if data else FakeUser()
    data = data or FakePasswordData(user)
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        SESSION_COOKIE_NAME='session',
        REMEMBER_COOKIE_NAME='remember_token',
        REMEMBER_COOKIE_DURATION=timedelta(days=365),
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    login_manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        session_protection='basic',
    )
    router = create_account_password_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 167 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '167' else None,
        login_manager=login_manager,
        data_access=data,
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    return TestClient(app), user, data


def credentials():
    session = {'_user_id': '167:old-fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, SECRET)
    return dump_session_cookie(session, SECRET), csrf


def test_password_change_updates_session_and_remember_cookie_fingerprint():
    client, user, data = make_client()
    cookie, csrf = credentials()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/password',
        json={
            'current_password': 'OldPassword1!',
            'new_password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['changed'] is True
    assert data.commits == 1
    assert data.rollbacks == 0
    expected_id = user.get_id()
    session = load_session_cookie(
        response.cookies.get('session'), SECRET, max_age=31_536_000
    )
    assert session['_user_id'] == expected_id
    assert session['_fresh'] is True
    assert session['_id']
    remember = response.cookies.get('remember_token')
    assert remember == encode_cookie(expected_id, key=SECRET)


def test_wrong_current_password_does_not_mutate_or_commit():
    client, user, data = make_client()
    cookie, csrf = credentials()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/password',
        json={
            'current_password': 'wrong',
            'new_password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 401
    assert response.json()['error'] == 'Current password is incorrect.'
    assert user.password == 'OldPassword1!'
    assert data.commits == 0


def test_password_validation_preserves_minimum_and_confirmation_checks():
    client, _user, data = make_client()
    cookie, csrf = credentials()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/password',
        json={
            'current_password': 'OldPassword1!',
            'new_password': 'short',
            'confirm_password': 'different',
        },
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 422
    assert 'at least 8 characters' in response.json()['error']
    assert data.commits == 0


def test_invalid_csrf_rejects_password_change_before_adapter():
    client, _user, data = make_client()

    response = client.post(
        '/api/account/password',
        json={
            'current_password': 'OldPassword1!',
            'new_password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert data.commits == 0


def test_commit_failure_rolls_back_and_does_not_leak_exception():
    user = FakeUser()
    data = FakePasswordData(user, commit_error=RuntimeError('database secret'))
    client, _user, _data = make_client(data=data)
    cookie, csrf = credentials()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/password',
        json={
            'current_password': 'OldPassword1!',
            'new_password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 500
    assert response.json()['error'] == 'Could not change your password.'
    assert 'database secret' not in response.text
    assert data.rollbacks == 1


def test_legacy_password_form_uses_hidden_csrf_and_refreshes_session():
    client, user, data = make_client()
    cookie, csrf = credentials()
    client.cookies.set('session', cookie)

    response = client.post(
        '/settings_password',
        data={
            'csrf_token': csrf,
            'current_password': 'OldPassword1!',
            'password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/library?account=password'
    assert user.password == 'NewPassword2!'
    assert data.commits == 1
    assert response.cookies.get('remember_token') == encode_cookie(user.get_id(), key=SECRET)


def test_legacy_password_form_requires_csrf():
    client, _user, data = make_client()
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '167:old-fingerprint', '_fresh': True}, SECRET,
    ))

    response = client.post(
        '/settings_password',
        data={
            'current_password': 'OldPassword1!',
            'password': 'NewPassword2!',
            'confirm_password': 'NewPassword2!',
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert data.commits == 0
