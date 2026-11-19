from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io

from argon2 import PasswordHasher
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from oneirodex.models import PersistentLoginSession, User
from scripts import reset_admin_password as script

NEW_PASSWORD = 'correct horse battery'


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "reset.db"}')
    User.__table__.create(engine)
    PersistentLoginSession.__table__.create(engine)
    yield engine
    engine.dispose()


def _user(session, name, role='admin'):
    user = User(
        name=name, email=f'{name.lower()}@example.invalid', role=role,
        password_hash=PasswordHasher().hash('old-password'), state=True,
        is_email_verified=True, password_reset_token='pending-reset',
    )
    session.add(user)
    session.flush()
    return user


def _login(session, user, *, revoked=False, suffix='a'):
    now = datetime.now(timezone.utc)
    session.add(PersistentLoginSession(
        id=f'{user.id}{suffix}'.ljust(32, '0'), user_id=user.id, secret_hash='0' * 64,
        created_at=now, last_seen_at=now, expires_at=now + timedelta(days=30),
        revoked_at=now if revoked else None,
    ))


def test_reset_stores_argon2_hash_clears_link_and_revokes_only_active_logins(engine):
    with Session(engine) as session:
        admin = _user(session, 'Admin_One')
        other = _user(session, 'member', role='user')
        _login(session, admin, suffix='a')
        _login(session, admin, suffix='b')
        _login(session, admin, suffix='c', revoked=True)
        _login(session, other, suffix='d')
        session.commit()

        revoked = script.reset_password(session, admin, NEW_PASSWORD)

        assert revoked == 2
        assert admin.check_password(NEW_PASSWORD)
        assert not admin.check_password('old-password')
        assert admin.password_reset_token is None
        member_login = session.execute(
            select(PersistentLoginSession).filter_by(user_id=other.id)
        ).scalar_one()
        assert member_login.revoked_at is None


def test_short_password_is_refused_without_changing_anything(engine):
    with Session(engine) as session:
        admin = _user(session, 'Admin_One')
        session.commit()
        before = admin.password_hash
        with pytest.raises(script.ResetRefused, match='at least 8'):
            script.reset_password(session, admin, 'short')
        session.rollback()
        assert session.get(User, admin.id).password_hash == before


def test_choose_admin_rules(engine):
    with Session(engine) as session:
        _user(session, 'Admin_One')
        _user(session, 'member', role='user')
        session.commit()
        assert script.choose_admin(session, None).name == 'Admin_One'
        with pytest.raises(script.ResetRefused, match='case-sensitive'):
            script.choose_admin(session, 'admin_one')
        with pytest.raises(script.ResetRefused, match='not an administrator'):
            script.choose_admin(session, 'member')

        _user(session, 'Admin_Two')
        session.commit()
        with pytest.raises(script.ResetRefused, match='--user'):
            script.choose_admin(session, None)
        assert script.choose_admin(session, 'Admin_Two').name == 'Admin_Two'


def test_main_with_password_stdin_never_prints_the_password(engine, monkeypatch, capsys):
    with Session(engine) as session:
        _user(session, 'Admin_One')
        session.commit()
    monkeypatch.setattr(script, 'resolve_database_url', lambda: engine.url)
    monkeypatch.setattr(script.sys, 'stdin', io.StringIO(NEW_PASSWORD + '\n'))

    assert script.main(['--password-stdin']) == 0

    out = capsys.readouterr()
    assert 'Password updated for Admin_One' in out.out
    assert NEW_PASSWORD not in out.out + out.err
    with Session(engine) as session:
        assert session.execute(select(User).filter_by(name='Admin_One')).scalar_one().check_password(NEW_PASSWORD)


def test_main_lists_admins_and_refuses_without_a_terminal(engine, monkeypatch, capsys):
    with Session(engine) as session:
        _user(session, 'Admin_One')
        _user(session, 'member', role='user')
        session.commit()
    monkeypatch.setattr(script, 'resolve_database_url', lambda: engine.url)

    assert script.main(['--list']) == 0
    assert capsys.readouterr().out.split() == ['Admin_One']

    monkeypatch.setattr(script.sys, 'stdin', io.StringIO(''))
    assert script.main([]) == 2
    assert 'docker exec -it' in capsys.readouterr().err
