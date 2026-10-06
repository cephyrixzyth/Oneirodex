"""Admin deactivation is serialized across independent database sessions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import scoped_session, sessionmaker

from oneirodex import db
from oneirodex.models import SystemEvents, User
from oneirodex.routes_admin_ext import users as users_routes


def test_legacy_null_state_admin_cannot_be_deactivated(app, db_session):
    suffix = uuid4().hex[:10]
    admin = User(
        name=f'legacy_admin_{suffix}', email=f'legacy_admin_{suffix}@example.com',
        role='admin', state=True, is_email_verified=True, user_id=str(uuid4()),
    )
    admin.set_password('a long test password')
    db_session.add(admin)
    db_session.commit()
    db_session.execute(
        text('UPDATE users SET state = NULL WHERE id = :id'), {'id': admin.id},
    )
    db_session.expire(admin)

    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = admin.get_id()
        session['_fresh'] = True
    response = client.put(f'/admin/api/user/{admin.id}', json={'state': False})

    assert response.status_code == 403
    db_session.refresh(admin)
    assert admin.state is None and admin.is_active


def test_concurrent_admin_deactivation_keeps_one_active(app, db_session, monkeypatch):
    # The normal test fixture binds every request to one rolled-back connection.
    # This case needs independent committed rows and separate connections to
    # exercise PostgreSQL's transaction lock. Clean them in finally.
    original_session = db.session
    independent = scoped_session(
        sessionmaker(bind=db.engine, expire_on_commit=False), scopefunc=get_ident,
    )
    db.session = independent
    ids = []
    try:
        admins = []
        for _ in range(2):
            suffix = uuid4().hex[:10]
            admin = User(
                name=f'concurrent_admin_{suffix}',
                email=f'concurrent_admin_{suffix}@example.com',
                role='admin', state=True, is_email_verified=True,
                user_id=str(uuid4()),
            )
            admin.set_password('a long test password')
            independent.add(admin)
            admins.append(admin)
        independent.commit()
        ids = [admin.id for admin in admins]

        barrier = Barrier(2)
        original_lock = users_routes._lock_admin_user_mutation

        def arrive_together():
            barrier.wait(timeout=15)
            return original_lock()

        monkeypatch.setattr(users_routes, '_lock_admin_user_mutation', arrive_together)

        def deactivate(admin):
            client = app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = admin.get_id()
                session['_fresh'] = True
            return client.put(f'/admin/api/user/{admin.id}', json={'state': False}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(deactivate, admins[0])
            second = pool.submit(deactivate, admins[1])
            statuses = [first.result(timeout=30), second.result(timeout=30)]

        assert sorted(statuses) == [200, 403]
        independent.expire_all()
        active = independent.scalar(select(func.count(User.id)).where(
            User.id.in_(ids), User.role == 'admin', User.state.is_(True),
        ))
        assert active == 1
    finally:
        independent.remove()
        if ids:
            independent.query(SystemEvents).filter(
                SystemEvents.audit_user.in_(ids)
            ).delete(synchronize_session=False)
            independent.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            independent.commit()
        independent.remove()
        db.session = original_session
