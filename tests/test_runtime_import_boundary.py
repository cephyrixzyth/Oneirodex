"""Importing native contract code must not initialize the Flask runtime."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_requirements_exclude_legacy_framework_packages():
    def package_names(path):
        names = set()
        for raw_line in path.read_text(encoding='utf-8').splitlines():
            line = raw_line.split('#', 1)[0].strip()
            if not line or line.startswith(('-r ', '--')):
                continue
            name = line.split('=', 1)[0].strip().lower().replace('_', '-').replace('.', '-')
            names.add(name)
        return names

    runtime = package_names(ROOT / 'requirements.txt')
    development = package_names(ROOT / 'requirements-dev.txt')
    legacy = {'flask', 'flask-wtf', 'flask-sqlalchemy', 'flask-login', 'jinja2'}
    assert runtime.isdisjoint(legacy)
    assert legacy.issubset(development)
    assert 'itsdangerous' in runtime, (
        'native session compatibility needs an explicit runtime serializer dependency'
    )
    assert 'httpx2' in runtime, (
        'Authlib Starlette OIDC needs its HTTPX2 client in the Flask-free runtime'
    )


def test_hash_identify_imports_without_flask():
    script = r'''
import sys
from importlib.abc import MetaPathFinder

class BlockFlask(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith('flask.'):
            raise ModuleNotFoundError('Flask is intentionally unavailable')
        return None

sys.meta_path.insert(0, BlockFlask())
from oneirodex.utils import hash_identify
from oneirodex.utils import mod_catalog
assert hash_identify._testing() is False
assert hash_identify.base_url() == hash_identify.DEFAULT_BASE_URL
assert mod_catalog.catalog_enabled()
assert set(mod_catalog.source_ids()) == {'thunderstore', 'modrinth', 'gamebanana', 'nexus'}
'''
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_native_runtime_source_does_not_import_flask_or_jinja():
    package = ROOT / 'oneirodex' / 'runtime_native'
    forbidden = []
    for path in package.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name == 'flask' or name.startswith('flask_') or name == 'jinja2' or name.startswith('jinja2.'):
                    forbidden.append(f'{path.relative_to(ROOT)}:{node.lineno}: {name}')

    assert forbidden == []


def test_native_api_contract_and_asgi_imports_do_not_load_flask():
    child_env = os.environ.copy()
    child_env['PYTEST_CURRENT_TEST'] = 'test_native_api_contract_and_asgi_imports_do_not_load_flask'
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys; '
                'import oneirodex.utils.api_contract; '
                'from oneirodex import app_start_time, app_version; '
                'assert app_version and app_start_time is not None; '
                'assert "flask" not in sys.modules and "jinja2" not in sys.modules; '
                'from oneirodex.utils.health_probes import build_liveness; '
                'assert build_liveness()["version"] == app_version; '
                'assert "flask" not in sys.modules and "jinja2" not in sys.modules; '
                'from oneirodex import cache; '
                'cache.set("boundary", {"value": 7}, timeout=60); '
                'assert cache.get("boundary") == {"value": 7}; '
                'cache.delete("boundary"); '
                'import oneirodex.utils.global_settings; '
                'import oneirodex.utils.scan_match_settings; '
                'from oneirodex.runtime_native.app_config import build_runtime_config; '
                'assert build_runtime_config({"TESTING": True})["TESTING"] is True; '
                'assert build_runtime_config()["TESTING"] is True; '
                'from sqlalchemy import create_engine; '
                'from oneirodex.models import GlobalSettings; '
                'from oneirodex.runtime_native.db_session import native_engine_session_scope; '
                'from oneirodex.utils.global_settings import global_settings_row, global_settings_row_or_create; '
                'engine = create_engine("sqlite:///:memory:"); '
                'GlobalSettings.__table__.create(engine); '
                'scope = native_engine_session_scope(engine); '
                'scope.__enter__(); '
                'row = global_settings_row_or_create(); '
                'assert global_settings_row() is row and row.id == 1; '
                'scope.__exit__(None, None, None); '
                'engine.dispose(); '
                'import oneirodex.utils.asset_urls; '
                'import oneirodex.utils.library_paths; '
                'import oneirodex.utils.icon_themes; '
                'import oneirodex.utils.avatar; '
                'from oneirodex.utils.asset_urls import dist_asset_url, theme_asset_url; '
                'from oneirodex.utils.icon_themes import icon_pack_css_url, icon_pack_previews_css_url; '
                'from oneirodex.utils.avatar import avatar_url; '
                'assert dist_asset_url("member-app/member-app.js").startswith("/static/"); '
                'assert theme_asset_url("css/od-tokens.css", theme="default").startswith("/static/"); '
                'assert icon_pack_css_url("outline", static_url_path="/static").startswith("/static/"); '
                'assert icon_pack_previews_css_url(static_url_path="/static") is None or icon_pack_previews_css_url(static_url_path="/static").startswith("/static/"); '
                'assert avatar_url("newstyle/avatars/default.svg", theme="default", static_url=lambda path: "/static/" + path).startswith("/static/"); '
                'import asgi; '
                'import oneirodex.models; '
                'from oneirodex.models.orm import ModelBase; '
                'assert len(ModelBase.metadata.tables) >= 80; '
                'import oneirodex.runtime_native.account_summary; '
                'import oneirodex.runtime_native.admin_ops_reads; '
                'import oneirodex.runtime_native.acquire_status; '
                'import oneirodex.runtime_native.filter_reads; '
                'import oneirodex.runtime_native.admin_features; '
                'import oneirodex.runtime_native.social_reads; '
                'import oneirodex.utils.social_projections; '
                'import oneirodex.runtime_native.setup_state; '
                'import oneirodex.runtime_native.announcements; '
                'import oneirodex.runtime_native.batch_wishlist; '
                'import oneirodex.runtime_native.admin_server_settings; '
                'import oneirodex.runtime_native.scan_unmatched_feedback; '
                'import oneirodex.runtime_native.updates_reads; '
                'import oneirodex.runtime_native.library_reads; '
                'import oneirodex.runtime_native.admin_themes_read; '
                'import oneirodex.runtime_native.game_reads; '
                'import oneirodex.runtime_native.game_delete_mutations; '
                'import oneirodex.runtime_native.vr_reads; '
                'import oneirodex.runtime_native.library_admin_mutations; '
                'import oneirodex.runtime_native.admin_pilot; '
                'import oneirodex.runtime_native.account_password; '
                'import oneirodex.runtime_native.auth_runtime_bootstrap; '
                'import oneirodex.runtime_native.member_shell; '
                'import oneirodex.runtime_native.db_session; '
                'import oneirodex.utils.services.scan_orchestration; '
                'import oneirodex.utils.scan_queue; '
                'import oneirodex.utils.library_deletion; '
                'import oneirodex.utils.services.game_delete; '
                'import oneirodex.runtime_native.scan_job_mutations; '
                'import oneirodex.utils.scanning; '
                'import oneirodex.utils.services.scan_identify; '
                'import oneirodex.utils.services.game_enrich; '
                'import oneirodex.utils.services.image_pipeline; '
                'import oneirodex.utils.local_metadata; '
                'import oneirodex.utils.update_projections; '
                'import oneirodex.utils.rom_language; '
                'import oneirodex.runtime_native.social_reads; '
                'import oneirodex.utils.setup_projections; '
                'import oneirodex.utils.role_catalog; '
                'import oneirodex.utils.server_settings; '
                'import oneirodex.utils.setup; '
                'import oneirodex.utils.game_mods; '
                'import oneirodex.utils.api_tokens; '
                'assert "flask" not in sys.modules; '
                'assert "flask_caching" not in sys.modules; '
                'assert "jinja2" not in sys.modules; '
                'assert "oneirodex.routes_apis.account" not in sys.modules; '
                'assert "oneirodex.routes_apis.acquire" not in sys.modules; '
                'assert "oneirodex.routes_apis.filters" not in sys.modules; '
                'assert "oneirodex.routes_admin_ext.features" not in sys.modules; '
                'assert "oneirodex.routes_apis.social" not in sys.modules; '
                'assert "oneirodex.routes_apis.setup" not in sys.modules; '
                'assert "oneirodex.utils.rbac" not in sys.modules; '
                'assert "oneirodex.routes_admin_ext.settings" not in sys.modules; '
                'assert "oneirodex.routes_apis.scan_unmatched_rows" not in sys.modules; '
                'assert "oneirodex.routes_apis.updates" not in sys.modules; '
                'assert "oneirodex.routes_apis.library" not in sys.modules; '
                'assert "oneirodex.routes_admin_ext.themes" not in sys.modules; '
                'assert "oneirodex.routes_apis.assists" not in sys.modules; '
                'assert "oneirodex.routes_apis.vr" not in sys.modules; '
                'assert "oneirodex.routes_info" not in sys.modules'
            ),
        ],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_asgi_router_startup_does_not_construct_or_import_flask():
    child_env = os.environ.copy()
    child_env['PYTEST_CURRENT_TEST'] = 'test_asgi_router_startup_does_not_construct_or_import_flask'
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import asyncio, sys; '
                'from types import SimpleNamespace; '
                'import oneirodex.runtime_native.admin_pilot as admin_pilot; '
                'user = SimpleNamespace(id=7, name="Admin", role="admin", is_active=True, avatarpath="newstyle/avatars/default.svg", preferences=SimpleNamespace(theme=None, icon_pack="outline"), session_fingerprint=lambda: "fresh"); '
                'admin_pilot._native_auth_backend = lambda _app: (lambda uid: user if uid == 7 else None, lambda _prefix: None, lambda _token: None); '
                'from asgi import LazyASGIApp; '
                'from oneirodex.runtime_native.runtime_context import NativeRuntimeContext; '
                'runtime = LazyASGIApp(); '
                'asyncio.run(runtime._ensure_flask()); '
                'import httpx; '
                'client = httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url="http://localhost"); '
                'response = asyncio.run(client.get("/api/account/summary", follow_redirects=False)); '
                'asyncio.run(client.aclose()); '
                'assert response.status_code == 302; '
                'assert response.headers["location"] == "/login?next=%2Fapi%2Faccount%2Fsummary"; '
                'runtime._runtime_config["SESSION_PROTECTION"] = "none"; '
                'from oneirodex.runtime_native.session_compat import dump_session_cookie; '
                'cookie = dump_session_cookie({"_user_id": "7:fresh", "_fresh": True}, runtime._runtime_config["SECRET_KEY"]); '
                'client = httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url="http://localhost", cookies={"session": cookie}); '
                'response = asyncio.run(client.get("/admin/api/runtime-bootstrap")); '
                'asyncio.run(client.aclose()); '
                'assert response.status_code == 200 and response.json()["user"]["role"] == "admin"; '
                'assert response.json()["csrf_token"]; '
                'assert isinstance(runtime._flask_app, NativeRuntimeContext); '
                'assert runtime._native_read_api_app is not None; '
                'assert not any(name == "flask" or name.startswith("flask.") for name in sys.modules); '
                'assert not any(name == "jinja2" or name.startswith("jinja2.") for name in sys.modules); '
                'runtime._native_sqlalchemy_engine.dispose() if runtime._native_sqlalchemy_engine else None'
            ),
        ],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_native_background_lifecycle_starts_without_flask_or_jinja():
    script = r'''
import os
import sys
from importlib.abc import MetaPathFinder

class BlockFrameworkImports(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith('flask_') or fullname.startswith('flask.'):
            raise ModuleNotFoundError('Flask is intentionally unavailable in this probe')
        if fullname == 'jinja2' or fullname.startswith('jinja2.'):
            raise ModuleNotFoundError('Jinja2 is intentionally unavailable in this probe')
        return None

sys.meta_path.insert(0, BlockFrameworkImports())
from sqlalchemy import create_engine
from oneirodex.runtime_native.runtime_context import NativeRuntimeContext
from oneirodex.runtime_native.runtime_context import get_runtime_config
from oneirodex.utils import scan_scheduler, library_watch, free_games_poller
from oneirodex.utils.discover_ml import job as discover_ml_job
from oneirodex.utils import ownership_poller, store_deals_poller
from oneirodex.utils import email_digest_scheduler, anticheat_poller, save_paths_poller
from oneirodex.utils import free_games, anticheat_compat, save_paths
from oneirodex.utils import ai_assist, challenge_solver, debrid_connectors
from oneirodex.utils import emulator_saves, remote_play, save_crypto, tokens
from oneirodex.utils import custom_emoji, emulator_cheats
from oneirodex.utils import arr_connectors, chat_attachments
from oneirodex.utils.clients import igdb as igdb_client
from oneirodex.utils import chat, chat_spaces, event_visibility, livekit_rtc, cover_selection
from oneirodex.utils import notifications, smtp
from oneirodex.utils import store_sync_jobs, store_connection_status, store_ownership, store_sync_all
from oneirodex.utils import artwork_apply, cover_art_stock, cover_art_studio, static_urls
from oneirodex.utils import game_details_payload, oidc
from oneirodex.utils import discover_hubs, game_more_from, discover_projections, email_digest
from oneirodex.utils import emulator_profiles
from oneirodex.utils import themes, unmatched
from oneirodex.utils import status, ops_summary

app = NativeRuntimeContext({}, package_root='.')
app.config['ENABLE_FREE_GAMES'] = False
app.native_engine = create_engine('sqlite:///:memory:')
from oneirodex.models.orm import ModelBase
ModelBase.metadata.create_all(app.native_engine)
assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert 'oneirodex.routes_discover' not in sys.modules
started = []
for module, name, symbol in (
    (scan_scheduler, 'scan', 'start_scan_scheduler'),
    (library_watch, 'watch', 'start_library_watch'),
    (discover_ml_job, 'discover-ml', 'start_discover_ml_scheduler'),
    (ownership_poller, 'ownership', 'start_ownership_scheduler'),
    (store_deals_poller, 'store-deals', 'start_store_deals_scheduler'),
    (email_digest_scheduler, 'email-digest', 'start_email_digest_scheduler'),
):
    setattr(module, symbol, lambda _app, label=name: started.append(label))
os.environ.pop('PYTEST_CURRENT_TEST', None)
os.environ['ENABLE_ANTICHEAT_COMPAT'] = 'false'
os.environ['ENABLE_SAVE_PATHS'] = 'false'
from oneirodex.background import start_background_workers
start_background_workers(app)
from oneirodex.utils.discover_ml.job import rebuild_all
with app.app_context():
    assert get_runtime_config() is app.config
    app.config['TESTING'] = False
    assert not anticheat_compat._testing()
    assert not save_paths._testing()
    app.config['ENABLE_FREE_GAMES_COVER_LOOKUP'] = False
    assert not free_games._cover_lookup_enabled()
    app.config['TESTING'] = True
    assert anticheat_compat._testing()
    assert save_paths._testing()
    app.config['TESTING'] = False
    app.config['ENABLE_FREE_GAMES_COVER_LOOKUP'] = True
    assert free_games._cover_lookup_enabled()
    assert rebuild_all()['members'] == 0
assert set(started) == {
    'scan', 'watch', 'discover-ml', 'ownership', 'store-deals', 'email-digest',
}
assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert not any(name == 'jinja2' or name.startswith('jinja2.') for name in sys.modules)
app.native_engine.dispose()
'''
    child_env = os.environ.copy()
    child_env.pop('PYTEST_CURRENT_TEST', None)
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_native_db_utility_modules_import_without_flask_or_jinja():
    script = r'''
import ast
import pathlib
import sys
from importlib.abc import MetaPathFinder

class BlockFrameworkImports(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith(('flask.', 'flask_')):
            raise ModuleNotFoundError('Flask is intentionally unavailable')
        if fullname == 'jinja2' or fullname.startswith('jinja2.'):
            raise ModuleNotFoundError('Jinja2 is intentionally unavailable')
        return None

sys.meta_path.insert(0, BlockFrameworkImports())
root = pathlib.Path('oneirodex/utils')
modules = []
for path in root.rglob('*.py'):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    uses_native_db = any(
        isinstance(node, ast.ImportFrom)
        and node.module == 'oneirodex.runtime_native.db_session'
        and any(alias.name == 'native_db' for alias in node.names)
        for node in ast.walk(tree)
    )
    if not uses_native_db:
        continue
    parts = path.with_suffix('').parts
    if parts[-1] == '__init__':
        parts = parts[:-1]
    modules.append('.'.join(parts))
runtime_modules = []
for path in pathlib.Path('oneirodex/runtime_native').rglob('*.py'):
    parts = path.with_suffix('').parts
    if parts[-1] == '__init__':
        parts = parts[:-1]
    runtime_modules.append('.'.join(parts))
failures = []
for name in sorted(set(modules + runtime_modules)):
    try:
        __import__(name)
    except Exception as exc:
        failures.append(f'{name}: {type(exc).__name__}: {exc}')
assert not failures, '\n'.join(failures)
assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert not any(name == 'jinja2' or name.startswith('jinja2.') for name in sys.modules)

assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert not any(name == 'jinja2' or name.startswith('jinja2.') for name in sys.modules)
print(
    f'imported {len(modules)} native DB utility modules and '
    f'{len(runtime_modules)} native runtime modules'
)
'''
    child_env = os.environ.copy()
    child_env.pop('PYTEST_CURRENT_TEST', None)
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert 'native runtime modules' in result.stdout


def test_legacy_compatibility_helpers_import_without_flask_or_jinja():
    script = r'''
import sys
from importlib.abc import MetaPathFinder

class BlockFrameworkImports(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith(('flask.', 'flask_')):
            raise ModuleNotFoundError('Flask is intentionally unavailable')
        if fullname == 'jinja2' or fullname.startswith('jinja2.'):
            raise ModuleNotFoundError('Jinja2 is intentionally unavailable')
        return None

sys.meta_path.insert(0, BlockFrameworkImports())
import oneirodex.utils.arr_hardlink_pipeline
import oneirodex.utils.rbac
import oneirodex.utils.bios_install
assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert not any(name == 'jinja2' or name.startswith('jinja2.') for name in sys.modules)
'''
    child_env = os.environ.copy()
    child_env.pop('PYTEST_CURRENT_TEST', None)
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_asgi_member_and_admin_session_flows_with_frameworks_blocked():
    script = r'''
import asyncio
import sys
from importlib.abc import MetaPathFinder
from types import SimpleNamespace

class BlockFrameworkImports(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith(('flask.', 'flask_')):
            raise ModuleNotFoundError('Flask is intentionally unavailable in this probe')
        if fullname == 'jinja2' or fullname.startswith('jinja2.'):
            raise ModuleNotFoundError('Jinja2 is intentionally unavailable in this probe')
        return None

sys.meta_path.insert(0, BlockFrameworkImports())
from oneirodex.runtime_native import admin_pilot
user = SimpleNamespace(
    id=7, name='Admin', role='admin', is_active=True,
    avatarpath='newstyle/avatars/default.svg',
    preferences=SimpleNamespace(theme=None, icon_pack='outline'),
    session_fingerprint=lambda: 'fresh',
)
admin_pilot._native_auth_backend = lambda _app: (
    lambda uid: user if uid == 7 else None,
    lambda _prefix: None,
    lambda _token: None,
)
from asgi import LazyASGIApp
runtime = LazyASGIApp()
asyncio.run(runtime._ensure_flask())
runtime._runtime_config['SESSION_PROTECTION'] = 'none'
import httpx
from oneirodex.runtime_native.session_compat import dump_session_cookie

async def main():
    transport = httpx.ASGITransport(app=runtime)
    async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
        anonymous = await client.get('/api/account/summary', follow_redirects=False)
        assert anonymous.status_code == 302
        assert anonymous.headers['location'] == '/login?next=%2Fapi%2Faccount%2Fsummary'
        cookie = dump_session_cookie(
            {'_user_id': '7:fresh', '_fresh': True},
            runtime._runtime_config['SECRET_KEY'],
        )
        client.cookies.set('session', cookie)
        admin = await client.get('/admin/api/runtime-bootstrap')
        assert admin.status_code == 200
        assert admin.json()['user']['role'] == 'admin'
        assert admin.json()['csrf_token']

asyncio.run(main())
assert not any(name == 'flask' or name.startswith(('flask.', 'flask_')) for name in sys.modules)
assert not any(name == 'jinja2' or name.startswith('jinja2.') for name in sys.modules)
if runtime._native_sqlalchemy_engine:
    runtime._native_sqlalchemy_engine.dispose()
'''
    child_env = os.environ.copy()
    child_env['PYTEST_CURRENT_TEST'] = 'test_asgi_member_and_admin_session_flows_with_frameworks_blocked'
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_legacy_app_exports_still_resolve_on_demand():
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys; '
                'from oneirodex import create_app, db; '
                'assert callable(create_app); '
                'assert db is not None; '
                'assert "flask" in sys.modules'
            ),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
