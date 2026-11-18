"""Admin-created accounts with no email address.

`users.email` is NOT NULL and unique, and a lot of code reads it without
checking, so an emailless account gets an unroutable RFC 2606 `.invalid`
placeholder rather than a NULL. These tests pin the two things that matters
about that: the account works, and the placeholder is never presented as an
address anyone could write to.
"""

from tests.fixtures.native_client import served_client
from uuid import uuid4

import pytest

from oneirodex.models import User
from oneirodex.utils.accounts import is_placeholder_email


@pytest.fixture
def admin(db_session):
    suffix = str(uuid4())[:8]
    user = User(
        name=f'admin_{suffix}',
        email=f'admin_{suffix}@example.com',
        password_hash='placeholder',
        role='admin',
        user_id=str(uuid4()),
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10,
    )
    user.set_password('admin password here')
    db_session.add(user)
    db_session.commit()
    return user


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def _create(client, **overrides):
    payload = {
        'username': f'household{str(uuid4())[:6]}',
        'email': '',
        'password': 'a good long password',
        'role': 'user',
        'state': True,
        'is_email_verified': True,
    }
    payload.update(overrides)
    return payload, client.put('/admin/api/user/0', json=payload)


class TestCreateWithoutEmail:
    def test_account_is_created_and_can_sign_in(self, client, db_session, admin):
        login(client, admin)
        payload, response = _create(client)
        assert response.status_code == 200

        created = db_session.execute(
            db_session.query(User).filter_by(name=payload['username']).statement
        ).scalar_one()
        assert created.check_password('a good long password')

    def test_placeholder_address_is_unroutable(self, client, db_session, admin):
        login(client, admin)
        payload, response = _create(client)
        assert response.status_code == 200

        created = db_session.execute(
            db_session.query(User).filter_by(name=payload['username']).statement
        ).scalar_one()
        assert is_placeholder_email(created.email)
        assert created.email.endswith('@no-email.invalid')

    def test_emailless_account_is_never_marked_verified(self, client, db_session, admin):
        login(client, admin)
        # Asked for verified: True on purpose — there is nothing to verify, so
        # the server must override rather than take the caller's word.
        payload, response = _create(client, is_email_verified=True)
        assert response.status_code == 200

        created = db_session.execute(
            db_session.query(User).filter_by(name=payload['username']).statement
        ).scalar_one()
        assert created.is_email_verified is False

    def test_emailless_account_can_actually_sign_in(self, client, app, db_session, admin):
        # `is_email_verified` is False for these accounts, but the login
        # activation gate must not bounce them — there is no email to check.
        login(client, admin)
        payload, response = _create(client)
        assert response.status_code == 200

        fresh = served_client(app)
        result = fresh.post('/login', data={
            'username': payload['username'],
            'password': payload['password'],
        })
        assert result.status_code == 302
        assert '/login' not in result.headers['Location']

    def test_real_unverified_email_is_still_blocked(self, app, db_session, admin):
        # The carve-out is for placeholder addresses only: a real address that
        # has not been confirmed still gets "check your email".
        suffix = str(uuid4())[:8]
        pending = User(
            name=f'pending_{suffix}',
            email=f'pending_{suffix}@example.com',
            role='user',
            user_id=str(uuid4()),
            is_email_verified=False,
        )
        pending.set_password('a good long password')
        db_session.add(pending)
        db_session.commit()

        result = served_client(app).post('/login', data={
            'username': pending.name,
            'password': 'a good long password',
        })
        assert result.status_code == 302
        assert '/login' in result.headers['Location']

    def test_two_emailless_accounts_do_not_collide(self, client, admin):
        login(client, admin)
        first = _create(client)[1]
        second = _create(client)[1]
        assert (first.status_code, second.status_code) == (200, 200)

    def test_roster_shows_no_address_rather_than_the_placeholder(self, client, admin):
        login(client, admin)
        payload, _ = _create(client)

        rows = client.get('/admin/api/users').get_json()['users']
        row = next(entry for entry in rows if entry['name'] == payload['username'])
        assert row['email'] == ''
        assert row['has_email'] is False

    def test_a_real_address_still_reports_as_present(self, client, admin):
        login(client, admin)
        payload, response = _create(client, email=f'real{str(uuid4())[:6]}@example.com')
        assert response.status_code == 200

        rows = client.get('/admin/api/users').get_json()['users']
        row = next(entry for entry in rows if entry['name'] == payload['username'])
        assert row['has_email'] is True
        assert row['email'] == payload['email']

    def test_a_malformed_address_is_still_refused(self, client, admin):
        login(client, admin)
        _payload, response = _create(client, email='not-an-address')
        assert response.status_code == 400
