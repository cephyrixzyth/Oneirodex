"""JSON password reset preserves token, enumeration, and session behavior."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from oneirodex.models import User


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
    assert user.password_reset_token == sent[0][1]
    assert user.token_creation_time is not None


def test_reset_confirmation_updates_password_clears_token_and_keeps_guest_logged_out(client, db_session):
    user = reset_user(db_session)
    user.password_reset_token = f'reset-{uuid4().hex}'
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    response = client.post(f'/api/auth/password-reset/{user.password_reset_token}', json={
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
    user.password_reset_token = f'reset-{uuid4().hex}'
    user.token_creation_time = datetime.now(timezone.utc)
    db_session.commit()

    response = client.post(f'/api/auth/password-reset/{user.password_reset_token}', json={
        'password': 'short', 'confirm_password': 'different',
    })

    assert response.status_code == 422
    assert response.get_json()['error_code'] == 'unprocessable'
    assert {'password', 'confirm_password'} <= set(response.get_json()['detail'])
