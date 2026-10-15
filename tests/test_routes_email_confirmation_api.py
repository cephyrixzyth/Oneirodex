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


def test_confirmation_api_confirms_account_and_is_idempotent(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    first = client.get(f'/api/auth/confirm/{token}')
    second = client.get(f'/api/auth/confirm/{token}')
    db_session.refresh(user)
    assert first.status_code == second.status_code == 200
    assert first.get_json()['confirmed'] is True
    assert first.get_json()['already_confirmed'] is False
    assert second.get_json()['already_confirmed'] is True
    assert user.is_email_verified is True


def test_confirmation_api_refuses_invalid_tokens(client):
    response = client.get('/api/auth/confirm/not-a-valid-token')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'


def test_confirmation_api_refuses_unknown_account(client, app):
    token = token_for(app, 'missing@example.com')
    response = client.get(f'/api/auth/confirm/{token}')
    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'not_found'
