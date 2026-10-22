"""Tests for the Flask-compatible setup gate around native ASGI dispatch."""
import asyncio
from contextlib import nullcontext

from fastapi import FastAPI
from flask import Flask

import asgi


def _scope(path, method='GET'):
    return {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': method,
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode('ascii'),
        'query_string': b'',
        'root_path': '',
        'headers': [],
        'server': ('localhost', 80),
        'client': ('127.0.0.1', 1234),
    }


def test_global_setup_gate_covers_native_pages_and_keeps_legacy_exemptions(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.secret_key = 'setup-gate-parity-test-secret'
    for path, endpoint in (
        ('/admin/dashboard', 'admin.dashboard'),
        ('/admin/help', 'admin.help'),
        ('/scan_management', 'admin.scan_management'),
        ('/register', 'login.register'),
        ('/setup/features', 'setup.setup_features'),
        ('/setup/integrations', 'setup.setup_integrations'),
        ('/login', 'login.login'),
        ('/setup', 'setup.setup'),
        ('/setup/smtp', 'setup.setup_smtp'),
        ('/setup/igdb', 'setup.setup_igdb'),
        ('/api/health', 'apis.health'),
    ):
        flask_app.add_url_rule(path, endpoint=endpoint, view_func=lambda: 'legacy')

    runtime = asgi.LazyASGIApp()
    runtime._flask_app = flask_app
    runtime._native_sqlalchemy_engine = object()

    async def initialized():
        return None

    runtime._ensure_flask = initialized
    runtime._ensure_native_database = initialized
    runtime._native_database_scope = lambda _app=None: nullcontext()
    monkeypatch.setattr(
        'oneirodex.utils.setup.should_redirect_to_setup', lambda: True,
    )
    monkeypatch.setattr(
        'oneirodex.utils.setup.get_setup_redirect_url',
        lambda: '/setup/integrations',
    )

    async def check(path, method='GET'):
        messages = []

        async def send(message):
            messages.append(message)

        matched = await runtime._send_legacy_setup_gate_if_required(
            _scope(path, method), send,
        )
        return matched, messages

    for path in (
        '/admin/dashboard', '/admin/help', '/scan_management', '/register',
    ):
        matched, messages = asyncio.run(check(path))
        assert matched is True
        assert messages[0]['status'] == 302
        headers = dict(messages[0]['headers'])
        assert headers[b'location'] == b'/setup/integrations'

    for path in (
        '/login', '/setup', '/setup/smtp', '/setup/igdb', '/setup/integrations',
        '/setup/features', '/api/health', '/static/site.css', '/missing-route',
    ):
        matched, messages = asyncio.run(check(path))
        assert matched is False
        assert messages == []


def test_global_setup_gate_uses_explicit_native_runtime_routes(monkeypatch, tmp_path):
    from oneirodex.runtime_native.runtime_context import NativeRuntimeContext

    runtime = asgi.LazyASGIApp()
    runtime._flask_app = NativeRuntimeContext({}, package_root=tmp_path)
    runtime._native_admin_routes = frozenset({'/admin/dashboard', '/admin/help'})
    runtime._native_read_api_app = FastAPI()
    runtime._native_read_api_app.add_api_route(
        '/admin/api/users', lambda: {'users': []}, methods=['GET'],
    )
    runtime._native_sqlalchemy_engine = object()

    async def initialized():
        return None

    runtime._ensure_flask = initialized
    runtime._ensure_native_database = initialized
    runtime._native_database_scope = lambda _app=None: nullcontext()
    monkeypatch.setattr(
        'oneirodex.utils.setup.should_redirect_to_setup', lambda: True,
    )
    monkeypatch.setattr(
        'oneirodex.utils.setup.get_setup_redirect_url',
        lambda: '/setup/integrations',
    )

    async def check(path, method='GET'):
        messages = []

        async def send(message):
            messages.append(message)

        matched = await runtime._send_legacy_setup_gate_if_required(
            _scope(path, method), send,
        )
        return matched, messages

    for path in (
        '/admin/dashboard', '/admin/help', '/admin/api/users',
        '/scan_management', '/register',
    ):
        matched, messages = asyncio.run(check(path))
        assert matched is True
        assert messages[0]['status'] == 302
        assert dict(messages[0]['headers'])[b'location'] == b'/setup/integrations'

    for path in ('/admin/unknown', '/admin/api/unknown'):
        matched, messages = asyncio.run(check(path))
        assert matched is False
        assert messages == []

    matched, messages = asyncio.run(check('/admin/api/users', method='POST'))
    assert matched is False
    assert messages == []
