from __future__ import annotations

import hashlib
import hmac
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.account_summary import (
    AccountInvitesData,
    create_account_summary_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
    load_session_cookie,
)


class FakeAccountSummaryData:
    def __init__(self):
        self.calls = []
        self.payload = {
            'username': 'member-one',
            'email': 'member@example.test',
            'role': 'user',
            'avatar_path': '/static/avatars/member.png',
            'avatar_url': '/static/avatars/member.png',
            'stock_avatars': [{'id': 'oneirodex', 'path': '/static/avatars/oneirodex.svg', 'url': '/static/avatars/oneirodex.svg'}],
            'invite_quota': 5,
            'invites_used': 2,
            'invites_remaining': 3,
            'invites_unlimited': False,
            'smtp_enabled': True,
        }

    def summary(self, user):
        self.calls.append(user.id)
        return self.payload


class FakeAccountInvitesData:
    def __init__(self):
        self.calls = []
        self.payload = {
            'invites': [
                {
                    'token': 'opaque-invite-token',
                    'email': 'friend@example.test',
                    'url': 'https://games.example.test/invite/opaque-invite-token',
                    'created_at': '2026-10-12T12:00:00+00:00',
                    'expires_at': '2026-10-14T12:00:00+00:00',
                    'expired': False,
                },
                {
                    'token': 'manual-invite-token',
                    'email': None,
                    'url': 'https://games.example.test/invite/manual-invite-token',
                    'created_at': None,
                    'expires_at': None,
                    'expired': False,
                },
            ],
            'quota': 5,
            'remaining': 3,
            'unlimited': False,
            'smtp_enabled': False,
            'ttl_hours': 48,
            'site_url_configured': True,
        }

    def invites(self, user, *, origin=None):
        self.calls.append(user.id)
        return self.payload


class FakeAccountInviteMutations:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.origins = []
        self.create_result = {
            'invite': {'token': 'new-invite', 'email': 'friend@example.com'},
            'emailed': False,
            'remaining': 2,
            'unlimited': False,
        }
        self.delete_result = {'revoked': 'opaque-invite-token', 'remaining': 3}

    def invites(self, user, *, origin=None):
        return FakeAccountInvitesData().invites(user)

    def create(self, user, email, *, origin=None):
        self.created.append((user.id, email))
        self.origins.append(origin)
        return self.create_result

    def delete(self, user, token):
        self.deleted.append((user.id, token))
        return self.delete_result


def make_client(*, data=None, invites_data=None, user=None, mutations_data=None, no_app_context=True):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-account-summary-secret', TESTING=True)
    if no_app_context:
        flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('Flask app context used'))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    actor = user or SimpleNamespace(
        id=167, user_id='member-167', name='member-one', email='member@example.test',
        role='user', avatarpath='/static/avatars/member.png', invite_quota=5,
        is_active=True, state=True, is_authenticated=True,
    )
    token = SimpleNamespace(
        token_hash=hashlib.sha256(b'secretpart').hexdigest(),
        user_id=167,
        revoked_at=None,
        last_used_at=None,
        is_expired=lambda _now: False,
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
    router = create_account_summary_router(
        flask_app,
        find_user=lambda user_id: actor if user_id == 167 else None,
        find_token=lambda prefix: token if prefix == 'token-prefix' else None,
        commit_token_touch=touch_calls.append,
        load_user_id=lambda value: actor if value.split(':', 1)[0] == '167' else None,
        login_manager=manager,
        data_access=data or FakeAccountSummaryData(),
        invites_data=invites_data or FakeAccountInvitesData(),
        mutations_data=mutations_data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.native_actor = actor
    client.native_token = token
    client.native_touch_calls = touch_calls
    return client


def remember_cookie(user_id, secret='native-account-summary-secret'):
    key = secret.encode('latin1')
    digest = hmac.new(key, user_id.encode('utf-8'), hashlib.sha512).hexdigest()
    return f'{user_id}|{digest}'


def csrf_session(secret='native-account-summary-secret'):
    state = {'_user_id': '167:fp', '_fresh': True}
    token = generate_csrf_token(state, secret)
    return dump_session_cookie(state, secret), token


def test_admin_invite_delete_reports_no_numeric_remaining_quota(monkeypatch):
    from oneirodex.runtime_native import db_session

    invite = SimpleNamespace(token='admin-invite')

    class FakeSession:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: invite)

        def delete(self, deleted):
            assert deleted is invite

        def commit(self):
            return None

        def scalar(self, _statement):
            return 0

    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=FakeSession()))

    result = AccountInvitesData().delete(
        SimpleNamespace(user_id='admin-1', role='admin', invite_quota=0),
        'admin-invite',
    )

    assert result == {'revoked': 'admin-invite', 'remaining': None}


def test_invite_mail_adapter_uses_quiet_sender_with_preflight_and_audit_actor(monkeypatch):
    from oneirodex.utils import smtp

    sent = []
    monkeypatch.setattr(
        smtp, 'send_email_quiet',
        lambda to, subject, html, **kwargs: sent.append((to, subject, html, kwargs)) or True,
    )

    assert smtp.send_invite_email_quiet(
        'friend@example.test', 'https://games.example.test/register?token=opaque', audit_user=167,
    )
    assert sent[0][0:2] == ('friend@example.test', "You're Invited!")
    assert 'https://games.example.test/register?token=opaque' in sent[0][2]
    assert sent[0][3] == {'preflight': True, 'audit_user': 167}


def test_signed_session_get_returns_only_existing_account_payload_and_api_ok_envelope():
    data = FakeAccountSummaryData()
    client = make_client(data=data, no_app_context=True)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )
    response = client.get('/api/account/summary')
    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        **data.payload,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == [167]


def test_valid_remember_cookie_can_read_summary_and_persists_session_login():
    data = FakeAccountSummaryData()
    client = make_client(data=data, no_app_context=True)
    client.cookies.set('remember_token', remember_cookie('167:fp'))
    response = client.get('/api/account/summary')
    assert response.status_code == 200
    assert response.json()['username'] == 'member-one'
    assert 'session' in response.cookies
    session = load_session_cookie(
        response.cookies['session'], 'native-account-summary-secret', max_age=31_536_000
    )
    assert session['_user_id'] == '167:fp'
    assert session['_fresh'] is False
    assert data.calls == [167]


def test_valid_bearer_token_gets_browser_session_forbidden_envelope():
    data = FakeAccountSummaryData()
    client = make_client(data=data)
    response = client.get(
        '/api/account/summary', headers={'Authorization': 'Bearer gt_token-prefix_secretpart'}
    )
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'Sign in with your site account to manage invites',
        'error_code': 'forbidden',
        'message': 'Sign in with your site account to manage invites',
        'success': False,
    }
    assert client.native_touch_calls and client.native_token.last_used_at is not None
    assert data.calls == []


def test_anonymous_request_uses_login_redirect_and_flashes():
    data = FakeAccountSummaryData()
    client = make_client(data=data)
    response = client.get('/api/account/summary?from=account', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Faccount%2Fsummary%3Ffrom%3Daccount'
    session = load_session_cookie(
        response.cookies['session'], 'native-account-summary-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == []


def test_head_matches_get_length_and_does_not_include_body():
    data = FakeAccountSummaryData()
    client = make_client(data=data)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )
    get_response = client.get('/api/account/summary')
    head_response = client.head('/api/account/summary')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.calls == [167, 167]


def test_browser_session_invites_get_returns_legacy_fields_and_envelope():
    data = FakeAccountInvitesData()
    client = make_client(invites_data=data)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )
    response = client.get('/api/account/invites')
    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        **data.payload,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == [167]


def test_invites_accept_remember_cookie_and_persist_resulting_session():
    data = FakeAccountInvitesData()
    client = make_client(invites_data=data)
    client.cookies.set('remember_token', remember_cookie('167:fp'))
    response = client.get('/api/account/invites')
    assert response.status_code == 200
    assert response.json()['invites'] == data.payload['invites']
    assert 'session' in response.cookies
    session = load_session_cookie(
        response.cookies['session'], 'native-account-summary-secret', max_age=31_536_000
    )
    assert session['_user_id'] == '167:fp'
    assert session['_fresh'] is False
    assert data.calls == [167]


def test_invites_reject_valid_bearer_token_with_browser_session_error():
    data = FakeAccountInvitesData()
    client = make_client(invites_data=data)
    response = client.get(
        '/api/account/invites', headers={'Authorization': 'Bearer gt_token-prefix_secretpart'}
    )
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'Sign in with your site account to manage invites',
        'error_code': 'forbidden',
        'message': 'Sign in with your site account to manage invites',
        'success': False,
    }
    assert client.native_touch_calls and client.native_token.last_used_at is not None
    assert data.calls == []


def test_anonymous_invites_redirect_with_login_flash():
    data = FakeAccountInvitesData()
    response = make_client(invites_data=data).get(
        '/api/account/invites?from=account', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Faccount%2Finvites%3Ffrom%3Daccount'
    session = load_session_cookie(
        response.cookies['session'], 'native-account-summary-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == []


def test_invites_head_returns_headers_and_length_without_body():
    data = FakeAccountInvitesData()
    client = make_client(invites_data=data)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )
    get_response = client.get('/api/account/invites')
    head_response = client.head('/api/account/invites')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.calls == [167, 167]


def test_create_invite_requires_csrf_and_returns_created_payload():
    mutations = FakeAccountInviteMutations()
    client = make_client(invites_data=mutations, mutations_data=mutations)
    cookie, csrf = csrf_session()
    client.cookies.set('session', cookie)

    response = client.post(
        '/api/account/invites',
        json={'email': ' friend@example.com '},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 201
    assert response.json() == {
        **mutations.create_result,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert mutations.created == [(167, 'friend@example.com')]
    assert mutations.origins == ['http://testserver']


def test_create_invite_rejects_invalid_email_values_without_mutating():
    mutations = FakeAccountInviteMutations()
    client = make_client(invites_data=mutations, mutations_data=mutations)
    cookie, csrf = csrf_session()
    client.cookies.set('session', cookie)

    for email in ('not-an-email', 123):
        response = client.post(
            '/api/account/invites',
            json={'email': email},
            headers={'X-CSRFToken': csrf},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'Invalid email.'
        assert response.json()['error_code'] == 'bad_request'

    assert mutations.created == []


def test_create_invite_rejects_missing_csrf_before_mutating():
    mutations = FakeAccountInviteMutations()
    client = make_client(invites_data=mutations, mutations_data=mutations)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )

    response = client.post('/api/account/invites', json={})

    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert mutations.created == []


def test_invite_quota_error_keeps_forbidden_envelope():
    mutations = FakeAccountInviteMutations()
    mutations.create_result = {
        'error': "You're out of invites. An admin can raise your limit.",
        'code': 'forbidden',
    }
    client = make_client(invites_data=mutations, mutations_data=mutations)
    cookie, csrf = csrf_session()
    client.cookies.set('session', cookie)

    response = client.post('/api/account/invites', json={}, headers={'X-CSRFToken': csrf})

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert mutations.created == [(167, None)]


def test_delete_invite_requires_csrf_and_returns_revocation_payload():
    mutations = FakeAccountInviteMutations()
    client = make_client(invites_data=mutations, mutations_data=mutations)
    cookie, csrf = csrf_session()
    client.cookies.set('session', cookie)

    response = client.delete(
        '/api/account/invites/opaque-invite-token', headers={'X-CSRFToken': csrf}
    )

    assert response.status_code == 200
    assert response.json()['revoked'] == 'opaque-invite-token'
    assert mutations.deleted == [(167, 'opaque-invite-token')]


def test_delete_invite_rejects_missing_csrf_without_revoking():
    mutations = FakeAccountInviteMutations()
    client = make_client(invites_data=mutations, mutations_data=mutations)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '167:fp'}, 'native-account-summary-secret')
    )

    response = client.delete('/api/account/invites/opaque-invite-token')

    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert mutations.deleted == []
