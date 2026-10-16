"""JSON browser sign-in shares the classic login security contract."""

from uuid import uuid4

from oneirodex.models import User
from oneirodex.runtime_native.auth_login import AuthLoginData
from oneirodex.utils.accounts import placeholder_email


def make_user(db_session, *, verified=True, state=True):
    suffix = str(uuid4())[:8]
    user = User(
        name=f'member_{suffix}',
        email=f'member_{suffix}@example.com',
        password_hash='placeholder',
        role='user',
        user_id=str(uuid4()),
        is_email_verified=verified,
        state=state,
    )
    user.set_password('correct horse battery')
    db_session.add(user)
    db_session.commit()
    return user


def test_login_creates_existing_session_and_returns_safe_next(client, db_session):
    user = make_user(db_session)

    response = client.post('/api/auth/login?next=%2Flibrary%3Fq%3Dzelda', json={
        'username': user.name,
        'password': 'correct horse battery',
    })

    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['next_url'] == '/library?q=zelda'
    assert response.headers.getlist('Set-Cookie')
    assert client.get('/api/account/summary').status_code == 200


def test_native_login_data_authenticates_without_legacy_auth_module(db_session):
    """The production ASGI login path must not import the Flask-only auth module."""
    user = make_user(db_session)

    authenticated, failure = AuthLoginData().authenticate(
        user.name, 'correct horse battery', '127.0.0.1',
    )

    assert failure is None
    assert authenticated.id == user.id


def test_login_refuses_external_next(client, db_session):
    user = make_user(db_session)

    response = client.post('/api/auth/login?next=https%3A%2F%2Fevil.example', json={
        'username': user.name,
        'password': 'correct horse battery',
    })

    assert response.status_code == 200
    assert response.get_json()['next_url'].startswith('/')
    assert not response.get_json()['next_url'].startswith('//')


def test_login_uses_generic_credentials_error_for_unknown_user(client):
    response = client.post('/api/auth/login', json={
        'username': 'not-a-member',
        'password': 'incorrect password',
    })

    assert response.status_code == 401
    assert response.get_json()['error_code'] == 'unauthorized'
    assert response.get_json()['error'] == 'Invalid username or password. USERNAMES ARE CASE SENSITIVE!'


def test_login_requires_nonempty_credentials(client):
    response = client.post('/api/auth/login', json={'username': 'alice', 'password': ''})

    assert response.status_code == 422
    assert response.get_json()['error_code'] == 'unprocessable'


def test_login_refuses_unverified_real_email(client, db_session):
    user = make_user(db_session, verified=False)

    response = client.post('/api/auth/login', json={
        'username': user.name,
        'password': 'correct horse battery',
    })

    assert response.status_code == 403
    assert response.get_json()['error_code'] == 'forbidden'


def test_login_allows_unverified_placeholder_accounts(client, db_session):
    user = make_user(db_session, verified=False)
    user.email = placeholder_email(user.name)
    db_session.commit()

    response = client.post('/api/auth/login', json={
        'username': user.name,
        'password': 'correct horse battery',
    })

    assert response.status_code == 200
    assert response.get_json()['ok'] is True


def test_login_rate_limit_returns_stable_json_refusal(client, monkeypatch):
    monkeypatch.setattr('oneirodex.routes_login.is_rate_limited', lambda _key: True)

    response = client.post('/api/auth/login', json={
        'username': 'alice',
        'password': 'not checked while limited',
    })

    assert response.status_code == 429
    assert response.get_json()['error_code'] == 'rate_limited'


def test_classic_login_still_uses_shared_policy_and_session(client, db_session):
    user = make_user(db_session)

    response = client.post('/login?next=%2Flibrary', data={
        'username': user.name,
        'password': 'correct horse battery',
    })

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/library')
    assert client.get('/api/account/summary').status_code == 200
