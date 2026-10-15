"""DB-free auth parity checks for ASGI download endpoints."""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext
from types import SimpleNamespace

from flask import Flask

import oneirodex
from asgi import LazyASGIApp
from oneirodex.runtime_native import admin_pilot, db_session
from oneirodex.runtime_native.session_compat import dump_session_cookie


def _configure_native_auth(monkeypatch, app, user, token=None):
    class Session:
        @staticmethod
        def get(_model, user_id):
            return user if int(user_id) == user.id else None

        @staticmethod
        def execute(_statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: token))

        @staticmethod
        def commit():
            return None

    monkeypatch.setattr(oneirodex, 'db', SimpleNamespace(session=Session()))
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: user if int(user_id) == user.id else None,
        lambda _prefix: token,
        lambda _token: None,
    ))
    app._flask_app = Flask(__name__)
    app._flask_app.config.update(
        SECRET_KEY='download-auth-test', TESTING=False,
        SESSION_COOKIE_NAME='session',
        PERMANENT_SESSION_LIFETIME=31_536_000,
    )
    async def ready():
        return None
    app._ensure_flask = ready


def _user(user_id=17, role='user'):
    return SimpleNamespace(
        id=user_id,
        role=role,
        state=True,
        is_active=True,
        session_fingerprint=lambda: 'current-fingerprint',
    )


def test_signed_download_session_uses_framework_free_cookie_and_active_user_checks(monkeypatch):
    user = _user()
    app = LazyASGIApp()
    _configure_native_auth(monkeypatch, app, user)
    cookie = dump_session_cookie(
        {'_user_id': '17:current-fingerprint'}, app._flask_app.config['SECRET_KEY'],
    )
    scope = {'headers': [(b'cookie', f'session={cookie}'.encode('ascii'))]}

    assert asyncio.run(app._get_user_from_session(scope)) == 17

    stale = dump_session_cookie(
        {'_user_id': '17:old-fingerprint'}, app._flask_app.config['SECRET_KEY'],
    )
    assert asyncio.run(app._get_user_from_session({
        'headers': [(b'cookie', f'session={stale}'.encode('ascii'))],
    })) is None


def test_download_bearer_scope_and_child_role_use_native_auth(monkeypatch):
    raw = 'gt_1234_secret'
    token = SimpleNamespace(
        user_id=17,
        token_hash=hashlib.sha256(b'secret').hexdigest(),
        revoked_at=None,
        expires_at=None,
        is_expired=lambda _now=None: False,
        has_scope=lambda requested: requested == 'write:download',
    )
    member = _user()
    app = LazyASGIApp()
    _configure_native_auth(monkeypatch, app, member, token)
    scope = {'headers': [(b'authorization', f'Bearer {raw}'.encode('ascii'))]}

    assert asyncio.run(app._get_user_id(scope)) == 17

    child = _user(role='child')
    _configure_native_auth(monkeypatch, app, child, token)
    assert asyncio.run(app._get_user_id(scope)) is None


def test_bearer_credential_takes_precedence_over_a_valid_session(monkeypatch):
    user = _user()
    raw = 'gt_1234_secret'
    token = SimpleNamespace(
        user_id=17,
        token_hash=hashlib.sha256(b'secret').hexdigest(),
        revoked_at=None,
        expires_at=None,
        is_expired=lambda _now=None: False,
        has_scope=lambda _requested: False,
    )
    app = LazyASGIApp()
    _configure_native_auth(monkeypatch, app, user, token)
    cookie = dump_session_cookie(
        {'_user_id': '17:current-fingerprint'}, app._flask_app.config['SECRET_KEY'],
    )
    scope = {'headers': [
        (b'authorization', f'Bearer {raw}'.encode('ascii')),
        (b'cookie', f'session={cookie}'.encode('ascii')),
    ]}

    assert asyncio.run(app._get_user_id(scope)) is None
