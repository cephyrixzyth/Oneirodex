"""JSON password reset preserves token, enumeration, and session behavior."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from oneirodex.models import User
from oneirodex.runtime_native.auth_pages import AuthPageData
from oneirodex.runtime_native.password_reset_confirm import PasswordResetConfirmData
from oneirodex.utils.tokens import password_reset_token_digest


def reset_user(db_session):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'reset_{suffix}', email=f'reset_{suffix}@example.com',
        password_hash='placeholder', role='user', user_id=str(uuid4()),
        is_email_verified=True,
    )
    user.set_password('current password')
    db_session.add(user)
    db_session.commit()
    return user


def test_reset_request_response_does_not_reveal_account_existence(client, db_session, monkeypatch):
    import oneirodex.routes_login as routes_login

    user = reset_user(db_session)
    sent = []
    monkeypatch.setattr(routes_login, 'send_password_reset_email', lambda *args: sent.append(args))

    known = client.post('/api/auth/password-reset/request', json={'email': user.email})
    unknown = client.post('/api/auth/password-reset/request', json={'email': 'missing@example.com'})

    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()
    assert known.get_json()['requested'] is True
    assert len(sent) == 1 and sent[0][0] == user.email
    db_session.refresh(user)
    assert user.password_reset_token == password_reset_token_digest(sent[0][1])
    assert user.password_reset_token != sent[0][1]
    assert user.token_creation_time is not None


def test_recipient_throttle_is_cross_ip_and_does_not_reveal_account_existence(
    app, client, db_session, monkeypatch,
):
    import oneirodex.routes_login as routes_login
    from oneirodex.utils.login_rate_limit import reset_for_tests

    reset_for_tests()
    app.config['LOGIN_RATE_LIMIT_ATTEMPTS'] = 2
    app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = 300
    user = reset_user(db_session)
    sent = []
    monkeypatch.setattr(routes_login, 'send_password_reset_email', lambda *args: sent.append(args))

    def request(email, index):
        return client.post(
            '/api/auth/password-reset/request', json={'email': email},
            environ_base={'REMOTE_ADDR': f'198.51.100.{index}'},
        )

    known = [request(user.email, index) for index in (10, 11)]
    known_limited = request(user.email, 12)
    unknown = [request('missing@example.com', index) for index in (20, 21)]
    unknown_limited = request('missing@example.com', 22)

    responses = [*known, known_limited, *unknown, unknown_limited]
    assert all(response.status_code == 200 for response in responses)
    assert known_limited.get_json() == unknown_limited.get_json()
    assert known_limited.get_json()['requested'] is True
    assert len(sent) == 2
    reset_for_tests()


def test_native_recipient_throttle_is_shared_across_ips(app, db_session, monkeypatch):
    from starlette.requests import Request

    import oneirodex.utils.smtp as smtp
    from oneirodex.runtime_native.password_reset_confirm import PasswordResetConfirmData
    from oneirodex.utils.login_rate_limit import reset_for_tests

    reset_for_tests()
    app.config['LOGIN_RATE_LIMIT_ATTEMPTS'] = 1
    app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = 300
    user = reset_user(db_session)
    sent = []
    monkeypatch.setattr(smtp, 'send_email_quiet', lambda *args, **kwargs: sent.append(args))
    data = PasswordResetConfirmData()

    def native_request(ip):
        return Request({
            'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': 'POST', 'scheme': 'http',
            'server': ('localhost', 5006), 'client': (ip, 12345),
            'root_path': '', 'path': '/api/auth/password-reset/request',
            'raw_path': b'/api/auth/password-reset/request', 'query_string': b'',
            'headers': [(b'host', b'localhost:5006')],
        })

    with app.test_request_context('/api/auth/password-reset/request'):
        first = data.request_reset(
            user.email, '198.51.100.31', native_request('198.51.100.31'), app.config,
        )
        second = data.request_reset(
            user.email, '198.51.100.32', native_request('198.51.100.32'), app.config,
        )

    assert first == second == 'requested'
    assert len(sent) == 1
    assert len(user.password_reset_token) == 64
    reset_for_tests()


def test_reset_confirmation_updates_password_clears_token_and_keeps_guest_logged_out(client, db_session):
    user = reset_user(db_session)
    raw_token = f'reset-{uuid4().hex}'
    user.password_reset_token = password_reset_token_digest(raw_token)
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    response = client.post(f'/api/auth/password-reset/{raw_token}', json={
        'password': 'brand-new-password',
        'confirm_password': 'brand-new-password',
    })

    assert response.status_code == 200
    assert response.get_json()['reset'] is True
    assert user.check_password('brand-new-password')
    assert user.password_reset_token is None
    assert client.get('/api/account/summary').status_code == 302


def test_reset_confirmation_refuses_expired_token(client, db_session):
    user = reset_user(db_session)
    user.password_reset_token = f'expired-{uuid4().hex}'
    user.token_creation_time = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.commit()

    response = client.post(f'/api/auth/password-reset/{user.password_reset_token}', json={
        'password': 'brand-new-password',
        'confirm_password': 'brand-new-password',
    })

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    assert user.check_password('current password')


def test_reset_confirmation_preserves_password_form_validation(client, db_session):
    user = reset_user(db_session)
    raw_token = f'reset-{uuid4().hex}'
    user.password_reset_token = password_reset_token_digest(raw_token)
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    response = client.post(f'/api/auth/password-reset/{raw_token}', json={
        'password': 'short', 'confirm_password': 'different',
    })

    assert response.status_code == 422
    assert response.get_json()['error_code'] == 'unprocessable'
    assert {'password', 'confirm_password'} <= set(response.get_json()['detail'])


def test_native_reset_handlers_accept_digest_and_legacy_token_storage(client, db_session):
    user = reset_user(db_session)
    raw_token = f'native-reset-{uuid4().hex}'
    user.password_reset_token = password_reset_token_digest(raw_token)
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    pages = AuthPageData()
    reset = PasswordResetConfirmData()
    assert pages.reset_token_active(raw_token) is True
    assert reset.valid_reset_token(raw_token) is True
    assert reset.reset(raw_token, 'native-new-password') is True
    assert user.password_reset_token is None
    assert user.check_password('native-new-password')

    legacy_token = f'legacy-reset-{uuid4().hex}'
    user.password_reset_token = legacy_token
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    assert pages.reset_token_active(legacy_token) is True
    assert reset.valid_reset_token(legacy_token) is True
    assert reset.reset(legacy_token, 'legacy-new-password') is True
    assert user.password_reset_token is None
    assert user.check_password('legacy-new-password')
