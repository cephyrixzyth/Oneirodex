"""Context-local SQLAlchemy sessions for FastAPI-owned requests.

Flask routes continue to scope sessions to Flask's application context. Native
routes can instead supply the already-configured engine and get an isolated
session without pushing a Flask app/request context.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from sqlalchemy import create_engine


_native_session_key: ContextVar[object | None] = ContextVar(
    'oneirodex_native_session_key', default=None
)
_native_engine: ContextVar[Any | None] = ContextVar(
    'oneirodex_native_engine', default=None
)
_native_session: ContextVar[Any | None] = ContextVar(
    'oneirodex_native_session', default=None
)


def current_native_engine():
    """The engine bound to the active native DB scope, if there is one."""
    return _native_engine.get()


def native_session_scope_key():
    """Return the key for a native request, leaving Flask scope to the host."""
    native_key = _native_session_key.get()
    return ('native', native_key) if native_key is not None else None


class _NativeDatabase:
    """Lazy database facade: native Session in scope, Flask session on legacy calls."""

    @property
    def session(self):
        session = _native_session.get()
        if session is not None:
            return session
        from oneirodex import db as legacy_database

        return legacy_database.session


native_db = _NativeDatabase()


def create_native_engine(config):
    """Create the engine used by the ASGI runtime from plain app settings.

    Keep this boundary independent of Flask-SQLAlchemy's private per-app
    engine registry. Flask retains its own engine for compatibility routes
    during the migration; native requests and workers use this explicit one.
    """
    uri = config.get('SQLALCHEMY_DATABASE_URI')
    if not uri:
        raise RuntimeError('Native database URL is not configured')
    options = config.get('SQLALCHEMY_ENGINE_OPTIONS') or {}
    if not isinstance(options, Mapping):
        raise RuntimeError('Native database engine options are invalid')
    return create_engine(uri, **dict(options))


@contextmanager
def native_session_scope(flask_app, database) -> Iterator[None]:
    """Bind one request-local session to ``flask_app``'s configured engine.

    The Flask-SQLAlchemy extension stores engines per app; reading its internal
    registry avoids ``db.engine`` because that property requires a Flask app
    context. Oneirodex has no named binds today.
    """
    extension = database
    if not hasattr(extension, '_app_engines'):
        # Transitional adapter for existing router factories. New FastAPI
        # lifecycle code will pass an engine directly to
        # ``native_engine_session_scope`` and avoid this Flask lookup.
        from oneirodex import db as extension
    try:
        engine = extension._app_engines[flask_app][None]
    except (AttributeError, KeyError) as exc:
        raise RuntimeError('Native database session is not initialized') from exc

    with native_engine_session_scope(engine, extension):
        yield


@contextmanager
def native_engine_session_scope(engine, database=None) -> Iterator[None]:
    """Bind a request/worker-local session to an explicitly owned engine.

    This is the framework-independent entry point for the native runtime.
    ``database`` currently supplies the shared mapped models/session registry;
    engine ownership can move out of Flask without changing route call sites.
    """
    from sqlalchemy.orm import Session

    session = Session(engine, expire_on_commit=False)
    session_key_token = _native_session_key.set(object())
    engine_token = _native_engine.set(engine)
    session_token = _native_session.set(session)
    try:
        yield
    finally:
        try:
            session.close()
        finally:
            try:
                if database is not None:
                    database.session.remove()
            finally:
                _native_session.reset(session_token)
                _native_engine.reset(engine_token)
                _native_session_key.reset(session_key_token)
