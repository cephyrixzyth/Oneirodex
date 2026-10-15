"""Framework-independent context shared by FastAPI route adapters.

The native routers historically received a Flask app for its configuration,
logger, package root, URL helpers, and JSON encoder. This object keeps those
small contracts available without constructing Flask or loading Jinja.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import enum
import json
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from werkzeug.http import http_date


_runtime_config: ContextVar[dict | None] = ContextVar('oneirodex_runtime_config', default=None)


@contextmanager
def runtime_config_scope(config):
    """Expose the active runtime configuration without importing Flask."""
    token = _runtime_config.set(config)
    try:
        yield config
    finally:
        _runtime_config.reset(token)


def get_runtime_config():
    """Return config for the current native scope, without framework lookup."""
    return _runtime_config.get()


class NativeJSONProvider:
    """Implement the JSON behavior used by native routes without Flask."""

    mimetype = 'application/json'

    def __init__(self, config):
        self.config = config

    def default(self, value):
        if isinstance(value, (dt.date, dt.datetime)):
            return http_date(value)
        if isinstance(value, (decimal.Decimal, uuid.UUID)):
            return str(value)
        if isinstance(value, enum.Enum):
            return value.value
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.asdict(value)
        html = getattr(value, '__html__', None)
        if html is not None:
            return str(html())
        raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')

    def dumps(self, value, **kwargs):
        kwargs.setdefault('default', self.default)
        kwargs.setdefault('ensure_ascii', self.config.get('JSON_AS_ASCII', True))
        kwargs.setdefault('sort_keys', self.config.get('JSON_SORT_KEYS', True))
        return json.dumps(value, **kwargs)

    def response(self, value):
        body = (self.dumps(value, separators=(',', ':')) + '\n').encode('utf-8')
        return _JSONResponseData(body)


class _JSONResponseData:
    def __init__(self, body):
        self._body = body
        self.status_code = 200
        self.headers = {'Content-Type': 'application/json'}

    def get_data(self):
        return self._body


class _NativeRule:
    def __init__(self, rule):
        self.rule = rule


class _NativeURLAdapter:
    def __init__(self, script_name='/'):
        self.script_name = script_name.rstrip('/')

    def build(self, endpoint, values=None):
        values = values or {}
        if endpoint != 'static' or 'filename' not in values:
            raise KeyError(f'Unknown native URL endpoint: {endpoint}')
        filename = quote(str(values['filename']).lstrip('/'), safe='/')
        return f'{self.script_name}/static/{filename}' or '/'


class _NativeURLMap:
    _LOGIN_ENDPOINTS = {
        'login.login', 'member.login', 'site.login', 'apis.login',
        'admin.login', 'admin2.login', 'arr.login',
    }

    def bind(self, _server_name, *, script_name='/'):
        return _NativeURLAdapter(script_name)

    def iter_rules(self, endpoint=None):
        if endpoint == 'static':
            return iter((_NativeRule('/static/<path:filename>'),))
        if endpoint in self._LOGIN_ENDPOINTS:
            return iter((_NativeRule('/login'),))
        return iter(())


class NativeRuntimeContext:
    """Small app-like context consumed by FastAPI adapters."""

    def __init__(self, config, *, package_root: str | Path):
        # Mirror the Flask defaults that the migrated auth, response, and URL
        # helpers previously inherited from Flask's Config object.
        defaults = {
            'APPLICATION_ROOT': '/',
            'DEBUG': False,
            'JSON_AS_ASCII': True,
            'JSON_SORT_KEYS': True,
            'MAX_CONTENT_LENGTH': None,
            'MAX_FORM_MEMORY_SIZE': 500_000,
            'MAX_FORM_PARTS': 1_000,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=31),
            'PREFERRED_URL_SCHEME': 'http',
            'SECRET_KEY_FALLBACKS': (),
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_NAME': 'session',
            'SESSION_COOKIE_PATH': None,
            'SESSION_COOKIE_SAMESITE': None,
            'SESSION_COOKIE_SECURE': False,
            'SESSION_REFRESH_EACH_REQUEST': True,
            'SERVER_NAME': None,
            'TESTING': False,
        }
        config.update({key: value for key, value in defaults.items() if key not in config})
        self.config = config
        self.root_path = str(Path(package_root).resolve())
        self.static_folder = str(Path(self.root_path) / 'static')
        self.static_url_path = '/static'
        self.logger = logging.getLogger('oneirodex')
        self.url_map = _NativeURLMap()
        self.json = NativeJSONProvider(config)
        self.login_manager = SimpleNamespace(
            login_view='login.login',
            blueprint_login_views={},
            session_protection=config.get('SESSION_PROTECTION', 'basic'),
        )
        self.native_engine = None

    @contextmanager
    def app_context(self):
        """Provide the small context-manager contract used by legacy workers.

        This is a native SQLAlchemy scope, not a Flask application context. It
        lets transitional worker services keep their lifecycle boundaries
        while the FastAPI runtime owns the engine and per-thread sessions.
        """
        if self.native_engine is None:
            raise RuntimeError('Native SQLAlchemy engine is not configured')
        from oneirodex.runtime_native.db_session import native_engine_session_scope

        with runtime_config_scope(self.config):
            with native_engine_session_scope(self.native_engine):
                yield self


__all__ = ['NativeJSONProvider', 'NativeRuntimeContext', 'get_runtime_config', 'runtime_config_scope']
