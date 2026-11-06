from itsdangerous import URLSafeTimedSerializer

from oneirodex.models import User
from oneirodex.utils.tokens import email_verification_token_digest


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


def test_confirmation_api_accepts_digest_and_clears_it_after_activation(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    user.email_verification_token = email_verification_token_digest(token)
    db_session.commit()

    inspected = client.get(f'/api/auth/confirm/{token}')
    activated = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'mailbox-owner-password',
        'confirm_password': 'mailbox-owner-password',
    })
    db_session.refresh(user)

    assert inspected.status_code == 200 and inspected.get_json()['confirmed'] is False
    assert activated.status_code == 200 and activated.get_json()['confirmed'] is True
    assert user.is_email_verified is True
    assert user.email_verification_token is None


def test_confirmation_api_keeps_legacy_raw_token_rows_working(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    user.email_verification_token = token
    db_session.commit()

    activated = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'mailbox-owner-password',
        'confirm_password': 'mailbox-owner-password',
    })
    db_session.refresh(user)

    assert activated.status_code == 200 and activated.get_json()['confirmed'] is True
    assert user.is_email_verified is True
    assert user.email_verification_token is None


def test_confirmation_api_rejects_token_that_does_not_match_saved_digest(client, app, db_session):
    user = make_unverified_user(db_session)
    token = token_for(app, user.email)
    other_token = token_for(app, f'other-{user.email}')
    user.email_verification_token = email_verification_token_digest(other_token)
    db_session.commit()

    response = client.post(f'/api/auth/confirm/{token}', json={
        'password': 'mailbox-owner-password',
        'confirm_password': 'mailbox-owner-password',
    })
    db_session.refresh(user)

    assert response.status_code == 400
    assert user.is_email_verified is False
    assert user.check_password('correct horse battery')


def test_native_confirmation_resolver_accepts_digest_and_rejects_mismatch(app, monkeypatch):
    from types import SimpleNamespace

    from oneirodex.runtime_native.auth_confirmation import AuthConfirmationData

    user = SimpleNamespace(
        email='native-confirm@example.com', is_email_verified=False,
        email_verification_token=None,
    )
    user.password = None
    user.set_password = lambda password: setattr(user, 'password', password)
    token = token_for(app, user.email)
    user.email_verification_token = email_verification_token_digest(token)

    class Result:
        def scalar_one_or_none(self):
            return user

    class Session:
        def execute(self, _statement):
            return Result()

        def add(self, _row):
            pass

        def commit(self):
            pass

    from oneirodex.runtime_native import db_session as native_db_session
    monkeypatch.setattr(native_db_session, 'native_db', SimpleNamespace(session=Session()))

    data = AuthConfirmationData()
    with app.app_context():
        resolved, outcome = data._resolve_user(token, app.config['SECRET_KEY'])
        assert resolved is user and outcome == 'confirmed'

        user.email_verification_token = token
        resolved, outcome = data._resolve_user(token, app.config['SECRET_KEY'])
        assert resolved is user and outcome == 'confirmed'

        other_token = token_for(app, f'other-{user.email}')
        user.email_verification_token = email_verification_token_digest(other_token)
        resolved, outcome = data._resolve_user(token, app.config['SECRET_KEY'])
        assert resolved is None and outcome == 'invalid'

        user.email_verification_token = email_verification_token_digest(token)
        outcome = data.confirm(token, app.config['SECRET_KEY'], 'mailbox-owner-password')
        assert outcome == 'confirmed'
        assert user.password == 'mailbox-owner-password'
        assert user.is_email_verified is True
        assert user.email_verification_token is None



def test_confirmation_api_refuses_invalid_tokens(client):
    response = client.get('/api/auth/confirm/not-a-valid-token')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'


def test_confirmation_api_refuses_unknown_account(client, app):
    token = token_for(app, 'missing@example.com')
    response = client.get(f'/api/auth/confirm/{token}')
    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'not_found'
