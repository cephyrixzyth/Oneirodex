"""DB-free coverage for native ASGI dispatch and session compatibility."""
import asyncio
from contextlib import nullcontext
import httpx
from flask import Flask
from starlette.responses import PlainTextResponse
import asgi
from oneirodex import app_version
from oneirodex.runtime_native import (
    admin_pilot,
    is_email_confirmation_page_route,
    is_game_edit_route,
    is_game_images_edit_route,
    is_library_edit_route,
)


def fetch(app, path, method='GET'):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            return await client.request(method, path)
    return asyncio.run(run())


def write_admin_shell(static_root):
    shell_path = static_root / 'dist' / 'admin-pilot' / 'index.html'
    shell_path.parent.mkdir(parents=True, exist_ok=True)
    shell_path.write_text('<!doctype html><head></head><div id="admin-app-root"></div>', encoding='utf-8')


def test_retired_admin_pilot_switch_cannot_restore_flask_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '0')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    app.add_url_rule('/admin/users', view_func=lambda: 'legacy')
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', lambda *a, **k: native)
    assert fetch(asgi.LazyASGIApp(), '/admin/users').text == 'native'


def test_admin_shell_uses_packaged_pilot_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv('ONEIRODEX_NATIVE_ADMIN_PILOT', raising=False)
    shell_path = tmp_path / 'dist' / 'admin-pilot' / 'index.html'
    shell_path.parent.mkdir(parents=True)
    shell_path.write_text('built shell', encoding='utf-8')
    app = Flask(__name__, static_folder=str(tmp_path))
    app.add_url_rule('/admin/users', view_func=lambda: 'legacy')
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    captured = []

    async def native(scope, receive, send):
        await PlainTextResponse('native' if scope['method'] == 'GET' else '')(scope, receive, send)

    def factory(flask_app, **kwargs):
        captured.append(kwargs['shell_path'])
        return native

    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', factory)
    runtime = asgi.LazyASGIApp()
    assert fetch(runtime, '/admin/users').text == 'native'
    assert fetch(runtime, '/admin/users', method='HEAD').status_code == 200
    assert fetch(runtime, '/admin/features').text == 'native'
    assert fetch(runtime, '/admin/features', method='HEAD').status_code == 200
    assert fetch(runtime, '/admin/help').text == 'native'
    assert fetch(runtime, '/admin/smtp_settings').text == 'native'
    assert fetch(runtime, '/admin/igdb_settings').text == 'native'
    assert captured == [shell_path]


def test_legacy_admin_paths_dispatch_to_native_router(monkeypatch):
    app = Flask(__name__)
    runtime = asgi.LazyASGIApp()
    runtime._flask_app = app
    seen = []

    async def native(scope, receive, send):
        seen.append((scope['path'], scope['method']))
        await PlainTextResponse('native redirect route')(scope, receive, send)

    async def legacy(scope, receive, send):
        await PlainTextResponse('legacy')(scope, receive, send)

    async def ready():
        return None

    runtime._native_read_api_app = native
    runtime._app = legacy
    runtime._ensure_flask = ready

    assert fetch(runtime, '/admin/scan_management?active_tab=tools', method='HEAD').status_code == 200
    assert fetch(runtime, '/admin/statistics/data').text == 'native redirect route'
    assert fetch(runtime, '/api/get_company_role?game_igdb_id=1&company_id=2').text == 'native redirect route'
    assert fetch(runtime, '/api/search_igdb_by_id?igdb_id=1').text == 'native redirect route'
    assert seen == [
        ('/admin/scan_management', 'HEAD'),
        ('/admin/statistics/data', 'GET'),
        ('/api/get_company_role', 'GET'),
        ('/api/search_igdb_by_id', 'GET'),
    ]


def test_liveness_is_native_and_does_not_construct_flask(monkeypatch):
    def forbidden_create_app():
        raise AssertionError('liveness must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/pulse')
            head_response = await client.head('/pulse')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.json() == {
        'status': 'ok', 'probe': 'liveness', 'version': app_version,
    }
    assert get_response.headers['content-type'] == 'application/json'
    assert get_response.headers['x-content-type-options'] == 'nosniff'
    assert get_response.headers['content-security-policy']
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_readiness_uses_request_local_db_scope_without_flask_context(monkeypatch, tmp_path):
    from oneirodex.utils import health_probes

    runtime = asgi.LazyASGIApp()
    runtime._runtime_config = {
        'CSP_ENABLED': True,
        'CSP_ENFORCE': True,
        'HSTS_SECONDS': 0,
        'SESSION_COOKIE_SECURE': False,
    }
    runtime._native_sqlalchemy_engine = object()
    runtime._native_database_scope = lambda _app=None: nullcontext()
    monkeypatch.setattr(
        asgi, 'create_app',
        lambda: (_ for _ in ()).throw(AssertionError('readiness must not construct Flask')),
    )
    monkeypatch.setattr(health_probes, 'build_readiness', lambda **_kwargs: ({
        'status': 'not_ready',
        'probe': 'readiness',
        'version': 'test',
        'checks': {
            'database': {'ok': False, 'error': 'OperationalError'},
            'initialization': {'ok': True, 'complete': True, 'testing_bypass': False},
        },
    }, 503))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/awake')
            head_response = await client.head('/awake')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 503
    assert get_response.json()['checks']['database']['error'] == 'OperationalError'
    assert get_response.headers['content-type'] == 'application/json'
    assert get_response.headers['content-security-policy']
    assert head_response.status_code == 503
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_readiness_builder_accepts_framework_free_dependencies():
    from types import SimpleNamespace
    from oneirodex.utils.health_probes import build_readiness

    class Session:
        @staticmethod
        def execute(_statement):
            return 1

    body, status = build_readiness(
        config={'TESTING': False},
        database=SimpleNamespace(session=Session()),
        initialization_check=lambda: True,
    )
    assert status == 200
    assert body['checks']['database'] == {'ok': True, 'error': None}
    assert body['checks']['initialization']['complete'] is True


def test_site_entry_redirects_bypass_wsgi_after_native_setup(monkeypatch):
    from oneirodex.utils import setup

    app = Flask('native-site-entry-test')
    app.config.update(
        SECRET_KEY='site-entry-test-secret',
        SESSION_PROTECTION='none',
        SESSION_COOKIE_SECURE=False,
        CSP_ENABLED=False,
    )
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(setup, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup, 'is_setup_in_progress', lambda: False)
    runtime = asgi.LazyASGIApp()
    runtime._native_database_scope = lambda _app=None: nullcontext()

    async def run():
        await runtime._ensure_flask()
        runtime._app = lambda *_args: (_ for _ in ()).throw(
            AssertionError('site entry fell through to WSGI')
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://localhost',
        ) as client:
            return await client.get('/')

    response = asyncio.run(run())
    assert response.status_code == 302
    assert response.headers['location'] == '/login'


def test_public_static_is_native_and_does_not_construct_flask(monkeypatch):
    def forbidden_create_app():
        raise AssertionError('public static files must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)
    runtime = asgi.LazyASGIApp()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            return await client.get('/static/app-sw.js')

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.content
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_installed_cores_allowlist_is_native_for_get_and_head(monkeypatch):
    from oneirodex.utils import webretro_cores

    def forbidden_create_app():
        raise AssertionError('installed core allowlist must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)
    monkeypatch.setattr(
        webretro_cores,
        'get_effective_installed_cores',
        lambda: frozenset({'nestopia', 'snes9x'}),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/api/emulator/installed-cores.js')
            head_response = await client.head('/api/emulator/installed-cores.js')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.text == 'var OD_INSTALLED_CORES = ["nestopia", "snes9x"];\n'
    assert get_response.headers['content-type'] == 'application/javascript; charset=utf-8'
    assert get_response.headers['cache-control'] == 'private, max-age=300'
    assert get_response.headers['x-content-type-options'] == 'nosniff'
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_install_manifest_uses_request_local_db_scope_without_flask_context(monkeypatch, tmp_path):
    from oneirodex.utils import processors
    runtime = asgi.LazyASGIApp()
    monkeypatch.setattr(
        asgi, 'create_app',
        lambda: (_ for _ in ()).throw(AssertionError('manifest must not construct Flask')),
    )
    async def native_database_ready():
        return None
    runtime._ensure_native_database = native_database_ready
    runtime._native_database_scope = lambda *_args: nullcontext()
    runtime._configured_security_headers = lambda: {
        'Content-Security-Policy': "default-src 'self'",
    }
    monkeypatch.setattr(processors, 'get_global_settings', lambda: {'site_name': 'Household Shelf'})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/manifest.webmanifest')
            head_response = await client.head('/manifest.webmanifest')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.json()['name'] == 'Household Shelf'
    assert get_response.json()['short_name'] == 'Household Sh'
    assert get_response.headers['content-type'] == 'application/manifest+json'
    assert get_response.headers['cache-control'] == 'public, max-age=3600'
    assert get_response.headers['content-security-policy']
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert runtime._flask_app is None


def test_loading_icon_bootstrap_uses_request_local_scope_without_flask_dispatch(monkeypatch, tmp_path):
    from oneirodex.utils import loading_icons
    from oneirodex.runtime_native import db_session

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(CSP_ENABLED=True, CSP_ENFORCE=True, HSTS_SECONDS=0)
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask request dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    expected = {
        'loading_icon_mode': 'lock',
        'loading_icon_id': 'disc',
        'resolved_id': 'disc',
        'catalogue': [{'id': 'disc', 'name': 'Disc'}],
    }
    monkeypatch.setattr(loading_icons, 'member_loading_icon_payload', lambda: expected)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/api/loading-icon')
            head_response = await client.head('/api/loading-icon')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.json() == expected
    assert get_response.headers['content-type'] == 'application/json'
    assert get_response.headers['x-content-type-options'] == 'nosniff'
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_public_setup_state_is_native_and_keeps_no_store_contract(monkeypatch, tmp_path):
    from oneirodex.utils import setup as setup_state
    from oneirodex.runtime_native import db_session

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(CSP_ENABLED=True, CSP_ENFORCE=True, HSTS_SECONDS=0)
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask request dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: True)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 1)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/api/setup/state')
            head_response = await client.head('/api/setup/state')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.json()['step'] == 1
    assert get_response.json()['settings'] == {}
    assert get_response.headers['cache-control'] == 'no-store'
    assert get_response.headers['content-security-policy']
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_public_setup_state_does_not_expose_in_progress_admin_settings(monkeypatch, tmp_path):
    from oneirodex.utils import setup as setup_state
    from oneirodex.runtime_native import db_session

    app = Flask(__name__, static_folder=str(tmp_path))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 2)

    response = fetch(asgi.LazyASGIApp(), '/api/setup/state')
    assert response.status_code == 401
    assert response.json()['error_code'] == 'unauthorized'
    assert response.headers['cache-control'] == 'no-store'


def test_setup_state_keeps_in_progress_settings_on_signed_admin_session(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from oneirodex.runtime_native import db_session
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
    from oneirodex.utils import setup as setup_state

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(SECRET_KEY='setup-native-session-test', SESSION_COOKIE_SECURE=False)
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    actor = SimpleNamespace(
        id=7, user_id='admin-guid', role='admin', state=True, is_active=True,
        session_fingerprint=lambda: 'fresh',
    )
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: actor if user_id == 7 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 2)
    monkeypatch.setattr('oneirodex.utils.setup_projections.state_settings', lambda: {
        'smtp_password_configured': True,
    })
    cookie = dump_session_cookie(
        {'_user_id': '7:fresh', '_fresh': True}, app.config['SECRET_KEY'],
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            client.cookies.set('session', cookie)
            return await client.get('/api/setup/state')

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.json()['step'] == 2
    assert response.json()['settings']['smtp_password_configured'] is True
    assert response.headers['cache-control'] == 'no-store'


def test_native_admin_and_member_read_family_dispatch(monkeypatch, tmp_path):
    from types import SimpleNamespace
    # Import provider code before replacing the shared validator below. If this
    # is the first provider import while the security module is patched, the
    # provider's bound function can outlive pytest's monkeypatch teardown.
    from oneirodex.utils.providers import base as provider_base
    from oneirodex.runtime_native import db_session
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
    from oneirodex.utils import statistics
    from oneirodex.runtime_native import palette_suggest
    from oneirodex.runtime_native import metadata_providers_read
    from oneirodex.runtime_native import licensed_catalog_reads
    from oneirodex.utils import event_logging
    from oneirodex.runtime_native import loading_icon_admin
    from oneirodex.runtime_native import metadata_search_sources
    from oneirodex.runtime_native import metadata_search
    from oneirodex.runtime_native import admin_themes_read
    from oneirodex.runtime_native import admin_discovery_sections
    from oneirodex.runtime_native import admin_whitelist
    from oneirodex.runtime_native import admin_user_create
    from oneirodex.runtime_native import admin_user_mutations
    from oneirodex.runtime_native import admin_art_studio_reads
    from oneirodex.runtime_native import emulator_health
    from oneirodex.runtime_native import hltb_stats
    from oneirodex.runtime_native import hltb_refresh
    from oneirodex.runtime_native import arr_config_read
    from oneirodex.runtime_native import chat_emoji_read
    from oneirodex.runtime_native import arr_indexers_read
    from oneirodex.runtime_native import smtp_settings_read
    from oneirodex.runtime_native import igdb_settings_read
    from oneirodex.runtime_native import reference_sets_read
    from oneirodex.runtime_native import discover_reads
    from oneirodex.utils import module_status

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(
        SECRET_KEY='native-admin-read-dispatch',
        CSP_ENABLED=True,
        CSP_ENFORCE=True,
        HSTS_SECONDS=0,
        ENABLE_ARR_HARDLINK_PIPELINE=True,
    )
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    actor = SimpleNamespace(
        id=9, user_id='admin-9', role='admin', state=True, is_active=True,
        session_fingerprint=lambda: 'fresh',
    )
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: actor if user_id == 9 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    monkeypatch.setattr(statistics, 'get_download_statistics', lambda: {
        'totals': {'games': 3},
        'top_games_table': [],
    })
    monkeypatch.setattr(
        hltb_stats.HltbStatsData,
        'read',
        lambda _self: {
            'total_games': 10,
            'games_with_hltb': 4,
            'games_without_hltb': 6,
            'coverage_percentage': 40.0,
        },
    )
    monkeypatch.setattr(
        hltb_refresh.HltbRefreshData,
        'refresh',
        lambda _self, game_uuid: ('updated', {
            'message': f'HLTB data updated for {game_uuid}',
            'data': {'hltb_id': 123, 'hltb_main_story': 5},
        }),
    )
    monkeypatch.setattr(
        hltb_refresh.HltbRefreshData,
        'bulk_refresh',
        lambda _self, limit: ('complete', {
            'processed': 1, 'successful': 1, 'failed': 0, 'limit_seen': limit,
        }),
    )
    monkeypatch.setattr(
        arr_config_read.ArrConfigData,
        'read',
        lambda _self, **_kwargs: {
            'prowlarr_url': 'https://indexer.example',
            'prowlarr_api_key_set': True,
            'qbittorrent_password_set': True,
        },
    )
    monkeypatch.setattr(
        arr_config_read.ArrConfigData,
        'save',
        lambda _self, payload, **_kwargs: {'saved': True},
    )
    monkeypatch.setattr(module_status, 'arr_module_on', lambda **_kwargs: True)
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'read',
        lambda _self: {
            'indexers': [{'id': 'idx-1', 'name': 'Local', 'api_key_set': True}],
            'presets': [{'id': 'preset-1', 'name': 'Preset'}],
        },
    )
    monkeypatch.setattr(
        smtp_settings_read.SmtpSettingsData,
        'read',
        lambda _self: {'settings': {
            'smtp_server': 'mail.example', 'password_saved': True,
        }},
    )
    monkeypatch.setattr(
        smtp_settings_read.SmtpSettingsData,
        'save',
        lambda _self, payload: {'settings': {
            'smtp_server': payload['smtp_server'],
            'password_saved': bool(payload['smtp_password']),
        }},
    )
    monkeypatch.setattr(smtp_settings_read.SmtpSettingsData, 'test_connection', lambda _self: True)
    monkeypatch.setattr(
        igdb_settings_read.IgdbSettingsData,
        'read',
        lambda _self: {'settings': {
            'igdb_client_id': 'client-id', 'secret_present': True,
        }},
    )
    monkeypatch.setattr(
        igdb_settings_read.IgdbSettingsData,
        'save',
        lambda _self, payload: {'settings': {
            'igdb_client_id': payload['igdb_client_id'],
            'secret_present': bool(payload['igdb_client_secret']),
        }},
    )
    monkeypatch.setattr(
        igdb_settings_read.IgdbSettingsData,
        'test_connection',
        lambda _self: {'settings': {
            'igdb_client_id': 'client-id', 'secret_present': True,
        }},
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'read_one',
        lambda _self, indexer_id: (
            {'indexer': {'id': indexer_id, 'name': 'Local', 'api_key_set': True}}
            if indexer_id == 'idx-1' else None
        ),
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'create',
        lambda _self, payload: {'id': 'idx-new', 'name': payload.get('name', ''), 'api_key_set': True},
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'update',
        lambda _self, indexer_id, payload: {
            'id': indexer_id, 'name': payload.get('name', 'Updated'), 'api_key_set': True,
        },
    )
    monkeypatch.setattr(
        reference_sets_read.ReferenceSetsData,
        'read',
        lambda _self: {
            'sets': [{'id': 3, 'name': 'USA'}],
            'platforms': [{'id': 'NES', 'label': 'Nintendo Entertainment System'}],
            'catalog_platforms': [{'id': 'NES', 'label': 'Nintendo Entertainment System'}],
            'regions': ['USA', 'Europe'], 'sources': ['no-intro'],
            'max_dat_bytes': 33554432,
        },
    )
    monkeypatch.setattr(
        reference_sets_read.ReferenceSetsData,
        'read_sets',
        lambda _self: {'sets': [{'id': 3, 'library_platform': 'NES'}]},
    )
    monkeypatch.setattr(
        reference_sets_read.ReferenceSetsData,
        'completion',
        lambda _self, **kwargs: {'platform': kwargs['platform'], 'matched': 4},
    )
    monkeypatch.setattr(
        reference_sets_read.ReferenceSetsData,
        'rehash',
        lambda _self, platform: {'platform': platform, 'hashed': 2, 'skipped': 1},
    )
    monkeypatch.setattr(
        reference_sets_read.ReferenceSetsData,
        'repair_preview',
        lambda _self, **kwargs: {'candidate_count': 3, 'platform': kwargs['platform']},
    )
    monkeypatch.setattr(
        discover_reads.DiscoverReadsData,
        'save_pins',
        lambda _self, _user, payload: {
            'pins': payload.get('pins', []), 'hidden': payload.get('hidden', []), 'max_pins': 3,
        },
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'delete',
        lambda _self, indexer_id: indexer_id == 'idx-1',
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'bulk_import',
        lambda _self, _payload: [{'id': 'idx-bulk', 'name': 'Bulk', 'api_key_set': True}],
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'enable_presets',
        lambda _self, ids: [{'id': ids[0], 'name': 'Preset', 'api_key_set': False}] if ids else [],
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'module_status',
        lambda _self, **_kwargs: {
            'enabled': False, 'db_enabled': False, 'env_enabled': False,
        },
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'save_module_status',
        lambda _self, enabled, **_kwargs: {
            'status': 'saved', 'enabled': enabled,
            'db_enabled': enabled, 'env_enabled': False,
        },
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'search',
        lambda _self, query, **kwargs: {
            'query': query, 'results': [{'title': 'Example', 'quality': {'score': 10}}],
            'excluded_by_quality': 0, 'warnings': [], 'options': kwargs,
        },
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'download',
        lambda _self, url: {'queued': True, 'url': url},
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'hardlink_preview',
        lambda _self, dest, *, limit, app: {
            'library_dest_dir': dest, 'count': 1, 'proposals': [],
        },
    )
    monkeypatch.setattr(
        arr_indexers_read.ArrIndexersData,
        'hardlink_apply',
        lambda _self, proposals, *, only_ok, app: {'applied_count': len(proposals)},
    )
    from oneirodex.utils import security
    assert provider_base.validate_user_outbound_http_url is security.validate_user_outbound_http_url
    monkeypatch.setattr(security, 'validate_user_outbound_http_url', lambda _url: (True, 'https://safe.example/download'))
    monkeypatch.setattr(
        chat_emoji_read.ChatEmojiData,
        'read',
        lambda _self: {
            'emojis': [{'slug': 'cheer', 'emoji': ':cheer:'}],
            'max_custom': 24,
            'limits': {
                'max_upload_bytes': 1048576,
                'max_edge_px': 256,
                'extensions': ['.png', '.webp'],
            },
        },
    )
    monkeypatch.setattr(
        chat_emoji_read.ChatEmojiData,
        'delete',
        lambda _self, _slug, **_kwargs: True,
    )
    from oneirodex.runtime_native import admin_search
    monkeypatch.setattr(
        admin_search.AdminGameSearchData,
        'search',
        lambda _self, query: [{'uuid': 'g-1', 'name': query, 'full_disk_path': '/games/g-1'}],
    )
    monkeypatch.setattr(
        palette_suggest.PaletteSuggestData,
        'suggest',
        lambda _self, _user, limit: {'recent': [{'uuid': str(limit)}], 'popular': []},
    )
    monkeypatch.setattr(
        metadata_providers_read.MetadataProvidersData,
        'read',
        lambda _self: {'providers': {'steam': False}, 'notes': {}},
    )
    monkeypatch.setattr(
        metadata_providers_read.MetadataProvidersData,
        'save',
        lambda _self, payload: {'providers': payload['providers'], 'notes': {}},
    )
    monkeypatch.setattr(
        licensed_catalog_reads.LicensedCatalogData,
        'report',
        lambda _self, platform, _user: {'platform': platform, 'unique_titles': 2},
    )
    monkeypatch.setattr(
        licensed_catalog_reads.LicensedCatalogData,
        'status',
        lambda _self, platform: {'platform': platform, 'age_seconds': 30},
    )
    monkeypatch.setattr(
        licensed_catalog_reads.LicensedCatalogData,
        'refresh',
        lambda _self, platform: {
            'library_platform': platform, 'unique_titles': 4, 'pages': 1,
        },
    )
    monkeypatch.setattr(event_logging, 'log_system_event', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        loading_icon_admin.LoadingIconAdminData,
        'get',
        lambda _self: {'catalogue': [{'id': 'dpad'}]},
    )
    monkeypatch.setattr(
        metadata_search_sources.MetadataSearchSourcesData,
        'read',
        lambda _self: {'sources': [{'id': 'steam'}]},
    )
    monkeypatch.setattr(
        metadata_search.MetadataSearchData,
        'search',
        lambda _self, source, name, **_kwargs: {
            'source': source, 'results': [{'name': name}], 'ownership_only': False,
        },
    )
    monkeypatch.setattr(
        admin_themes_read.AdminThemesData,
        'payload',
        lambda _self, _app, _user: {
            'themes': [{'folder': 'default', 'name': 'Default'}],
            'default_theme': {'name': 'Default'},
            'active_theme': 'default',
        },
    )
    monkeypatch.setattr(
        admin_whitelist.AdminWhitelistData, 'list',
        lambda _self: {'entries': [{'id': 8, 'email': 'member@example.org', 'is_registered': False}]},
    )
    monkeypatch.setattr(
        admin_whitelist.AdminWhitelistData, 'add',
        lambda _self, body, user: ({'id': 9, 'email': body.email}, None),
    )
    monkeypatch.setattr(
        admin_whitelist.AdminWhitelistData, 'delete',
        lambda _self, whitelist_id, user: ({'message': f'deleted {whitelist_id}'}, None),
    )
    monkeypatch.setattr(
        admin_user_create.AdminUserCreateData, 'create',
        lambda _self, body, user: ({'user': {
            'id': 31, 'name': body.get('username'), 'email': None,
            'has_email': False, 'role': 'user',
        }}, None),
    )
    monkeypatch.setattr(
        admin_user_mutations.AdminUserMutationData, 'update',
        lambda _self, user_id, body, actor_id: ({}, None, False),
    )
    monkeypatch.setattr(
        admin_user_mutations.AdminUserMutationData, 'delete',
        lambda _self, user_id, actor_id: ({}, None),
    )
    monkeypatch.setattr(
        emulator_health.EmulatorHealthData, 'read',
        lambda _self, config: {'installed_cores': ['snes9x'], 'pcdos_browser': False,
                               'core_checks': {'snes9x': True}, 'deferred_cores': []},
    )
    monkeypatch.setattr(
        admin_art_studio_reads.AdminArtStudioReadData, 'stock_catalog',
        lambda _self: [{'id': 'stock-one'}],
    )
    monkeypatch.setattr(
        admin_themes_read.AdminThemesData,
        'upload',
        lambda _self, _app, _user, filename, _content: ({
            'status': 'uploaded', 'theme': {'name': filename},
        }, None),
    )
    monkeypatch.setattr(
        admin_themes_read.AdminThemesData,
        'delete',
        lambda _self, _app, _user, theme_name: ({
            'status': 'deleted', 'theme_name': theme_name,
        }, None),
    )
    monkeypatch.setattr(
        admin_themes_read.AdminThemesData,
        'reset',
        lambda _self, _app, _user: (
            True, 'Default theme reset and 2 preset themes installed. Pick a theme under Preferences.'
        ),
    )
    monkeypatch.setattr(
        admin_discovery_sections.AdminDiscoverySectionsData,
        'state',
        lambda _self: {'sections': [{'id': 1, 'identifier': 'fixture'}], 'libraries': [],
                       'platforms': [], 'genres': [], 'max_games': 60},
    )
    monkeypatch.setattr(
        admin_discovery_sections.AdminDiscoverySectionsData,
        'create',
        lambda _self, body, actor_id: ({'section': {'name': body.name, 'actor': actor_id}}, None),
    )
    session_data = {'_user_id': '9:fresh', '_fresh': True}
    csrf = generate_csrf_token(session_data, app.config['SECRET_KEY'])
    cookie = dump_session_cookie(session_data, app.config['SECRET_KEY'])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            client.cookies.set('session', cookie)
            stats = await client.get('/api/admin/statistics')
            hltb = await client.get('/api/hltb/stats')
            hltb_refresh_response = await client.post(
                '/api/hltb/refresh/game-1', headers={'X-CSRFToken': csrf}
            )
            hltb_bulk_refresh = await client.post(
                '/api/hltb/bulk-refresh', json={'limit': 25},
                headers={'X-CSRFToken': csrf},
            )
            arr_config = await client.get('/api/arr/config')
            arr_config_write = await client.put(
                '/api/arr/config', json={'prowlarr_url': 'https://indexer.example'},
                headers={'X-CSRFToken': csrf},
            )
            arr_indexers = await client.get('/api/arr/indexers')
            arr_indexer = await client.get('/api/arr/indexers/idx-1')
            missing_arr_indexer = await client.get('/api/arr/indexers/missing')
            created_arr_indexer = await client.post(
                '/api/arr/indexers', json={'name': 'Added'},
                headers={'X-CSRFToken': csrf},
            )
            updated_arr_indexer = await client.put(
                '/api/arr/indexers/idx-1', json={'name': 'Changed'},
                headers={'X-CSRFToken': csrf},
            )
            deleted_arr_indexer = await client.delete(
                '/api/arr/indexers/idx-1', headers={'X-CSRFToken': csrf}
            )
            bulk_arr_indexers = await client.post(
                '/api/arr/indexers/bulk',
                json={'indexers': [{'name': 'Bulk'}]},
                headers={'X-CSRFToken': csrf},
            )
            preset_arr_indexers = await client.post(
                '/api/arr/indexers/enable-presets',
                json={'preset_ids': ['preset-1']},
                headers={'X-CSRFToken': csrf},
            )
            arr_module = await client.get('/api/arr/module')
            arr_module_write = await client.put(
                '/api/arr/module', json={'enabled': True},
                headers={'X-CSRFToken': csrf},
            )
            arr_search = await client.get('/api/arr/search?q=Example&limit=7')
            arr_download = await client.post(
                '/api/arr/download', json={'url': 'https://safe.example/download'},
                headers={'X-CSRFToken': csrf},
            )
            hardlink_preview = await client.post(
                '/api/arr/hardlink/preview', json={'library_dest_dir': '/library'},
                headers={'X-CSRFToken': csrf},
            )
            hardlink_apply = await client.post(
                '/api/arr/hardlink/apply', json={'proposals': [{'source': '/a', 'dest': '/b'}]},
                headers={'X-CSRFToken': csrf},
            )
            smtp_settings = await client.get('/api/admin/smtp/settings')
            smtp_settings_write = await client.put(
                '/api/admin/smtp/settings',
                json={
                    'smtp_enabled': False, 'smtp_use_tls': True,
                    'smtp_server': 'mail.example', 'smtp_username': 'mailer',
                    'smtp_password': 'new-secret', 'smtp_default_sender': 'noreply@example.com',
                    'smtp_port': 587,
                },
                headers={'X-CSRFToken': csrf},
            )
            smtp_test = await client.post(
                '/api/admin/smtp/test', headers={'X-CSRFToken': csrf}
            )
            igdb_settings = await client.get('/api/admin/igdb/settings')
            igdb_settings_write = await client.put(
                '/api/admin/igdb/settings',
                json={'igdb_client_id': 'new-client', 'igdb_client_secret': 'new-secret'},
                headers={'X-CSRFToken': csrf},
            )
            igdb_test = await client.post(
                '/api/admin/igdb/test', headers={'X-CSRFToken': csrf}
            )
            reference_sets = await client.get('/api/admin/reference-sets')
            reference_sets_head = await client.head('/api/admin/reference-sets')
            reference_sets_member = await client.get('/api/reference-sets')
            discover_pins_write = await client.put(
                '/api/discover/pins', json={'pins': ['recent'], 'hidden': ['played']},
                headers={'X-CSRFToken': csrf},
            )
            completion = await client.get('/api/set-completion?platform=NES')
            rehash = await client.post(
                '/api/reference-sets/rehash', json={'platform': 'NES'},
                headers={'X-CSRFToken': csrf},
            )
            repair_preview = await client.post(
                '/api/reference-sets/repair-preview',
                json={'library_platform': 'NES', 'region': 'USA'},
                headers={'X-CSRFToken': csrf},
            )
            chat_emoji = await client.get('/api/admin/chat-emoji')
            chat_emoji_delete = await client.delete(
                '/api/admin/chat-emoji/cheer', headers={'X-CSRFToken': csrf}
            )
            games = await client.get('/api/admin/games_search?q=Alpha')
            palette = await client.get('/api/palette/suggest?limit=99')
            metadata = await client.get('/api/admin/integrations/metadata-providers')
            metadata_write = await client.put(
                '/api/admin/integrations/metadata-providers',
                json={'providers': {'steam': False}},
                headers={'X-CSRFToken': csrf},
            )
            catalog = await client.get('/api/licensed-catalog?library_platform=NES')
            catalog_status = await client.get('/api/licensed-catalog/status?platform=NES')
            catalog_refresh = await client.post(
                '/api/licensed-catalog/refresh',
                json={'library_platform': 'NES'},
                headers={'X-CSRFToken': csrf},
            )
            theme_icons = await client.get('/api/admin/themes/loading-icons')
            metadata_sources = await client.get('/api/search_metadata/sources')
            metadata_search_response = await client.get(
                '/api/search_metadata?name=Alpha&source=steam'
            )
            themes = await client.get('/api/admin/themes')
            themes_upload = await client.post(
                '/api/admin/themes', files={'theme_zip': ('custom.zip', b'zip')},
                headers={'X-CSRFToken': csrf},
            )
            themes_delete = await client.delete(
                '/api/admin/themes/custom', headers={'X-CSRFToken': csrf}
            )
            themes_reset = await client.post(
                '/admin/themes/reset', json={}, headers={'X-CSRFToken': csrf}
            )
            themes_form_upload = await client.post(
                '/admin/themes', data={'csrf_token': csrf},
                files={'theme_zip': ('custom.zip', b'zip')},
            )
            themes_form_delete = await client.post(
                '/admin/themes/delete/custom', data={'csrf_token': csrf},
            )
            discovery_sections = await client.get('/admin/api/discovery_sections')
            discovery_section_create = await client.post(
                '/admin/api/discovery_sections', json={'name': 'FastAPI shelf', 'mode': 'manual'},
                headers={'X-CSRFToken': csrf},
            )
            whitelist = await client.get('/admin/api/whitelist')
            whitelist_create = await client.post(
                '/admin/api/whitelist', json={'email': 'native@example.org'},
                headers={'X-CSRFToken': csrf},
            )
            whitelist_delete = await client.delete(
                '/admin/whitelist/9', headers={'X-CSRFToken': csrf},
            )
            user_create = await client.put(
                '/admin/api/user/0', json={'username': 'living-room'},
                headers={'X-CSRFToken': csrf},
            )
            user_update = await client.put(
                '/admin/api/user/42', json={'about': 'child account'},
                headers={'X-CSRFToken': csrf},
            )
            user_delete = await client.delete(
                '/admin/api/user/42', headers={'X-CSRFToken': csrf},
            )
            emulator_core_health = await client.get('/api/emulator/health')
            art_studio_stock = await client.get('/admin/api/art-studio/stock')
            assert whitelist.status_code == 200
            assert whitelist.json()['entries'][0]['email'] == 'member@example.org'
            assert whitelist_create.status_code == 201
            assert whitelist_create.json()['email'] == 'native@example.org'
            assert whitelist_delete.status_code == 200
            assert user_create.status_code == 200
            assert user_update.status_code == 200
            assert user_delete.status_code == 200
            assert emulator_core_health.status_code == 200
            assert emulator_core_health.json()['installed_cores'] == ['snes9x']
            assert art_studio_stock.status_code == 200
            assert art_studio_stock.json()['count'] == 1
            assert user_create.json()['user']['name'] == 'living-room'
        return stats, hltb, hltb_refresh_response, hltb_bulk_refresh, arr_config, arr_config_write, arr_indexers, arr_indexer, missing_arr_indexer, created_arr_indexer, updated_arr_indexer, deleted_arr_indexer, bulk_arr_indexers, preset_arr_indexers, arr_module, arr_module_write, arr_search, arr_download, hardlink_preview, hardlink_apply, smtp_settings, smtp_settings_write, smtp_test, igdb_settings, igdb_settings_write, igdb_test, reference_sets, reference_sets_head, reference_sets_member, discover_pins_write, completion, rehash, repair_preview, chat_emoji, chat_emoji_delete, games, palette, metadata, metadata_write, catalog, catalog_status, catalog_refresh, theme_icons, metadata_sources, metadata_search_response, themes, themes_upload, themes_delete, themes_reset, themes_form_upload, themes_form_delete, discovery_sections, discovery_section_create

    stats, hltb, hltb_refresh_response, hltb_bulk_refresh, arr_config, arr_config_write, arr_indexers, arr_indexer, missing_arr_indexer, created_arr_indexer, updated_arr_indexer, deleted_arr_indexer, bulk_arr_indexers, preset_arr_indexers, arr_module, arr_module_write, arr_search, arr_download, hardlink_preview, hardlink_apply, smtp_settings, smtp_settings_write, smtp_test, igdb_settings, igdb_settings_write, igdb_test, reference_sets, reference_sets_head, reference_sets_member, discover_pins_write, completion, rehash, repair_preview, chat_emoji, chat_emoji_delete, games, palette, metadata, metadata_write, catalog, catalog_status, catalog_refresh, theme_icons, metadata_sources, metadata_search_response, themes, themes_upload, themes_delete, themes_reset, themes_form_upload, themes_form_delete, discovery_sections, discovery_section_create = asyncio.run(run())
    assert stats.status_code == 200
    assert stats.json()['totals'] == {'games': 3}
    assert hltb.status_code == 200
    assert hltb.json()['stats'] == {
        'total_games': 10,
        'games_with_hltb': 4,
        'games_without_hltb': 6,
        'coverage_percentage': 40.0,
    }
    assert hltb_refresh_response.status_code == 200
    assert hltb_refresh_response.json()['data']['hltb_id'] == 123
    assert hltb_bulk_refresh.status_code == 200
    assert hltb_bulk_refresh.json()['limit_seen'] == 25
    assert arr_config.status_code == 200
    assert arr_config.json()['prowlarr_api_key_set'] is True
    assert 'prowlarr_api_key' not in arr_config.json()
    assert 'qbittorrent_password' not in arr_config.json()
    assert arr_config_write.status_code == 200
    assert arr_config_write.json()['status'] == 'saved'
    assert arr_indexers.status_code == 200
    assert arr_indexers.json()['indexers'][0]['name'] == 'Local'
    assert arr_indexers.json()['presets'][0]['id'] == 'preset-1'
    assert arr_indexer.status_code == 200
    assert arr_indexer.json()['indexer']['id'] == 'idx-1'
    assert missing_arr_indexer.status_code == 404
    assert created_arr_indexer.status_code == 201
    assert created_arr_indexer.json()['indexer']['id'] == 'idx-new'
    assert updated_arr_indexer.status_code == 200
    assert updated_arr_indexer.json()['indexer']['name'] == 'Changed'
    assert deleted_arr_indexer.status_code == 200
    assert bulk_arr_indexers.status_code == 201
    assert bulk_arr_indexers.json()['count'] == 1
    assert preset_arr_indexers.status_code == 201
    assert preset_arr_indexers.json()['indexers'][0]['id'] == 'preset-1'
    assert arr_module.status_code == 200
    assert arr_module.json() == {
        'enabled': False, 'db_enabled': False, 'env_enabled': False,
    }
    assert arr_module_write.status_code == 200
    assert arr_module_write.json()['db_enabled'] is True
    assert arr_search.status_code == 200
    assert arr_search.json()['options'] == {'limit': 7, 'include_disallowed': False}
    assert arr_download.status_code == 202
    assert arr_download.json()['queued'] is True
    assert hardlink_preview.status_code == 200
    assert hardlink_preview.json()['count'] == 1
    assert hardlink_apply.status_code == 201
    assert hardlink_apply.json()['applied_count'] == 1
    assert smtp_settings.status_code == 200
    assert smtp_settings.json()['settings']['password_saved'] is True
    assert 'smtp_password' not in smtp_settings.text
    assert smtp_settings_write.status_code == 200
    assert smtp_settings_write.json()['settings']['password_saved'] is True
    assert 'new-secret' not in smtp_settings_write.text
    assert smtp_test.status_code == 200
    assert smtp_test.json()['message'] == 'SMTP connection successful. No email was sent.'
    assert igdb_settings.status_code == 200
    assert igdb_settings.json()['settings']['secret_present'] is True
    assert 'igdb_client_secret' not in igdb_settings.text
    assert igdb_settings_write.status_code == 200
    assert igdb_settings_write.json()['settings']['igdb_client_id'] == 'new-client'
    assert 'new-secret' not in igdb_settings_write.text
    assert igdb_test.status_code == 200
    assert igdb_test.json()['message'] == 'IGDB connection successful.'
    assert reference_sets.status_code == 200
    assert reference_sets.json()['sets'] == [{'id': 3, 'name': 'USA'}]
    assert reference_sets.headers['cache-control'] == 'no-store'
    assert reference_sets_head.status_code == 200
    assert reference_sets_head.content == b''
    assert reference_sets_head.headers['content-length'] == str(len(reference_sets.content))
    assert reference_sets_member.status_code == 200
    assert reference_sets_member.json() == {'sets': [{'id': 3, 'library_platform': 'NES'}]}
    assert discover_pins_write.status_code == 200
    assert discover_pins_write.json()['pins'] == ['recent']
    assert discover_pins_write.json()['hidden'] == ['played']
    assert completion.status_code == 200
    assert completion.json() == {'platform': 'NES', 'matched': 4}
    assert rehash.status_code == 200
    assert rehash.json()['hashed'] == 2
    assert repair_preview.status_code == 200
    assert repair_preview.json()['candidate_count'] == 3
    assert chat_emoji.status_code == 200
    assert chat_emoji.json()['emojis'][0]['slug'] == 'cheer'
    assert chat_emoji.headers['cache-control'] == 'no-store'
    assert chat_emoji_delete.status_code == 200
    assert chat_emoji_delete.json()['message'] == 'Custom emoji deleted.'
    assert games.status_code == 200
    assert games.json()[0]['full_disk_path'] == '/games/g-1'
    assert palette.status_code == 200
    assert palette.json()['recent'][0]['uuid'] == '12'
    assert metadata.status_code == 200
    assert metadata.json()['providers']['steam'] is False
    assert metadata_write.status_code == 200
    assert metadata_write.json()['providers']['steam'] is False
    assert catalog.status_code == 200
    assert catalog.json()['unique_titles'] == 2
    assert catalog_status.status_code == 200
    assert catalog_status.json()['age_seconds'] == 30
    assert catalog_refresh.status_code == 200
    assert catalog_refresh.json()['unique_titles'] == 4
    assert theme_icons.status_code == 200
    assert theme_icons.json()['catalogue'][0]['id'] == 'dpad'
    assert metadata_sources.status_code == 200
    assert metadata_sources.json() == {'sources': [{'id': 'steam'}]}
    assert metadata_search_response.status_code == 200
    assert metadata_search_response.json()['results'] == [{'name': 'Alpha'}]
    assert themes.status_code == 200
    assert themes.json()['themes'][0]['folder'] == 'default'
    assert themes_upload.status_code == 200
    assert themes_upload.json()['theme']['name'] == 'custom.zip'
    assert themes_delete.status_code == 200
    assert themes_delete.json()['theme_name'] == 'custom'
    assert themes_reset.status_code == 200
    assert themes_reset.json()['status'] == 'reset'
    assert themes_form_upload.status_code == 302
    assert themes_form_upload.headers['location'] == '/admin/themes'
    assert themes_form_delete.status_code == 302
    assert themes_form_delete.headers['location'] == '/admin/themes'
    assert discovery_sections.status_code == 200
    assert discovery_sections.json()['sections'][0]['identifier'] == 'fixture'
    assert discovery_section_create.status_code == 201
    assert discovery_section_create.json()['section']['actor'] == 9
    assert stats.headers['content-security-policy']
    assert games.headers['x-content-type-options'] == 'nosniff'


def test_attract_mode_settings_use_native_path_for_anonymous_and_signed_users(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from oneirodex.runtime_native import admin_pilot, attract_mode_reads, db_session
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(
        CSP_ENABLED=True, CSP_ENFORCE=True, HSTS_SECONDS=0,
        SECRET_KEY='attract-native-session-test',
    )
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    user = SimpleNamespace(
        id=7, user_id='user-guid', role='user', state=True, is_active=True,
        session_fingerprint=lambda: 'fresh',
    )
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: user if user_id == 7 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    class Data:
        def __init__(self):
            self.saved = []

        def payload(self, authenticated_user):
            genre = 'Action' if authenticated_user is None else 'Member Choice'
            return {
                'enabled': True,
                'idle_timeout': 75,
                'settings': {'filters': {'genres': [genre]}, 'autoplay': {'enabled': True}},
            }
        def save_override(self, authenticated_user, payload):
            self.saved.append((authenticated_user.id, payload))
    data = Data()
    monkeypatch.setattr(attract_mode_reads, 'AttractModeData', lambda: data)
    session_data = {'_user_id': '7:fresh', '_fresh': True}
    csrf_token = generate_csrf_token(session_data, app.config['SECRET_KEY'])
    signed_cookie = dump_session_cookie(session_data, app.config['SECRET_KEY'])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/api/attract-mode/settings')
            head_response = await client.head('/api/attract-mode/settings')
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
            cookies={'session': signed_cookie},
        ) as client:
            credential_response = await client.get('/api/attract-mode/settings')
            write_response = await client.post(
                '/api/attract-mode/user-override',
                json={'filters': {'genres': ['Member Choice']}},
                headers={'X-CSRFToken': csrf_token},
            )
        return get_response, head_response, credential_response, write_response

    get_response, head_response, credential_response, write_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.json() == {
        'enabled': True,
        'idle_timeout': 75,
        'settings': {'filters': {'genres': ['Action']}, 'autoplay': {'enabled': True}},
    }
    assert credential_response.status_code == 200
    assert credential_response.json()['settings']['filters']['genres'] == ['Member Choice']
    assert 'session=' in credential_response.headers['set-cookie']
    assert write_response.status_code == 200
    assert write_response.json()['ok'] is True
    assert data.saved == [(7, {'filters': {'genres': ['Member Choice']}})]
    assert get_response.headers['x-content-type-options'] == 'nosniff'
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_offline_document_is_native_cache_revalidated_and_member_free(monkeypatch):
    def forbidden_create_app():
        raise AssertionError('the offline document must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/offline')
            head_response = await client.head('/offline')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.headers['cache-control'] == 'no-cache'
    assert get_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert '/static/js/od_offline_retry.js?v=' in get_response.text
    assert 'No route to your library' in get_response.text
    assert 'browse_games' not in get_response.text
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_service_workers_are_native_scoped_and_never_cached(monkeypatch):
    def forbidden_create_app():
        raise AssertionError('service-worker routes must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            root_worker = await client.get('/sw.js')
            vr_worker = await client.get('/vr/sw.js')
            root_head = await client.head('/sw.js')
            root_not_modified = await client.get('/sw.js', headers={
                'If-None-Match': root_worker.headers['etag'],
            })
            root_range = await client.get('/sw.js', headers={'Range': 'bytes=0-9'})
        return root_worker, vr_worker, root_head, root_not_modified, root_range

    root_worker, vr_worker, root_head, root_not_modified, root_range = asyncio.run(run())
    assert root_worker.status_code == vr_worker.status_code == 200
    assert root_worker.headers['service-worker-allowed'] == '/'
    assert vr_worker.headers['service-worker-allowed'] == '/vr'
    assert root_worker.headers['cache-control'] == vr_worker.headers['cache-control'] == 'no-cache'
    assert 'javascript' in root_worker.headers['content-type']
    assert root_worker.headers['content-security-policy']
    assert root_head.content == b''
    assert root_head.headers['content-length'] == str(len(root_worker.content))
    assert root_not_modified.status_code == 304
    assert root_not_modified.content == b''
    assert root_range.status_code == 206
    assert root_range.headers['content-range'] == f'bytes 0-9/{len(root_worker.content)}'
    assert root_range.content == root_worker.content[:10]


def test_service_worker_ignores_library_static_overrides(monkeypatch, tmp_path):
    static_root = tmp_path / 'static'
    static_root.mkdir()
    shipped_worker = static_root / 'app-sw.js'
    shipped_worker.write_text('/* shipped worker */', encoding='utf-8')
    library = tmp_path / 'library'
    override = library / 'static-overrides' / 'app-sw.js'
    override.parent.mkdir(parents=True)
    override.write_text('/* mutable override */', encoding='utf-8')
    monkeypatch.setenv('ONEIRODEX_LIBRARY_DIR', str(library))

    runtime = asgi.LazyASGIApp()
    runtime._static_root = static_root
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            return await client.get('/sw.js')

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.text == '/* shipped worker */'


def test_favicon_is_native_and_keeps_short_cache_policy(monkeypatch, tmp_path):
    def forbidden_create_app():
        raise AssertionError('favicon must not construct Flask')

    monkeypatch.setattr(asgi, 'create_app', forbidden_create_app)
    static_root = tmp_path / 'static'
    icon_path = static_root / 'icons' / 'favicon.ico'
    icon_path.parent.mkdir(parents=True)
    icon_payload = bytes(range(256)) * 8
    icon_path.write_bytes(icon_payload)
    runtime = asgi.LazyASGIApp()
    runtime._static_root = static_root

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            full = await client.get('/favicon.ico')
            head = await client.head('/favicon.ico')
            not_modified_etag = await client.get('/favicon.ico', headers={
                'If-None-Match': full.headers['etag'],
            })
            not_modified_date = await client.get('/favicon.ico', headers={
                'If-Modified-Since': full.headers['last-modified'],
            })
            ranged = await client.get('/favicon.ico', headers={'Range': 'bytes=10-109'})
            unsatisfiable = await client.get('/favicon.ico', headers={
                'Range': f'bytes={len(icon_payload)}-',
            })
        return full, head, not_modified_etag, not_modified_date, ranged, unsatisfiable

    full, head, not_modified_etag, not_modified_date, ranged, unsatisfiable = asyncio.run(run())
    assert full.status_code == 200
    assert full.headers['content-type'] == 'image/vnd.microsoft.icon'
    assert full.headers['cache-control'] == 'public, max-age=3600'
    assert full.content == icon_payload
    assert full.headers['etag']
    assert full.headers['last-modified']
    assert full.headers['accept-ranges'] == 'bytes'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(icon_payload))
    assert not_modified_etag.status_code == not_modified_date.status_code == 304
    assert not_modified_etag.content == not_modified_date.content == b''
    assert ranged.status_code == 206
    assert ranged.headers['content-range'] == f'bytes 10-109/{len(icon_payload)}'
    assert ranged.content == icon_payload[10:110]
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers['content-range'] == f'bytes */{len(icon_payload)}'


def test_theme_font_stylesheet_is_native_and_preserves_css_contract(monkeypatch, tmp_path):
    from oneirodex.runtime_native import admin_pilot, db_session

    font_root = tmp_path / 'fonts'
    font_root.mkdir()
    (font_root / 'Cabinet-Test.woff2').write_bytes(b'wOF2test-font')
    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(SECRET_KEY='theme-font-native-test', FONT_PATH=str(font_root))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda _user_id: None, lambda _prefix: None, lambda _token: None,
    ))
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/api/theme/fonts.css?font=cabinet-test')
            head_response = await client.head('/api/theme/fonts.css?font=cabinet-test')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.headers['content-type'] == 'text/css; charset=utf-8'
    assert get_response.headers['cache-control'] == 'public, max-age=60'
    assert "font-family: 'Cabinet-Test'" in get_response.text
    assert '/static/library/fonts/Cabinet-Test.woff2' in get_response.text
    assert '--od-font-family: "Cabinet-Test", sans-serif' in get_response.text
    assert get_response.headers['content-security-policy']
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_credentialed_theme_font_request_uses_native_user_preference(monkeypatch, tmp_path):
    from oneirodex.runtime_native import admin_pilot, db_session

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(SECRET_KEY='theme-font-session-test', TESTING=True)
    user = type('User', (), {'preferences': type('Prefs', (), {'font': 'vt323'})()})()
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: user if user_id == 7 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    session_cookie = app.session_interface.get_signing_serializer(app).dumps({
        '_user_id': '7', '_fresh': True,
    })

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
            cookies={'session': session_cookie},
        ) as client:
            response = await client.get('/api/theme/fonts.css')
            override = await client.get('/api/theme/fonts.css?font=orbitron')
            return response, override

    response, override = asyncio.run(run())
    assert response.status_code == 200
    assert '"VT323", "Courier New", monospace' in response.text
    assert '"Orbitron", "Arial Black", sans-serif' in override.text


def test_member_auth_runtime_bootstrap_is_native_with_flask_session_compat(monkeypatch, tmp_path):
    from flask_wtf.csrf import validate_csrf
    from oneirodex.runtime_native import auth_runtime_bootstrap

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(
        SECRET_KEY='native-auth-bootstrap-test',
        TESTING=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask request dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(auth_runtime_bootstrap, 'member_auth_runtime_fields', lambda _app, **_kwargs: {
        'oidc_enabled': True,
        'oidc_display_name': 'Household SSO',
    })

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
        ) as client:
            response = await client.get('/api/auth/runtime-bootstrap')
            head = await client.head('/api/auth/runtime-bootstrap')
            return response, head

    response, head = asyncio.run(run())
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['runtime'] == 'fastapi-session-compat'
    assert response.json()['oidc_display_name'] == 'Household SSO'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['vary'] == 'Cookie'
    assert response.headers['content-security-policy']
    assert head.status_code == 200 and head.content == b''
    cookie = response.cookies.get('session')
    assert cookie
    with app.test_request_context(headers={'Cookie': f'session={cookie}'}):
        validate_csrf(response.json()['csrf_token'])


def test_member_auth_runtime_bootstrap_preserves_existing_signed_session(monkeypatch, tmp_path):
    from oneirodex.runtime_native import auth_runtime_bootstrap
    from oneirodex.runtime_native.session_compat import load_session_cookie

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config.update(SECRET_KEY='native-auth-session-test', TESTING=True)
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(auth_runtime_bootstrap, 'member_auth_runtime_fields', lambda _app, **_kwargs: {
        'oidc_enabled': False,
        'oidc_display_name': 'Sign in with SSO',
    })
    prior_cookie = app.session_interface.get_signing_serializer(app).dumps({
        '_user_id': '19:existing-fingerprint',
        '_fresh': True,
        'theme': 'crt',
    })

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
            cookies={'session': prior_cookie},
        ) as client:
            return await client.get('/api/auth/runtime-bootstrap')

    response = asyncio.run(run())
    cookie = response.cookies.get('session')
    assert response.status_code == 200
    assert cookie
    session = load_session_cookie(
        cookie,
        app.secret_key,
        max_age=int(app.permanent_session_lifetime.total_seconds()),
    )
    assert session['_user_id'] == '19:existing-fingerprint'
    assert session['_fresh'] is True
    assert session['theme'] == 'crt'
    assert session['csrf_token']


def test_credential_free_confirmation_page_is_native_and_exactly_matched(monkeypatch, tmp_path):
    static_root = tmp_path / 'static'
    shell_path = static_root / 'dist' / 'member-auth' / 'auth.html'
    shell_path.parent.mkdir(parents=True)
    shell_path.write_text(
        '<html><head></head><body><div id="member-auth-root"></div></body></html>',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        asgi,
        'create_app',
        lambda: (_ for _ in ()).throw(AssertionError('confirmation shell constructed Flask')),
    )
    runtime = asgi.LazyASGIApp()
    runtime._static_root = static_root
    assert is_email_confirmation_page_route('/confirm/opaque-token')
    for invalid in ('/confirm', '/confirm/a/b', '/confirm/token/'):
        assert not is_email_confirmation_page_route(invalid)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/confirm/opaque-token')
            head_response = await client.head('/confirm/opaque-token')
        return get_response, head_response

    get_response, head_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert get_response.headers['cache-control'] == 'no-store'
    assert get_response.headers['vary'] == 'Cookie'
    assert 'id="member-auth-root"' in get_response.text
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_credential_free_auth_pages_are_native_and_use_validated_shell(monkeypatch, tmp_path):
    static_root = tmp_path / 'static'
    shell_path = static_root / 'dist' / 'member-auth' / 'auth.html'
    shell_path.parent.mkdir(parents=True)
    shell_path.write_text(
        '<html><head></head><body><div id="member-auth-root"></div></body></html>',
        encoding='utf-8',
    )
    monkeypatch.setattr(
        asgi,
        'create_app',
        lambda: (_ for _ in ()).throw(AssertionError('anonymous login must not construct Flask')),
    )
    runtime = asgi.LazyASGIApp()
    runtime._static_root = static_root

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as client:
            get_response = await client.get('/login')
            head_response = await client.head('/login')
            reset_response = await client.get('/reset_password_request')
        return get_response, head_response, reset_response

    get_response, head_response, reset_response = asyncio.run(run())
    assert get_response.status_code == 200
    assert get_response.headers['cache-control'] == 'no-store'
    assert get_response.headers['vary'] == 'Cookie'
    assert 'id="member-auth-root"' in get_response.text
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert reset_response.status_code == 200
    assert reset_response.text == get_response.text


def test_login_with_existing_session_uses_native_auth_page(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from oneirodex.runtime_native import db_session
    from oneirodex.runtime_native.session_compat import dump_session_cookie

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config['SECRET_KEY'] = 'native-auth-page-session-test'
    shell = tmp_path / 'dist' / 'member-auth' / 'auth.html'
    shell.parent.mkdir(parents=True)
    shell.write_text('<html><body><div id="member-auth-root"></div></body></html>')
    actor = SimpleNamespace(
        id=42, role='user', state=True, is_active=True,
        session_fingerprint=lambda: 'fresh',
    )
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: actor if user_id == 42 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    cookie = dump_session_cookie(
        {'_user_id': '42:fresh', '_fresh': True}, app.config['SECRET_KEY'],
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
            cookies={'session': cookie},
        ) as client:
            return await client.get('/login')

    response = asyncio.run(run())
    assert response.status_code == 302
    assert response.headers['location'] == '/discover'


def test_confirmation_page_with_session_keeps_queued_flash(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from oneirodex.runtime_native import db_session
    from oneirodex.runtime_native.session_compat import dump_session_cookie

    app = Flask(__name__, static_folder=str(tmp_path))
    app.config['SECRET_KEY'] = 'native-confirm-page-session-test'
    shell = tmp_path / 'dist' / 'member-auth' / 'auth.html'
    shell.parent.mkdir(parents=True)
    shell.write_text('<html><body><div id="member-auth-root"></div></body></html>')
    actor = SimpleNamespace(
        id=43, role='user', state=True, is_active=True,
        session_fingerprint=lambda: 'fresh',
    )
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    monkeypatch.setattr(db_session, 'native_session_scope', lambda _app, _db: nullcontext())
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: actor if user_id == 43 else None,
        lambda _prefix: None,
        lambda _token: None,
    ))
    cookie = dump_session_cookie(
        {
            '_user_id': '43:fresh', '_fresh': True,
            '_flashes': [('success', 'Email address confirmed.')],
        },
        app.config['SECRET_KEY'],
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi.LazyASGIApp()),
            base_url='http://localhost',
            cookies={'session': cookie},
        ) as client:
            return await client.get('/confirm/opaque-token')

    response = asyncio.run(run())
    assert response.status_code == 200
    assert 'Email address confirmed.' in response.text


def test_admin_routes_are_bounded_and_retired_switch_cannot_restore_wsgi(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '0')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    app.add_url_rule('/other', view_func=lambda: 'existing')
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    captured = []
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    def factory(flask_app, **kwargs):
        captured.append(kwargs['shell_path'])
        return native
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', factory)
    runtime = asgi.LazyASGIApp()
    for path in ['/admin/users','/admin/announcements','/admin/invites','/admin/manage_invites','/admin/extensions','/admin/api/runtime-bootstrap']:
        assert fetch(runtime, path).text == 'native'
    assert fetch(runtime, '/other').status_code == 404
    assert captured == [tmp_path / 'dist' / 'admin-pilot' / 'index.html']


def test_native_shell_switch_preserves_invite_form_post_dispatch(monkeypatch):
    runtime = asgi.LazyASGIApp()
    runtime._flask_app = Flask(__name__)
    runtime._flask_app.config['WTF_CSRF_ENABLED'] = False
    seen = []

    async def native(scope, receive, send):
        seen.append((scope['path'], scope['method']))
        await PlainTextResponse('native invite compatibility route')(scope, receive, send)

    async def legacy(scope, receive, send):
        await PlainTextResponse('legacy')(scope, receive, send)

    async def ready():
        return None

    runtime._native_read_api_app = native
    runtime._app = legacy
    runtime._ensure_flask = ready

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url='http://localhost') as client:
            response = await client.post('/admin/manage_invites', data={'invites_number': '1'})
            assert response.status_code == 200
            assert response.text == 'native invite compatibility route'
    asyncio.run(run())
    assert seen == [('/admin/manage_invites', 'POST')]


def test_newsletter_numeric_dispatch_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '1')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', lambda *a, **k: native)
    runtime = asgi.LazyASGIApp()
    for path in ['/admin/newsletter', '/admin/newsletter/7', '/admin/newsletter/0007', '/admin/newsletter/0']:
        assert fetch(runtime, path).text == 'native', path
    for path in ['/admin/newsletterish/7', '/admin/newsletter/no', '/admin/newsletter/-1', '/admin/newsletter/7/extra', '/admin/newsletter/7/', '/admin/newsletter/\uFF17']:
        assert fetch(runtime, path).status_code == 404


def test_library_editor_dynamic_dispatch_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '1')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', lambda *a, **k: native)
    runtime = asgi.LazyASGIApp()
    assert is_library_edit_route('/admin/library/edit/123e4567-e89b-12d3-a456-426614174000')
    assert fetch(runtime, '/admin/library/edit/123e4567-e89b-12d3-a456-426614174000').text == 'native'
    for path in ['/admin/library/edit', '/admin/library/edit/x/y', '/admin/library/edit/123/']:
        assert not is_library_edit_route(path)
        assert fetch(runtime, path).status_code == 404


def test_game_editor_dynamic_dispatch_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '1')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', lambda *a, **k: native)
    runtime = asgi.LazyASGIApp()
    game_uuid = '123e4567-e89b-12d3-a456-426614174000'
    assert is_game_edit_route(f'/game_edit/{game_uuid}')
    assert fetch(runtime, f'/game_edit/{game_uuid}').text == 'native'
    for path in ['/game_edit', '/game_edit/x/y', '/game_edit/123/']:
        assert not is_game_edit_route(path)
        assert fetch(runtime, path).status_code == 404


def test_game_images_editor_dynamic_dispatch_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv('ONEIRODEX_NATIVE_ADMIN_PILOT', '1')
    app = Flask(__name__, static_folder=str(tmp_path))
    write_admin_shell(tmp_path)
    monkeypatch.setattr(asgi, 'create_app', lambda: app)
    async def native(scope, receive, send):
        await PlainTextResponse('native')(scope, receive, send)
    monkeypatch.setattr(admin_pilot, 'create_admin_pilot', lambda *a, **k: native)
    runtime = asgi.LazyASGIApp()
    game_uuid = '123e4567-e89b-12d3-a456-426614174000'
    assert is_game_images_edit_route(f'/edit_game_images/{game_uuid}')
    assert fetch(runtime, f'/edit_game_images/{game_uuid}').text == 'native'
    for path in ['/edit_game_images', '/edit_game_images/x/y', '/edit_game_images/123/']:
        assert not is_game_images_edit_route(path)
        assert fetch(runtime, path).status_code == 404
