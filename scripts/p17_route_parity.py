"""Read-only census of legacy Flask methods missing from native FastAPI/ASGI.

This is a migration aid, not acceptance evidence: matching paths and methods do
not prove auth, CSRF, payload, or side-effect parity. It registers route
blueprints in memory and initializes the same native router set used by ASGI,
without creating an app context, opening a database, or starting workers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import re
from collections import defaultdict
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask


def _blueprints():
    from oneirodex.routes_site import site_bp
    from oneirodex.routes_member import member_bp
    from oneirodex.routes_admin_ext import admin2_bp
    from oneirodex.routes_library import library_bp
    from oneirodex.routes_setup import setup_bp
    from oneirodex.routes_settings import settings_bp
    from oneirodex.routes_login import login_bp
    from oneirodex.routes_discover import discover_bp
    from oneirodex.routes_downloads_ext import download_bp
    from oneirodex.routes_games_ext import games_bp
    from oneirodex.routes_smtp import smtp_bp
    from oneirodex.routes_info import info_bp
    from oneirodex.routes_apis import apis_bp
    from oneirodex.routes_arr import arr_bp

    return (
        site_bp, member_bp, admin2_bp, library_bp, setup_bp, settings_bp,
        login_bp, discover_bp, download_bp, games_bp, smtp_bp, info_bp,
        apis_bp, arr_bp,
    )


NATIVE_PARAM = re.compile(r"\{(?P<name>[^}:]+)(?::(?P<converter>[^}]+))?\}")
LEGACY_PARAM = re.compile(r"<(?:(?P<converter>[^:<>]+):)?(?P<name>[^<>]+)>")


def _normalize(path: str) -> str:
    path = LEGACY_PARAM.sub(lambda match: '{' + match.group('name') + '}', path)
    path = NATIVE_PARAM.sub(lambda match: '{' + match.group('name') + '}', path)
    return path.rstrip('/') or '/'


def _is_api_path(path: str) -> bool:
    return path.startswith('/api/') or path.startswith('/admin/api/')


def _legacy_operations(app, *, include_all=False):
    operations = {}
    converter_types = {'int': 'integer', 'float': 'number', 'uuid': 'uuid'}
    for rule in app.url_map.iter_rules():
        if not include_all and not _is_api_path(rule.rule):
            continue
        path = _normalize(rule.rule)
        types = {
            match.group('name'): converter_types.get(
                (match.group('converter') or 'string').lower(),
                (match.group('converter') or 'string').lower(),
            )
            for match in LEGACY_PARAM.finditer(rule.rule)
        }
        for method in (rule.methods or ()) - {'OPTIONS', 'HEAD'}:
            operations[(method, path)] = types
    return operations


def _native_operations(app, *, include_all=False):
    import asgi
    from oneirodex.runtime_native import admin_pilot

    original_create_app = asgi.create_app
    original_auth_backend = admin_pilot._native_auth_backend
    asgi.create_app = lambda: app
    admin_pilot._native_auth_backend = lambda _app: (
        lambda _user_id: None, lambda _prefix: None, lambda _token: None,
    )
    try:
        lazy = asgi.LazyASGIApp()
        asyncio.run(lazy._ensure_flask())
        routes = {}

        def collect(router_routes, prefix=''):
            for route in router_routes:
                included = getattr(route, 'original_router', None)
                if included is not None:
                    nested_prefix = getattr(included, 'prefix', '') or ''
                    collect(included.routes, prefix + nested_prefix)
                    continue
                path = getattr(route, 'path', None)
                if not path:
                    continue
                full_path = path if not prefix or path.startswith(prefix) else prefix + path
                if not include_all and not _is_api_path(full_path):
                    continue
                if include_all and full_path == '/{member_path:path}':
                    # The member app uses a catch-all ASGI route, but the outer
                    # dispatcher sends only member_shell_route() paths to it.
                    continue
                parameter_types = {}
                for parameter in getattr(getattr(route, 'dependant', None), 'path_params', ()):
                    annotation = getattr(parameter, 'type_', None)
                    annotation_name = getattr(annotation, '__name__', '')
                    if annotation_name == 'int':
                        parameter_types[parameter.name] = 'integer'
                    elif annotation_name == 'float':
                        parameter_types[parameter.name] = 'number'
                    elif annotation_name == 'UUID':
                        parameter_types[parameter.name] = 'uuid'
                    else:
                        parameter_types[parameter.name] = 'string'
                for method in getattr(route, 'methods', ()) or ():
                    routes[(method.upper(), _normalize(full_path))] = parameter_types

        route_apps = [lazy._native_read_api_app]
        if include_all:
            route_apps.extend((lazy._native_member_shell_app, lazy._native_admin_pilot))
        for route_app in route_apps:
            if route_app is not None:
                collect(route_app.routes)
        if include_all:
            from oneirodex.runtime_native.member_shell import STATIC_MEMBER_TITLES

            for path in STATIC_MEMBER_TITLES:
                routes[('GET', _normalize(path))] = {}
            routes.update({
                ('GET', '/discover/{identifier}'): {'identifier': 'string'},
                ('GET', '/discover/zone/{slug}'): {'slug': 'string'},
                ('GET', '/discover/hub/genre/{genre}'): {'genre': 'path'},
                ('GET', '/collections/{collection_uuid}'): {'collection_uuid': 'string'},
                ('GET', '/members/{user_id}'): {'user_id': 'integer'},
                ('GET', '/game_details/{game_uuid}'): {'game_uuid': 'string'},
            })
    finally:
        asgi.create_app = original_create_app
        admin_pilot._native_auth_backend = original_auth_backend
    return routes


def _custom_asgi_operations(*, include_all=False):
    """Known handlers that intentionally sit outside FastAPI routing."""
    routes = {
        ('GET', '/api/activity/stream'): {},
        ('GET', '/api/auth/runtime-bootstrap'): {},
        ('GET', '/api/downloadrom/{guid}'): {'guid': 'string'},
        ('GET', '/api/emulator/installed-cores.js'): {},
        ('GET', '/api/events/stream'): {},
    }
    if include_all:
        routes.update({
            ('GET', '/awake'): {},
            ('GET', '/offline'): {},
            ('GET', '/pulse'): {},
            ('GET', '/favicon.ico'): {},
            ('GET', '/sw.js'): {},
            ('GET', '/vr/sw.js'): {},
            ('GET', '/static/{filename}'): {'filename': 'path'},
            ('GET', '/download_zip/{download_id}'): {'download_id': 'string'},
            ('GET', '/manifest.webmanifest'): {},
        })
    return routes


def _path_covers(native_path, native_types, legacy_path, legacy_types):
    native_parts = native_path.strip('/').split('/')
    legacy_parts = legacy_path.strip('/').split('/')
    if len(native_parts) != len(legacy_parts):
        return False
    for native_part, legacy_part in zip(native_parts, legacy_parts):
        native_match = NATIVE_PARAM.fullmatch(native_part)
        legacy_match = NATIVE_PARAM.fullmatch(legacy_part)
        if legacy_match:
            if not native_match:
                return False
            if native_types.get(native_match.group('name')) == 'path':
                return True
            legacy_type = legacy_types.get(legacy_match.group('name'), 'string')
            native_type = native_types.get(native_match.group('name'), 'string')
            # A string path parameter accepts every single-segment Flask
            # converter domain. Narrow FastAPI types only cover equivalent or
            # narrower legacy domains.
            if native_type == 'string':
                continue
            if native_type != legacy_type:
                return False
        elif native_match:
            native_type = native_types.get(native_match.group('name'), 'string')
            if native_type == 'string':
                continue
            if native_type == 'integer' and legacy_part.isdigit():
                continue
            if native_type == 'number':
                try:
                    float(legacy_part)
                    continue
                except ValueError:
                    return False
            if native_type == 'uuid':
                try:
                    UUID(legacy_part)
                    continue
                except ValueError:
                    return False
            return False
        elif native_part != legacy_part:
            return False
    return True


def build_report(*, include_all=False):
    # Native admin/member pilot routes are enabled from shipped static shell
    # artifacts under the app's real static root. A scratch Flask app defaults
    # to a nonexistent ./static directory, silently omitting those routes from
    # the all-route census even when the actual package contains the bundle.
    flask_app = Flask(
        'p17-route-parity-census',
        static_folder=str(ROOT / 'oneirodex' / 'static'),
    )
    flask_app.config.update(
        SECRET_KEY='route-census-only', CSP_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )
    for blueprint in _blueprints():
        flask_app.register_blueprint(blueprint)
    legacy = _legacy_operations(flask_app, include_all=include_all)
    native = _native_operations(flask_app, include_all=include_all)
    custom = _custom_asgi_operations(include_all=include_all)
    missing_fastapi = []
    for operation, legacy_types in legacy.items():
        method, legacy_path = operation
        if not any(
            native_method == method and _path_covers(
                native_path, native_types, legacy_path, legacy_types,
            )
            for (native_method, native_path), native_types in native.items()
        ):
            missing_fastapi.append(operation)
    custom_covered = []
    unmatched = []
    for operation in missing_fastapi:
        method, legacy_path = operation
        legacy_types = legacy[operation]
        if any(
            custom_method == method and _path_covers(
                custom_path, custom_types, legacy_path, legacy_types,
            )
            for (custom_method, custom_path), custom_types in custom.items()
        ):
            custom_covered.append(operation)
        else:
            unmatched.append(operation)
    unmatched.sort()
    by_path = defaultdict(list)
    for method, path in unmatched:
        by_path[path].append(method)
    return {
        'scope': (
            'all legacy Flask methods vs mounted FastAPI routes and known ASGI handlers'
            if include_all else
            'legacy /api and /admin/api methods vs FastAPI routes and custom ASGI handlers'
        ),
        'warning': 'Path/method overlap is not route behavior, auth, CSRF, or side-effect parity.',
        'legacy_method_paths': len(legacy),
        'native_method_paths': len(native),
        'fastapi_covered_method_paths': len(legacy) - len(missing_fastapi),
        'custom_asgi_covered_method_paths': len(custom_covered),
        'unmatched_legacy_method_paths': len(unmatched),
        'custom_asgi_routes': sorted(f'{method} {path}' for method, path in custom),
        'unmatched_by_path': [
            {'path': path, 'methods': sorted(methods)}
            for path, methods in sorted(by_path.items())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    parser.add_argument(
        '--all-routes', action='store_true',
        help='include non-API routes and mounted member/admin shell apps',
    )
    args = parser.parse_args()
    report = build_report(include_all=args.all_routes)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(
        f"Legacy {report['legacy_method_paths']}; native {report['native_method_paths']}; "
        f"FastAPI-covered {report['fastapi_covered_method_paths']}; "
        f"custom-ASGI-covered {report['custom_asgi_covered_method_paths']}; "
        f"unmatched {report['unmatched_legacy_method_paths']}"
    )
    for item in report['unmatched_by_path']:
        print(','.join(item['methods']), item['path'])


if __name__ == '__main__':
    main()
