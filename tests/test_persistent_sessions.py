from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from oneirodex.models import PersistentLoginSession, User
from oneirodex.utils.persistent_sessions import (
    MAX_SESSION_AGE,
    MAX_SESSION_IDLE,
    active_login_sessions,
    issue_login_identity,
    revoke_all_login_sessions,
    revoke_login_session,
    session_id_from_identity,
    validate_login_identity,
)


def _identity_parts(identity):
    uid, fingerprint, session_id, secret = identity.split(':')
    return int(uid), fingerprint, session_id, secret


def test_persistent_session_hashes_secret_and_enforces_age_idle_and_revocation(app, db_session):
    user = User(name='session-owner', email='session-owner@example.test', role='user', state=True)
    user.set_password('correct horse battery staple')
    db_session.add(user)
    db_session.commit()
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)

    with app.app_context():
        identity = issue_login_identity(user, now=now)
        user_id, fingerprint, session_id, secret = _identity_parts(identity)
        row = db_session.get(PersistentLoginSession, session_id)

        assert user_id == user.id
        assert fingerprint == user.session_fingerprint()
        assert row.secret_hash == hashlib.sha256(secret.encode('ascii')).hexdigest()
        assert secret not in row.secret_hash
        assert session_id_from_identity(identity) == session_id
        assert validate_login_identity(identity, user, now=now, touch=False)
        assert not validate_login_identity(identity, user, now=now + MAX_SESSION_AGE, touch=False)
        assert not validate_login_identity(
            identity, user, now=now + MAX_SESSION_IDLE, touch=False
        )
        assert not validate_login_identity(
            identity.replace(secret, 'wrong-secret'), user, now=now, touch=False
        )

        assert revoke_login_session(session_id, user_id=user.id, now=now + timedelta(minutes=1))
        db_session.commit()
        assert not validate_login_identity(identity, user, now=now + timedelta(minutes=1), touch=False)


def test_all_device_revocation_is_user_scoped(app, db_session):
    owner = User(name='session-owner-2', email='session-owner-2@example.test', role='user', state=True)
    other = User(name='session-other', email='session-other@example.test', role='user', state=True)
    owner.set_password('correct horse battery staple')
    other.set_password('another correct horse battery staple')
    db_session.add_all([owner, other])
    db_session.commit()
    # Session listing uses the current clock; keep these user-scope fixtures active.
    now = datetime.now(timezone.utc)

    with app.app_context():
        own = [issue_login_identity(owner, now=now) for _ in range(2)]
        foreign = issue_login_identity(other, now=now)
        assert len(active_login_sessions(owner.id)) == 2
        assert revoke_all_login_sessions(owner.id, now=now + timedelta(minutes=1)) == 2
        db_session.commit()

        assert all(
            not validate_login_identity(token, owner, now=now + timedelta(minutes=1), touch=False)
            for token in own
        )
        assert validate_login_identity(foreign, other, now=now + timedelta(minutes=1), touch=False)
        assert db_session.execute(
            select(PersistentLoginSession).where(PersistentLoginSession.user_id == owner.id)
        ).scalars().all()


def test_password_change_and_account_disable_revoke_sessions(app, db_session):
    user = User(name='session-revoke-owner', email='session-revoke-owner@example.test', role='user', state=True)
    user.set_password('first password')
    db_session.add(user)
    db_session.commit()
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)

    with app.app_context():
        before_password_change = issue_login_identity(user, now=now)
        user.set_password('second password')
        db_session.commit()
        assert not validate_login_identity(
            before_password_change, user, now=now + timedelta(minutes=1), touch=False
        )

        before_disable = issue_login_identity(user, now=now + timedelta(minutes=2))
        user.state = False
        db_session.commit()
        assert not validate_login_identity(
            before_disable, user, now=now + timedelta(minutes=3), touch=False
        )

        user.state = True
        db_session.commit()
        assert not validate_login_identity(
            before_disable, user, now=now + timedelta(minutes=4), touch=False
        )


def test_classic_logout_revokes_identity_loaded_only_from_remember_cookie(app, db_session):
    from oneirodex.runtime_native.auth_resolver import encode_remember_cookie

    app.config["TESTING"] = False
    user = User(name='remember-logout-owner', email='remember-logout@example.test', role='user', state=True)
    user.set_password('correct horse battery staple')
    db_session.add(user)
    db_session.commit()

    with app.app_context():
        identity = issue_login_identity(user)
        session_id = session_id_from_identity(identity)
        remember_cookie = encode_remember_cookie(identity, app.config['SECRET_KEY'])

    client = app.test_client()
    client.set_cookie(app.config.get('REMEMBER_COOKIE_NAME', 'remember_token'), remember_cookie)
    response = client.post('/logout')

    assert response.status_code == 302
    row = db_session.get(PersistentLoginSession, session_id)
    assert row is not None
    assert row.revoked_at is not None
