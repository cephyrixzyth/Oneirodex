from itsdangerous import URLSafeTimedSerializer

from oneirodex.models import User


def make_unverified_user(db_session):
    user = User(
        name='confirm_member', email='confirm_member@example.com',
        password_hash='placeholder', role='user', user_id='confirm-member',
        is_email_verified=False,
    )
    user.set_password('correct horse battery')
    db_session.add(user)
    db_session.commit()
    return user


def token_for(app, email):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    with app.app_context():
        token = serializer.dumps(email, salt='email-confirm')
    return token


def test_confirmation_api_get_is_read_only_and_post_sets_mailbox_owner_password(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    first = client.get(f'/api/auth/confirm/{token}')
    second = client.get(f'/api/auth/confirm/{token}')
    db_session.refresh(user)
    assert first.status_code == second.status_code == 200
    assert first.get_json()['confirmed'] is False
    assert second.get_json()['confirmed'] is False
    assert user.is_email_verified is False

    activated = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'mailbox-owner-password',
        'confirm_password': 'mailbox-owner-password',
    })
    second_activation = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'attacker-cannot-change-it',
        'confirm_password': 'attacker-cannot-change-it',
    })
    db_session.refresh(user)
    assert activated.status_code == second_activation.status_code == 200
    assert activated.get_json()['confirmed'] is True
    assert activated.get_json()['already_confirmed'] is False
    assert second_activation.get_json()['already_confirmed'] is True
    assert user.is_email_verified is True
    assert user.check_password('mailbox-owner-password')
    assert not user.check_password('attacker-cannot-change-it')


def test_confirmation_post_rejects_password_mismatch(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    response = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'mailbox-owner-password',
        'confirm_password': 'different-password',
    })
    db_session.refresh(user)
    assert response.status_code == 422
    assert user.is_email_verified is False


def test_confirmation_api_refuses_invalid_tokens(client):
    response = client.get('/api/auth/confirm/not-a-valid-token')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'


def test_confirmation_api_refuses_unknown_account(client, app):
    token = token_for(app, 'missing@example.com')
    response = client.get(f'/api/auth/confirm/{token}')
    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'not_found'
