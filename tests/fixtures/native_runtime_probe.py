"""Owned data-only engine for framework-blocked native request probes."""
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


def persisted_runtime_probe(user):
    from asgi import LazyASGIApp
    from oneirodex.models import GlobalSettings, PersistentLoginSession, User
    from oneirodex.runtime_native.db_session import native_db, native_engine_session_scope
    from oneirodex.utils.persistent_sessions import issue_login_identity

    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    try:
        User.__table__.create(engine)
        GlobalSettings.__table__.create(engine)
        PersistentLoginSession.__table__.create(engine)
        runtime = LazyASGIApp()
        runtime._native_sqlalchemy_engine = engine
        with native_engine_session_scope(engine):
            row = User(id=user.id, name=user.name, role=user.role, state=True, email='native-probe@example.test', password_hash='synthetic-probe-hash')
            native_db.session.add(row)
            native_db.session.add(GlobalSettings(id=1, setup_completed=True, setup_in_progress=False))
            native_db.session.commit()
            user.session_fingerprint = row.session_fingerprint
            identity = issue_login_identity(user)
        return runtime, identity
    except BaseException:
        engine.dispose()
        raise
