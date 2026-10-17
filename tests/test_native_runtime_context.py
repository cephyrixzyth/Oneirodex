from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from flask import Flask
from sqlalchemy import create_engine, text

from oneirodex.runtime_native.db_session import (
    current_native_engine,
    native_db,
    native_session_scope_key,
)
from oneirodex.runtime_native.runtime_context import (
    NativeRuntimeContext,
    get_runtime_config,
    install_flask_json_response_compat,
)


def test_native_runtime_context_preserves_required_flask_defaults(tmp_path):
    context = NativeRuntimeContext({}, package_root=tmp_path)

    assert context.config['PERMANENT_SESSION_LIFETIME'].total_seconds() == 31 * 24 * 60 * 60
    assert context.config['SESSION_COOKIE_NAME'] == 'session'
    assert context.config['SESSION_COOKIE_HTTPONLY'] is True
    assert context.config['SESSION_REFRESH_EACH_REQUEST'] is True
    assert context.config['APPLICATION_ROOT'] == '/'
    assert context.static_folder == str(Path(tmp_path).resolve() / 'static')
    assert context.static_url_path == '/static'


def test_native_static_url_and_login_route_match_the_compatibility_contract(tmp_path):
    context = NativeRuntimeContext({'APPLICATION_ROOT': '/oneirodex'}, package_root=tmp_path)
    adapter = context.url_map.bind('localhost', script_name='/oneirodex')

    assert adapter.build('static', {'filename': 'library/a b.css'}) == (
        '/oneirodex/static/library/a%20b.css'
    )
    assert next(context.url_map.iter_rules('login.login')).rule == '/login'


def test_native_json_provider_matches_flask_default_json_contract(tmp_path):
    @dataclass
    class Sample:
        value: str

    payload = {
        'date': date(2026, 10, 14),
        'datetime': datetime(2026, 10, 14, 12, tzinfo=timezone.utc),
        'decimal': Decimal('4.20'),
        'uuid': UUID('12345678-1234-5678-1234-567812345678'),
        'sample': Sample('ok'),
    }
    flask_app = Flask('runtime-context-json-compat')
    context = NativeRuntimeContext({}, package_root=tmp_path)

    expected = flask_app.json.response(payload).get_data()
    actual = context.json.response(payload).get_data()

    assert actual == expected


def test_starlette_json_response_matches_flask_trailing_newline():
    from starlette.responses import JSONResponse

    install_flask_json_response_compat()
    install_flask_json_response_compat()
    response = JSONResponse({'ok': True})

    assert response.body == b'{"ok":true}\n'
    assert response.headers['content-length'] == str(len(response.body))


def test_native_app_context_owns_a_scoped_session_without_flask_app_context(tmp_path):
    engine = create_engine('sqlite:///:memory:')
    context = NativeRuntimeContext({}, package_root=tmp_path)
    context.native_engine = engine

    with context.app_context():
        assert current_native_engine() is engine
        assert native_session_scope_key() is not None
        assert get_runtime_config() is context.config
        assert native_db.session.execute(text('select 1')).scalar_one() == 1

    assert current_native_engine() is None
    assert native_session_scope_key() is None
    engine.dispose()


def test_runtime_config_scope_restores_outer_context():
    from oneirodex.runtime_native.runtime_context import runtime_config_scope
    from oneirodex.utils.static_urls import static_asset_url

    outer = {'SECRET_KEY': 'outer', 'APPLICATION_ROOT': '/oneirodex'}
    inner = {'SECRET_KEY': 'inner'}
    with runtime_config_scope(outer):
        assert get_runtime_config() is outer
        with runtime_config_scope(inner):
            assert get_runtime_config() is inner
            assert static_asset_url('library/images/a b.jpg') == (
                '/static/library/images/a%20b.jpg'
            )
        assert get_runtime_config() is outer
        assert static_asset_url('library/icons/app.svg') == '/oneirodex/static/library/icons/app.svg'
