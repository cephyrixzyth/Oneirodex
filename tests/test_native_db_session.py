"""FastAPI can own a request-local SQLAlchemy session without Flask context."""
from __future__ import annotations

import pytest
from flask import Flask, has_app_context
from sqlalchemy import text

from oneirodex import db
from oneirodex.runtime_native.db_session import (
    create_native_engine,
    native_engine_session_scope,
    native_session_scope,
)
from oneirodex.models.orm import ModelBase


class NativeSessionProbe(ModelBase):
    __tablename__ = 'native_session_probe'

    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.Integer, nullable=False)


@pytest.fixture
def database_app():
    app = Flask('native-session-test')
    app.config.update(
        SECRET_KEY='native-session-test-only',
        SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    NativeSessionProbe.__table__.create(db._app_engines[app][None], checkfirst=True)
    yield app
    with app.app_context():
        db.session.remove()
    db._app_engines[app][None].dispose()


def test_native_session_uses_configured_engine_without_flask_context(database_app):
    engine = db._app_engines[database_app][None]
    with native_session_scope(database_app, db):
        assert not has_app_context()
        session = db.session()
        assert session.get_bind() is engine
        assert session.execute(text('select 41 + 1')).scalar_one() == 42
        session.add(NativeSessionProbe(id=1, value=42))
        session.commit()
        assert session.get(NativeSessionProbe, 1).value == 42
    assert not has_app_context()

    with native_session_scope(database_app, db):
        assert db.session.get(NativeSessionProbe, 1).value == 42


def test_legacy_session_still_scopes_to_flask_app_context(database_app):
    engine = db._app_engines[database_app][None]
    with database_app.app_context():
        assert has_app_context()
        assert db.session().get_bind() is engine
        assert db.session.execute(text('select 6 * 7')).scalar_one() == 42


def test_native_session_accepts_an_explicit_engine_without_flask_app_lookup(database_app):
    engine = db._app_engines[database_app][None]
    with native_engine_session_scope(engine, db):
        assert not has_app_context()
        assert db.session().get_bind() is engine
        assert db.session.execute(text('select 9 * 5')).scalar_one() == 45


def test_native_engine_is_created_from_plain_runtime_config():
    engine = create_native_engine({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    try:
        from oneirodex.models.orm import db as model_registry
        from oneirodex.runtime_native.db_session import native_db

        with native_engine_session_scope(engine):
            assert native_db.session.execute(text('select 13 * 3')).scalar_one() == 39
            assert model_registry.session is native_db.session
    finally:
        engine.dispose()


def test_model_query_uses_the_explicit_native_session_without_extension_cleanup(database_app):
    from oneirodex.runtime_native.db_session import native_db

    engine = db._app_engines[database_app][None]
    with native_engine_session_scope(engine):
        assert not has_app_context()
        query = NativeSessionProbe.query
        assert query.session is native_db.session
        assert query.session.get_bind() is engine


def test_scan_worker_session_cleanup_accepts_direct_native_session():
    from oneirodex.runtime_native.db_session import native_db
    from oneirodex.utils.services.scan_orchestration import _remove_scan_session

    engine = create_native_engine({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    try:
        with native_engine_session_scope(engine, db):
            assert native_db.session.execute(text('select 8')).scalar_one() == 8
            _remove_scan_session()
            assert native_db.session.execute(text('select 9')).scalar_one() == 9
    finally:
        engine.dispose()


def test_member_oidc_bootstrap_fields_do_not_push_flask_context(database_app, monkeypatch):
    from types import SimpleNamespace

    from oneirodex.runtime_native.auth_runtime_bootstrap import member_auth_runtime_fields
    from oneirodex.utils import global_settings, oidc

    from oneirodex.runtime_native.db_session import native_db

    engine = db._app_engines[database_app][None]
    monkeypatch.setattr(
        global_settings,
        'global_settings_row',
        lambda: native_db.session.execute(text('select 42')).scalar_one(),
    )
    monkeypatch.setattr(
        oidc,
        'build_oidc_config',
        lambda _row: SimpleNamespace(display_name='Household SSO'),
    )
    monkeypatch.setattr(
        database_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('member bootstrap pushed Flask context')),
    )

    fields = member_auth_runtime_fields(
        database_app,
        database_scope=lambda _app: native_engine_session_scope(engine, db),
    )

    assert fields == {'oidc_enabled': True, 'oidc_display_name': 'Household SSO'}
    assert not has_app_context()

