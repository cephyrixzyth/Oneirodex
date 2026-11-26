"""ASGI runtime for Oneirodex.

FastAPI owns normal application route dispatch. Normal startup builds the
framework-independent runtime configuration and native SQLAlchemy engine;
Flask app injection remains available for compatibility tests and adapters.
The WSGI fallback has been retired after the legacy method/path inventory
reached full native coverage.
"""

from __future__ import annotations

from oneirodex.runtime_native import (
    is_email_confirmation_page_route,
    is_game_edit_route,
    is_game_image_refresh_route,
    is_game_images_edit_route,
    is_library_edit_route,
    is_local_game_image_route,
    is_single_image_upload_route,
    is_numeric_admin_detail,
)

import asyncio
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from importlib import import_module

from werkzeug.exceptions import RequestedRangeNotSatisfiable
from werkzeug.utils import secure_filename, send_file as werkzeug_send_file

from sqlalchemy import select
from starlette.routing import Match
from oneirodex.runtime_native.companion_cors import native_companion_cors


def create_app(config_object=None):
    """Lazily expose the legacy app factory for compatibility startup/tests."""
    from oneirodex import create_app as legacy_create_app

    return legacy_create_app(config_object)


_DEFAULT_CREATE_APP = create_app


class _LazyDatabaseExport:
    """Resolve Flask-SQLAlchemy only when a compatibility handler needs it."""

    def __getattr__(self, name):
        from oneirodex import db as legacy_db

        return getattr(legacy_db, name)


db = _LazyDatabaseExport()


def _lazy_callable(module_name, attribute):
    """Create a compatibility callable without importing Flask-owned helpers."""
    def call(*args, **kwargs):
        helper = getattr(import_module(module_name), attribute)
        return helper(*args, **kwargs)

    call.__name__ = attribute
    return call


async_generate_zipstream_response = _lazy_callable(
    'oneirodex.async_streaming', 'async_generate_zipstream_response'
)
get_content_type_for_file = _lazy_callable(
    'oneirodex.async_streaming', 'get_content_type_for_file'
)
forbidden_scopes_for_role = _lazy_callable(
    'oneirodex.utils.api_tokens', 'forbidden_scopes_for_role'
)
log_system_event = _lazy_callable('oneirodex.utils.event_logging', 'log_system_event')
user_can_access_game = _lazy_callable(
    'oneirodex.utils.library_acl', 'user_can_access_game'
)
library_platform_key = _lazy_callable('oneirodex.utils.play_url', 'library_platform_key')
bundle_playable_rom_zip = _lazy_callable(
    'oneirodex.utils.rom_archive', 'bundle_playable_rom_zip'
)
resolve_playable_rom_path = _lazy_callable(
    'oneirodex.utils.rom_archive', 'resolve_playable_rom_path'
)

# Archive expansion is disk-heavy and runs once per Uvicorn worker. Keep one
# conversion active per worker; requests that need extraction fail quickly
# instead of accumulating temporary outputs or blocking the ASGI event loop.
_ROM_EXTRACTION_LIMITER = threading.BoundedSemaphore(1)
get_allowed_base_directories = _lazy_callable(
    'oneirodex.utils.security', 'get_allowed_base_directories'
)
is_safe_path = _lazy_callable('oneirodex.utils.security', 'is_safe_path')
open_plain_file_within = _lazy_callable(
    'oneirodex.utils.security', 'open_plain_file_within'
)
baseline_static_headers = _lazy_callable(
    'oneirodex.utils.security_headers', 'baseline_static_headers'
)
library_dir = _lazy_callable('oneirodex.utils.library_paths', 'library_dir')
resolve_served_static = _lazy_callable(
    'oneirodex.utils.static_files', 'resolve_served_static'
)
resolve_static_path = _lazy_callable(
    'oneirodex.utils.static_files', 'resolve_static_path'
)
static_access = _lazy_callable('oneirodex.utils.static_files', 'static_access')
theme_document_security_headers = _lazy_callable(
    'oneirodex.utils.static_files', 'theme_document_security_headers'
)


#: How much of a served file each ``http.response.body`` message carries.
_FILE_CHUNK_SIZE = 2 * 1024 * 1024


def _vary_cookie_required(path: str) -> bool:
    """Return whether a response can depend on the browser session."""
    if path.startswith('/static/'):
        return False
    return path not in {
        '/favicon.ico', '/manifest.webmanifest', '/offline', '/pulse', '/awake',
        '/sw.js', '/vr/sw.js',
    }


def _ensure_cookie_vary(message: dict) -> dict:
    """Add Cookie to an ASGI response's Vary headers without dropping peers."""
    if message.get('type') != 'http.response.start':
        return message
    headers = list(message.get('headers') or ())
    vary_values = [value for key, value in headers if key.lower() == b'vary']
    tokens = {
        token.strip().lower()
        for value in vary_values
        for token in value.decode('latin1').split(',')
    }
    if '*' in tokens or 'cookie' in tokens:
        return message
    return {**message, 'headers': headers + [(b'vary', b'Cookie')]}


def _file_headers(filename: str, size: int) -> list[tuple[bytes, bytes]]:
    """Response headers for a file download of *size* bytes."""
    secure_name = secure_filename(filename) or "download.zip"
    return [
        (b"content-type", get_content_type_for_file(filename, filename).encode()),
        (b"content-disposition", f'attachment; filename="{secure_name}"'.encode()),
        (b"content-length", str(size).encode()),
        (b"cache-control", b"no-cache"),
    ]


async def _read_chunks(handle, size: int):
    """Yield exactly *size* bytes of an open file, reading off the event loop.

    *size* was announced in ``content-length``, so a file that shrank under us
    is an error (the response then ends short and the client can tell) and one
    that grew is cut off at the announced length instead of overrunning it.
    """
    loop = asyncio.get_running_loop()
    remaining = size
    while remaining > 0:
        chunk = await loop.run_in_executor(None, handle.read, min(_FILE_CHUNK_SIZE, remaining))
        if not chunk:
            raise OSError('file ended before the size announced for the download')
        remaining -= len(chunk)
        yield chunk


def _rom_location(rom_path, cache_dir, real_game, game_is_dir):
    """Where a resolved ROM may be read from.

    Returns ``(path to open, folder it must stay inside, whether that folder is
    already resolved)``. A ROM extracted from an archive lives in the app's own
    cache folder. A ROM in a game folder is held to the folder resolved when the
    request began (*real_game*). A game that is a single file is the file
    resolved at that moment, held to the folder it was in: the operator's own
    link to a file keeps working, and a link swapped in later is refused.
    """
    try:
        in_cache = Path(rom_path).is_relative_to(cache_dir)
    except (TypeError, ValueError):
        in_cache = False
    if in_cache:
        return rom_path, cache_dir, False
    if game_is_dir:
        return rom_path, real_game, True
    return real_game, os.path.dirname(real_game), True


# Proper ASGI application with lifespan protocol support
#: A visitor cancelling a download, not a server fault.
_CLIENT_GONE = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)


def _install_native_api_error_handlers(native_app, config, logger, *, routing_app=None) -> None:
    """Keep native API failures in the shared envelope without Flask context."""
    from fastapi import Request
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import JSONResponse
    from werkzeug.exceptions import NotFound

    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.error_envelope import http_error_code
    from oneirodex.utils.security_headers import security_header_values

    safe_messages = {
        400: 'Bad request',
        401: 'Unauthorized',
        403: 'Forbidden',
        # Flask's API HTTPException envelope uses the Werkzeug description for
        # unmatched routes. Keep ASGI route misses on the same client contract.
        404: NotFound().description,
        405: 'Method not allowed',
        409: 'Conflict',
        413: 'Request payload is too large',
        422: 'Invalid request',
        429: 'Too many requests',
    }

    async def http_error(request: Request, exc: StarletteHTTPException):
        status = int(exc.status_code or 500)
        if status == 404 and request.scope.get('route') is None:
            from oneirodex.runtime_native.response_compat import flask_route_not_found_response

            return flask_route_not_found_response(config, request)
        if status == 405 and request.method.upper() == 'OPTIONS':
            from oneirodex.runtime_native.response_compat import flask_auto_options_response

            response = flask_auto_options_response(
                config, request, route_app=native_app, routing_app=routing_app,
            )
            if response is not None:
                return response
        if status == 405:
            from oneirodex.runtime_native.response_compat import flask_http_exception_response

            return flask_http_exception_response(
                config, request, status, route_app=native_app, routing_app=routing_app,
                extra_headers=exc.headers,
            )
        payload, _ = api_error_payload(
            safe_messages.get(status, 'Request failed'),
            code=http_error_code(status),
            status=status,
        )
        response = JSONResponse(payload, status_code=status)
        for key, value in security_header_values(config).items():
            response.headers.setdefault(key, value)
        for key, value in (getattr(exc, 'headers', None) or {}).items():
            response.headers.setdefault(key, value)
        return response

    async def unexpected_error(_request: Request, _exc: Exception):
        logger.exception('Unhandled native API request failure')
        payload, status = api_error_payload(
            'Something went wrong on our end. The error has been logged.',
            code='internal',
        )
        response = JSONResponse(payload, status_code=status)
        for key, value in security_header_values(config).items():
            response.headers.setdefault(key, value)
        return response

    native_app.add_exception_handler(StarletteHTTPException, http_error)
    native_app.add_exception_handler(Exception, unexpected_error)


def _is_link_or_escape_refusal(exc: OSError) -> bool:
    """True when ``open_plain_file_within`` refused the file itself (a link,
    not a regular file, or outside its folder), as opposed to the file being
    locked, unreadable or failing with an I/O error."""
    import errno

    if exc.errno in (errno.ELOOP, errno.EINVAL):
        return True
    return exc.errno == errno.EACCES and exc.strerror == 'file is outside its folder'


def _is_native_admin_theme_font_path(path: str, method: str) -> bool:
    return (
        (path == '/admin/api/theme/fonts' and method == 'POST')
        or (path.startswith('/admin/api/theme/fonts/') and method == 'DELETE')
    )


def _is_native_image_refresh_progress_path(path: str, method: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] == 'check_image_refresh_progress'
        and bool(parts[1]) and method in ('GET', 'HEAD')
    )


def _is_native_library_delete_progress_path(path: str, method: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] == 'check_deletion_progress'
        and bool(parts[1]) and method in ('GET', 'HEAD')
    )


def _is_native_library_delete_sse_path(path: str, method: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] == 'delete_library_progress'
        and bool(parts[1]) and method in ('GET', 'HEAD')
    )


def _is_native_scan_job_mutation_path(path: str, method: str) -> bool:
    if method != 'POST':
        return False
    if path in {'/clear_all_scan_jobs', '/clear_scan_jobs'}:
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] in {
            'cancel_scan_job', 'delete_scan_job', 'restart_scan_job',
        }
        and bool(parts[1])
    )


def _is_native_admin_delete_image_path(path: str, method: str) -> bool:
    value = path.removeprefix('/admin/api/delete_image/')
    return method == 'DELETE' and bool(value) and value.isdigit()


def _is_native_admin_whitelist_path(path: str) -> bool:
    if path in {'/admin/api/whitelist', '/admin/whitelist'}:
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 3 and parts[:2] == ['admin', 'whitelist'] and parts[2].isdigit()


def _is_native_admin_whitelist_operation(path: str, method: str) -> bool:
    """Dispatch only the whitelist methods that match a native action route."""
    method = str(method or '').upper()
    if path == '/admin/api/whitelist':
        return method in {'GET', 'HEAD', 'POST'}
    if path == '/admin/whitelist':
        return method == 'POST'
    return _is_native_admin_whitelist_path(path) and method == 'DELETE'


def _is_native_auth_page_path(path: str) -> bool:
    if path in {'/login', '/register', '/reset_password_request'}:
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] == 'confirm' and bool(parts[1])
    ) or (
        len(parts) == 2 and parts[0] == 'reset_password' and bool(parts[1])
    )


class LazyASGIApp:
    def __init__(self):
        from oneirodex.utils.logging_setup import install_uvicorn_access_secret_filter

        # Native ASGI startup intentionally avoids the Flask app factory, so
        # install access-log redaction directly before Uvicorn handles requests.
        install_uvicorn_access_secret_filter()
        self._app = None
        self._flask_app = None
        self._native_sqlalchemy_engine = None
        self._runtime_config = None
        self._init_lock = asyncio.Lock()
        self._static_root: Path | None = (
            Path(__file__).resolve().parent / 'oneirodex' / 'static'
        )
        self._native_admin_pilot = None
        self._native_admin_routes = frozenset()
        self._native_read_api_app = None
        self._native_member_shell_app = None
        self._native_read_api_routes = frozenset({
            '/',
            '/index',
            '/restricted',
            '/api/trailers/filters',
            '/api/trailers/random',
            '/api/acquire/status',
            '/api/acquire/search',
            '/api/acquire/download',
            '/api/social/status',
            '/api/social/friends',
            '/api/activity',
            '/api/search',
            '/api/get_company_role',
            '/api/search_igdb_by_id',
            '/api/search_igdb_by_name',
            '/api/storage/hardlink/preview',
            '/api/storage/hardlink/apply',
            '/api/get_next_custom_igdb_id',
            '/api/move_game_to_library',
            '/api/favorites',
            '/api/current_user_role',
            '/api/icon-packs',
            '/api/check_username',
            '/api/vr/catalog',
            '/api/filters/bundle',
            '/api/library_platforms',
            '/api/get_libraries',
            '/api/scan_jobs_status',
            '/api/path/open',
            '/logout',
            '/demo',
            '/api/auth/login',
            '/api/auth/register',
            '/api/admin/newsletters',
            '/api/admin/server-settings',
            '/api/check_igdb_id',
            '/api/get_cover_thumbnail',
            '/api/reorder_libraries',
            '/api/admin/libraries/batch/edit',
            '/api/library/preview-cropped-image',
            '/api/genres',
            '/api/themes',
            '/api/game_modes',
            '/api/player_perspectives',
            '/api/igdb_platforms',
            '/api/filters/fields',
            '/api/filters/saved',
            '/api/filters/preview',
            '/api/games/batch/favorite',
            '/api/games/batch/status',
            '/api/games/batch/wishlist',
            '/api/games/batch/freshness/check',
            '/api/admin/freshness/refresh',
            '/api/games/batch/refresh_images',
            '/api/playtime/me',
            '/api/oidc/status',
            '/api/remote-play/status',
            '/api/settings/module-status',
            '/api/health/library',
            '/api/quality-profiles',
            '/api/storage/status',
            '/api/admin/malware-scan/status',
            '/api/admin/malware-scan',
            '/api/admin/challenge-solver/status',
            '/api/admin/challenge-solver/config',
            '/api/admin/challenge-solver/test',
            '/api/admin/ambient-lighting/status',
            '/api/admin/ambient-lighting/config',
            '/api/admin/ambient-lighting/test',
            '/api/rom-translate/capabilities',
            '/api/attract-mode/settings',
            '/api/attract-mode/user-override',
            '/api/setup/state',
            '/api/setup/step',
            '/api/admin/statistics',
            '/admin/statistics/data',
            '/api/hltb/stats',
            '/api/hltb/bulk-refresh',
            '/api/admin/games_search',
            '/api/palette/suggest',
            '/api/admin/integrations/metadata-providers',
            '/api/licensed-catalog',
            '/api/licensed-catalog/status',
            '/api/licensed-catalog/refresh',
            '/api/search_metadata/sources',
            '/api/search_metadata',
            '/api/ownership/providers',
            '/api/ownership/connections',
            '/api/ownership',
            '/api/ownership/titles',
            '/api/emulators',
            '/api/emulator-profiles',
            '/api/emulator/health',
            '/api/openapi.json',
            '/api/openapi.yaml',
            '/api/export/esde',
            '/api/export/pegasus',
            '/api/browser-player-settings',
            '/api/check_path_availability',
            '/api/library_roots',
            '/api/browse_folders_ss',
            '/api/unmatched_folders',
            '/api/unmatched_folders/duplicates',
            '/api/unmatched_folders/fix_logs',
            '/api/unmatched_folders/export',
            '/api/admin/themes',
            '/admin/api/art-studio/stock',
            '/admin/api/art-studio/system-marks',
            '/admin/api/art-studio/system-marks/lab',
            '/admin/api/theme/fonts',
            '/admin/api/system/reset',
            '/admin/api/art-studio/preview',
            '/admin/api/art-studio/generate',
            '/admin/api/art-studio/stock/generate',
            '/admin/api/art-studio/system-marks/generate',
            '/admin/api/art-studio/apply',
            '/admin/api/art-studio/apply-batch',
            '/admin/api/art-studio/batch-generate',
            '/admin/api/artwork/generate',
            '/admin/api/artwork/generate/batch',
            '/admin/api/image_queue_list',
            '/admin/api/download_images',
            '/admin/api/images/batch_upload',
            '/admin/api/covers/search',
            '/admin/api/covers/batch/search',
            '/admin/api/covers/apply',
            '/admin/api/covers/batch/apply',
            '/admin/api/artwork/auto-pick',
            '/api/admin/chat-emoji',
            '/api/chat/emoji',
            '/api/chat/channels',
            '/api/chat/spaces',
            '/api/chat/search',
            '/api/chat/dm',
            '/api/chat/spaces/join',
            '/api/layouts/detail',
            '/api/layouts/detail/mine',
            '/api/layouts/detail/presets',
            '/api/admin/smtp/settings',
            '/api/admin/smtp/test',
            '/admin/smtp_settings',
            '/admin/smtp_test',
            '/api/admin/igdb/settings',
            '/admin/igdb_settings',
            '/admin/test_igdb',
            '/api/admin/reference-sets',
            '/api/reference-sets',
            '/api/reference-sets/rehash',
            '/api/reference-sets/repair-preview',
            '/api/set-completion',
            '/api/admin/igdb/test',
            '/api/theme/fonts.css',
            '/api/admin/loading-icon/config',
            '/api/admin/themes/loading-icons',
            '/api/loading-icon',
            '/api/ai/status',
            '/api/ai/config',
            '/api/ai/triage',
            '/api/ai/doctor-notes',
            '/api/ai/apply-triage',
            '/api/admin/library_platforms',
            '/api/arr/status',
            '/api/arr/config',
            '/api/arr/indexers',
            '/api/arr/module',
            '/api/arr/search',
            '/api/arr/download',
            '/api/arr/hardlink/preview',
            '/api/arr/hardlink/apply',
            '/api/discover/sections',
            '/api/discover/surprise',
            '/api/discover/pins',
            '/api/account/summary',
            '/api/account/invites',
            '/api/account/preferences',
            '/settings_panel',
            '/api/locale',
            '/api/account/avatar/stock',
            '/api/account/avatar',
            '/settings_profile_edit',
            '/api/account/password',
            '/settings_password',
            '/api/calendar',
            '/api/tokens',
            '/api/client/capabilities',
            '/api/client/lifecycle',
            '/api/client/identity',
            '/api/client/heartbeat',
            '/api/client/commands',
            '/api/announcements',
            '/api/collections',
            '/api/requests',
            '/api/notifications',
            '/api/notifications/read',
            '/api/notifications/preferences',
            '/api/admin/notify-bus/test',
            '/api/events/publish_test',
            '/api/updates/wanted',
            '/api/updates/wanted/fulfill',
            '/api/updates/inbox',
            '/api/updates/store_search',
            '/api/updates/scan',
            '/api/news/gaming',
            '/api/news/free-games',
            '/api/rtc/status',
            '/api/rtc/token',
            '/browse_games',
        })

    async def _ensure_flask(self):
        """Initialize native configuration and routers once.

        Flask app injection remains available to compatibility tests which
        replace ``create_app`` explicitly. Normal ASGI startup builds only the
        framework-independent runtime context.
        """
        if self._app is not None:
            return
        async with self._init_lock:
            if self._app is not None:
                return
            from oneirodex.runtime_native.app_config import build_runtime_config
            from oneirodex.runtime_native.db_session import create_native_engine
            from oneirodex.runtime_native.runtime_context import (
                NativeRuntimeContext,
                install_flask_json_response_compat,
            )

            install_flask_json_response_compat()

            compatibility_app_injected = create_app is not _DEFAULT_CREATE_APP
            if compatibility_app_injected:
                # Existing route-parity tests can inject an in-memory Flask
                # host without making it part of the normal ASGI runtime.
                self._flask_app = create_app()
                self._runtime_config = dict(self._flask_app.config)
            else:
                self._runtime_config = build_runtime_config()
                package_root = Path(__file__).resolve().parent / 'oneirodex'
                self._flask_app = NativeRuntimeContext(
                    self._runtime_config, package_root=package_root,
                )
            database_url = self._runtime_config.get('SQLALCHEMY_DATABASE_URI')
            if self._native_sqlalchemy_engine is None and database_url:
                self._native_sqlalchemy_engine = create_native_engine(self._runtime_config)
            if isinstance(self._flask_app, NativeRuntimeContext):
                self._flask_app.native_engine = self._native_sqlalchemy_engine
            self._static_root = Path(self._flask_app.static_folder or '').resolve()
            # Native API handlers share a FastAPI app. Compatibility route
            # adapters receive config/logger/url helpers, not a Flask runtime.
            from fastapi import FastAPI
            from oneirodex.runtime_native.admin_pilot import _native_auth_backend
            from oneirodex.runtime_native.trailers import (
                TrailerAuthCallbacks,
                mount_trailers_routes,
            )
            from oneirodex.runtime_native.browse import mount_browse_routes
            from oneirodex.runtime_native.browse_locations import mount_browse_locations_routes
            from oneirodex.runtime_native.acquire_status import mount_acquire_status_routes
            from oneirodex.runtime_native.acquire_actions import mount_acquire_actions_routes
            from oneirodex.runtime_native.social_reads import mount_social_reads_routes
            from oneirodex.runtime_native.game_reads import mount_game_reads_routes
            from oneirodex.runtime_native.game_delete_mutations import mount_game_delete_mutation_routes
            from oneirodex.runtime_native.filter_reads import mount_filter_reads_routes
            from oneirodex.runtime_native.playtime import mount_playtime_routes
            from oneirodex.runtime_native.related_media import mount_related_media_routes
            from oneirodex.runtime_native.saved_filters import mount_saved_filter_routes
            from oneirodex.runtime_native.batch_favorite import mount_batch_favorite_routes
            from oneirodex.runtime_native.batch_status import mount_batch_status_routes
            from oneirodex.runtime_native.batch_wishlist import mount_batch_wishlist_routes
            from oneirodex.runtime_native.batch_refresh import mount_batch_refresh_routes
            from oneirodex.runtime_native.member_game_state import mount_member_game_state_routes
            from oneirodex.runtime_native.favorites import mount_favorites_routes
            from oneirodex.runtime_native.member_meta import mount_member_meta_routes
            from oneirodex.runtime_native.vr_reads import mount_vr_read_routes
            from oneirodex.runtime_native.social_writes import mount_social_writes_routes
            from oneirodex.runtime_native.oidc_status import mount_oidc_status_routes
            from oneirodex.runtime_native.remote_play_status import mount_remote_play_status_routes
            from oneirodex.runtime_native.settings_module_status import mount_settings_module_status_routes
            from oneirodex.runtime_native.library_health import mount_library_health_routes
            from oneirodex.runtime_native.game_health import mount_game_health_routes
            from oneirodex.runtime_native.quality_profiles import mount_quality_profiles_routes
            from oneirodex.runtime_native.status_reads import mount_status_reads_routes
            from oneirodex.runtime_native.device_status import mount_device_status_routes
            from oneirodex.runtime_native.rom_translate import mount_rom_translate_routes
            from oneirodex.runtime_native.loading_icon_admin import mount_loading_icon_admin_routes
            from oneirodex.runtime_native.attract_mode_reads import mount_attract_mode_routes
            from oneirodex.runtime_native.theme_font_css import mount_theme_font_routes
            from oneirodex.runtime_native.ai_status import mount_ai_status_routes
            from oneirodex.runtime_native.library_platforms import mount_library_platforms_routes
            from oneirodex.runtime_native.library_reads import mount_library_reads_routes
            from oneirodex.runtime_native.scan_job_reads import mount_scan_job_reads_routes
            from oneirodex.runtime_native.scan_job_mutations import mount_scan_job_mutation_routes
            from oneirodex.runtime_native.arr_status import mount_arr_status_routes
            from oneirodex.runtime_native.discover_reads import mount_discover_reads_routes
            from oneirodex.runtime_native.account_summary import mount_account_summary_routes
            from oneirodex.runtime_native.account_preferences import mount_account_preferences_routes
            from oneirodex.runtime_native.room_games import mount_room_games_routes
            from oneirodex.runtime_native.locale import mount_locale_routes
            from oneirodex.runtime_native.account_stock_avatar import mount_account_stock_avatar_routes
            from oneirodex.runtime_native.account_avatar_upload import mount_account_avatar_upload_routes
            from oneirodex.runtime_native.account_password import mount_account_password_routes
            from oneirodex.runtime_native.release_calendar import mount_release_calendar_routes
            from oneirodex.runtime_native.account_tokens import mount_account_tokens_routes
            from oneirodex.runtime_native.account_sessions import mount_account_sessions_routes
            from oneirodex.runtime_native.client_reads import mount_client_reads_routes
            from oneirodex.runtime_native.announcements import mount_announcements_routes
            from oneirodex.runtime_native.news_feeds import mount_news_feed_routes
            from oneirodex.runtime_native.collection_reads import mount_collection_reads_routes
            from oneirodex.runtime_native.wishlist import mount_wishlist_routes
            from oneirodex.runtime_native.notifications import mount_notifications_routes
            from oneirodex.runtime_native.wanted_updates import mount_wanted_updates_routes
            from oneirodex.runtime_native.updates_reads import mount_update_reads_routes
            from oneirodex.runtime_native.updates_scan import mount_update_scan_routes
            from oneirodex.runtime_native.setup_state import mount_setup_state_routes
            from oneirodex.runtime_native.admin_statistics import mount_admin_statistics_routes
            from oneirodex.runtime_native.admin_search import mount_admin_search_routes
            from oneirodex.runtime_native.palette_suggest import mount_palette_suggest_routes
            from oneirodex.runtime_native.metadata_providers_read import mount_metadata_providers_read_routes
            from oneirodex.runtime_native.licensed_catalog_reads import mount_licensed_catalog_reads_routes
            from oneirodex.runtime_native.metadata_search_sources import mount_metadata_search_sources_routes
            from oneirodex.runtime_native.metadata_search import mount_metadata_search_routes
            from oneirodex.runtime_native.admin_themes_read import mount_admin_themes_read_routes
            from oneirodex.runtime_native.ownership_providers import mount_ownership_provider_routes
            from oneirodex.runtime_native.ownership_actions import mount_ownership_actions_routes
            from oneirodex.runtime_native.ownership_admin_reads import mount_ownership_admin_read_routes
            from oneirodex.runtime_native.game_servers import mount_game_servers_routes
            from oneirodex.runtime_native.emulator_mutations import mount_emulator_mutation_routes
            from oneirodex.runtime_native.game_mods import mount_game_mods_routes
            from oneirodex.runtime_native.scan_unmatched_reads import mount_scan_unmatched_read_routes
            from oneirodex.runtime_native.scan_unmatched_mutations import mount_scan_unmatched_mutation_routes
            from oneirodex.runtime_native.scan_unmatched_feedback import mount_scan_unmatched_feedback_routes
            from oneirodex.runtime_native.emulator_reads import mount_emulator_read_routes
            from oneirodex.runtime_native.system_path_check import mount_system_path_check_routes
            from oneirodex.runtime_native.system_file_types import mount_system_file_type_routes
            from oneirodex.runtime_native.artwork_provider_search import mount_artwork_provider_search_routes
            from oneirodex.runtime_native.artwork_apply_mutation import mount_artwork_apply_routes
            from oneirodex.runtime_native.patch_catalog_routes import mount_patch_catalog_routes
            from oneirodex.runtime_native.download_request_reads import mount_download_request_read_routes
            from oneirodex.runtime_native.manual_identify_reads import mount_manual_identify_read_routes
            from oneirodex.runtime_native.manual_identify_mutations import mount_manual_identify_mutation_routes
            from oneirodex.runtime_native.retroachievements_settings import mount_retroachievements_settings_routes
            from oneirodex.runtime_native.admin_policy_settings import mount_admin_policy_settings_routes
            from oneirodex.runtime_native.admin_attract_mode import mount_admin_attract_mode_routes
            from oneirodex.runtime_native.admin_features import mount_admin_features_routes
            from oneirodex.runtime_native.admin_scan_filters import mount_admin_scan_filters_routes
            from oneirodex.runtime_native.manual_identify_session_preview import mount_manual_identify_session_preview_routes
            from oneirodex.runtime_native.admin_discovery_sections import mount_admin_discovery_sections_routes
            from oneirodex.runtime_native.admin_invites import mount_admin_invites_routes
            from oneirodex.runtime_native.admin_users_read import mount_admin_users_read_routes
            from oneirodex.runtime_native.admin_user_create import mount_admin_user_create_routes
            from oneirodex.runtime_native.admin_user_mutations import mount_admin_user_mutation_routes
            from oneirodex.runtime_native.admin_art_studio_reads import mount_admin_art_studio_read_routes
            from oneirodex.runtime_native.emulator_health import mount_emulator_health_routes
            from oneirodex.runtime_native.openapi_documents import mount_openapi_documents_routes
            from oneirodex.runtime_native.library_exports import mount_library_export_routes
            from oneirodex.runtime_native.admin_theme_fonts import mount_admin_theme_font_routes
            from oneirodex.runtime_native.admin_system_reset import mount_admin_system_reset_routes
            from oneirodex.runtime_native.admin_art_studio_preview import mount_admin_art_studio_preview_routes
            from oneirodex.runtime_native.admin_art_studio_actions import mount_admin_art_studio_action_routes
            from oneirodex.runtime_native.admin_artwork_generate import mount_admin_artwork_generation_routes
            from oneirodex.runtime_native.admin_artwork_batch import mount_admin_artwork_batch_routes
            from oneirodex.runtime_native.admin_image_queue_read import mount_admin_image_queue_read_routes
            from oneirodex.runtime_native.admin_cover_search import mount_admin_cover_search_routes
            from oneirodex.runtime_native.admin_cover_apply import mount_admin_cover_apply_routes
            from oneirodex.runtime_native.admin_cover_batch import mount_admin_cover_batch_routes
            from oneirodex.runtime_native.admin_image_mutations import mount_admin_image_mutation_routes
            from oneirodex.runtime_native.admin_whitelist import mount_admin_whitelist_routes
            from oneirodex.runtime_native.admin_plugins_read import mount_admin_plugins_routes
            from oneirodex.runtime_native.launcher_import_reads import mount_launcher_import_read_routes
            from oneirodex.runtime_native.download_mutations import mount_download_mutation_routes
            from oneirodex.runtime_native.support_mutations import mount_support_mutation_routes
            from oneirodex.runtime_native.launcher_import_mutations import mount_launcher_import_mutation_routes
            from oneirodex.runtime_native.library_tools import mount_library_tools_routes
            from oneirodex.runtime_native.library_tools_mutations import mount_library_tools_mutations_routes
            from oneirodex.runtime_native.library_tools_manual_identify import mount_manual_identify_list_routes
            from oneirodex.runtime_native.library_admin_mutations import mount_library_admin_mutations_routes
            from oneirodex.runtime_native.support_reads import mount_support_reads_routes
            from oneirodex.runtime_native.theme_fonts_read import mount_theme_fonts_read_routes
            from oneirodex.runtime_native.provider_catalog_reads import mount_provider_catalog_reads_routes
            from oneirodex.runtime_native.integrations_inventory import mount_integrations_inventory_routes
            from oneirodex.runtime_native.integration_settings import mount_integration_settings_routes
            from oneirodex.runtime_native.admin_newsletters import mount_admin_newsletters_routes
            from oneirodex.runtime_native.igdb_availability import mount_igdb_availability_routes
            from oneirodex.runtime_native.igdb_company_role import mount_igdb_company_role_routes
            from oneirodex.runtime_native.storage_hardlinks import mount_storage_hardlinks_routes
            from oneirodex.runtime_native.malware_scan_mutation import mount_malware_scan_mutation_routes
            from oneirodex.runtime_native.auth_confirmation import mount_auth_confirmation_routes
            from oneirodex.runtime_native.auth_login import mount_auth_login_routes
            from oneirodex.runtime_native.auth_logout import mount_auth_logout_routes
            from oneirodex.runtime_native.auth_pages import mount_auth_pages_routes
            from oneirodex.runtime_native.auth_registration import mount_auth_registration_routes
            from oneirodex.runtime_native.password_reset_confirm import mount_password_reset_confirm_routes
            from oneirodex.runtime_native.auth_form_posts import mount_auth_form_post_routes
            from oneirodex.runtime_native.oidc_auth import mount_oidc_auth_routes
            from oneirodex.runtime_native.setup_pages import mount_setup_pages_routes
            from oneirodex.runtime_native.setup_transition import mount_setup_transition_routes
            from oneirodex.runtime_native.site_redirects import mount_site_redirect_routes
            from oneirodex.runtime_native.play_redirect import mount_play_redirect_routes
            from oneirodex.runtime_native.styleguide import mount_styleguide_routes
            from oneirodex.runtime_native.admin_server_settings import mount_admin_server_settings_routes
            from oneirodex.runtime_native.admin_ops_reads import mount_admin_ops_reads_routes
            from oneirodex.runtime_native.admin_redirects import mount_admin_redirect_routes

            find_user, find_token, commit_token_touch = _native_auth_backend(self._flask_app)
            manager = getattr(self._flask_app, 'login_manager', None)
            # Native requests resolve the signed identity through the shared
            # fingerprint/active-user resolver and `find_user`; consulting
            # Flask-Login's callback here would keep native authentication
            # coupled to the legacy request extension.
            load_user_id = None
            self._native_read_api_app = FastAPI(
                docs_url=None,
                redoc_url=None,
                openapi_url=None,
            )
            from oneirodex.runtime_native.bounded_request_body import ASGIBodyLimitMiddleware
            from oneirodex.utils.security_headers import security_header_values

            native_body_limit = int(
                self._flask_app.config.get('MAX_CONTENT_LENGTH') or 128 * 1024 * 1024
            )
            native_error_headers = security_header_values(self._flask_app.config)
            self._native_read_api_app.add_middleware(
                ASGIBodyLimitMiddleware,
                max_bytes=native_body_limit,
                response_headers=native_error_headers,
            )
            self._native_read_api_app.router.redirect_slashes = False
            mount_site_redirect_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_play_redirect_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_styleguide_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.member_shell import create_member_shell_router

            self._native_member_shell_app = FastAPI(
                docs_url=None, redoc_url=None, openapi_url=None,
            )
            self._native_member_shell_app.add_middleware(
                ASGIBodyLimitMiddleware,
                max_bytes=native_body_limit,
                response_headers=native_error_headers,
            )
            self._native_member_shell_app.router.redirect_slashes = False
            self._native_member_shell_app.include_router(create_member_shell_router(
                self._flask_app,
                database_scope=lambda app: self._native_database_scope(app),
            ))
            _install_native_api_error_handlers(
                self._native_read_api_app,
                self._flask_app.config,
                self._flask_app.logger,
                routing_app=self._flask_app,
            )
            mount_trailers_routes(
                self._native_read_api_app,
                self._flask_app,
                auth=TrailerAuthCallbacks(
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                        login_manager=manager,
                ),
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_browse_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_browse_locations_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_acquire_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_acquire_actions_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_social_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_member_game_state_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_favorites_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_member_meta_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_vr_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            # Register the static /games/batch/... routes before the dynamic
            # /games/{game_uuid}/... detail routes.
            mount_batch_refresh_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_game_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_game_delete_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_filter_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_playtime_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_related_media_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_saved_filter_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_batch_favorite_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_batch_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_batch_wishlist_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_social_writes_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_oidc_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_remote_play_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_settings_module_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_health_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_game_health_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_quality_profiles_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_status_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_device_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_rom_translate_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_loading_icon_admin_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_attract_mode_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_theme_font_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_ai_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_platforms_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_scan_job_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_scan_job_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_newsletters_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_igdb_availability_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_igdb_company_role_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_storage_hardlinks_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_malware_scan_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_auth_confirmation_routes(
                self._native_read_api_app,
                app_config=self._flask_app.config,
                database_scope=lambda: self._native_database_scope(self._flask_app),
            )
            mount_auth_login_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_auth_logout_routes(
                self._native_read_api_app,
                self._flask_app,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_auth_pages_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_oidc_auth_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_setup_pages_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_setup_transition_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_auth_registration_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_password_reset_confirm_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_auth_form_post_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.auth_demo import mount_public_demo_routes
            mount_public_demo_routes(
                self._native_read_api_app,
                self._flask_app,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_server_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_ops_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_redirect_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_arr_status_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.arr_config_read import mount_arr_config_routes
            mount_arr_config_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.arr_indexers_read import mount_arr_indexers_routes
            mount_arr_indexers_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_discover_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_summary_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_preferences_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_room_games_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_locale_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_stock_avatar_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_avatar_upload_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_password_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_release_calendar_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_tokens_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_account_sessions_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_client_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_announcements_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_news_feed_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_collection_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_wishlist_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_notifications_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_wanted_updates_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_update_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_update_scan_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_setup_state_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_statistics_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.hltb_stats import mount_hltb_stats_routes
            mount_hltb_stats_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.hltb_refresh import mount_hltb_refresh_routes
            mount_hltb_refresh_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_search_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_palette_suggest_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_metadata_providers_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_licensed_catalog_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_metadata_search_sources_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_metadata_search_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_themes_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_ownership_provider_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_ownership_actions_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_ownership_admin_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_artwork_provider_search_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_artwork_apply_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_patch_catalog_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_download_request_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_manual_identify_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_manual_identify_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_retroachievements_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_policy_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_attract_mode_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_features_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_scan_filters_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_manual_identify_session_preview_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_discovery_sections_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_invites_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_users_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_user_create_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_user_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_art_studio_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_openapi_documents_routes(
                self._native_read_api_app,
                self._flask_app,
            )
            mount_library_export_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_theme_font_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_system_reset_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_art_studio_preview_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_art_studio_action_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_artwork_generation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_artwork_batch_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_image_queue_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_cover_search_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_cover_apply_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_cover_batch_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_admin_image_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_emulator_health_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            admin_shell_path = self._static_root / 'dist' / 'admin-pilot' / 'index.html'
            mount_admin_whitelist_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
                shell_path=admin_shell_path,
            )
            mount_admin_plugins_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_launcher_import_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_download_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_support_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_launcher_import_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_game_servers_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_emulator_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_game_mods_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_scan_unmatched_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_scan_unmatched_mutation_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_scan_unmatched_feedback_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_tools_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_tools_mutations_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_manual_identify_list_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_library_admin_mutations_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_support_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_theme_fonts_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_provider_catalog_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_integrations_inventory_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_integration_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_emulator_read_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_system_path_check_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_system_file_type_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.chat_emoji_read import mount_chat_emoji_routes
            from oneirodex.runtime_native.chat_reads import mount_chat_reads_routes
            from oneirodex.runtime_native.layouts import mount_layout_routes
            mount_chat_emoji_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_chat_reads_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_layout_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.smtp_settings_read import mount_smtp_settings_routes
            mount_smtp_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.igdb_settings_read import mount_igdb_settings_routes
            mount_igdb_settings_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            from oneirodex.runtime_native.reference_sets_read import mount_reference_sets_routes
            mount_reference_sets_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            if not admin_shell_path.is_file() and not compatibility_app_injected:
                raise RuntimeError('Required built admin React shell is missing from the application static tree.')
            from oneirodex.runtime_native import (
                ADMIN_STATIC_ROUTES,
                ADMIN_BOOTSTRAP_ROUTE,
            )
            from oneirodex.runtime_native.admin_pilot import create_admin_pilot, legacy_chrome_fields
            self._native_admin_routes = frozenset((*ADMIN_STATIC_ROUTES, ADMIN_BOOTSTRAP_ROUTE))
            self._native_admin_pilot = (
                create_admin_pilot(
                    self._flask_app,
                    shell_path=admin_shell_path,
                    chrome_fields=legacy_chrome_fields,
                    database_scope=lambda app: self._native_database_scope(app),
                )
                if admin_shell_path.is_file() else None
            )
            # Keep the initialized sentinel tied to the native router. Every
            # registered legacy method/path is covered by FastAPI or an
            # explicit ASGI handler; unknown paths now get native 404/405s.
            self._app = self._native_read_api_app

    async def _ensure_native_database(self):
        """Prepare framework-free runtime config and DB engine for probes."""
        if self._runtime_config is not None and self._native_sqlalchemy_engine is not None:
            return
        async with self._init_lock:
            if self._runtime_config is None:
                from oneirodex.runtime_native.app_config import build_runtime_config

                self._runtime_config = build_runtime_config()
            if self._native_sqlalchemy_engine is None:
                from oneirodex.runtime_native.db_session import create_native_engine

                if self._runtime_config.get('SQLALCHEMY_DATABASE_URI'):
                    self._native_sqlalchemy_engine = create_native_engine(self._runtime_config)

    def _native_database_scope(self, app=None):
        """Return a native Session scope; retain a test/legacy fallback only."""
        from oneirodex.runtime_native.db_session import (
            native_engine_session_scope,
            native_session_scope,
        )

        if self._native_sqlalchemy_engine is not None:
            from oneirodex.runtime_native.runtime_context import NativeRuntimeContext

            if isinstance(self._flask_app, NativeRuntimeContext):
                return self._flask_app.app_context()
            return native_engine_session_scope(self._native_sqlalchemy_engine, db)
        return native_session_scope(app or self._flask_app, db)

    def _is_native_read_api_request(self, path: str, scope) -> bool:
        """Whether the native FastAPI app owns this request.

        The native app wins over the shell, admin-pilot and method-not-allowed
        branches below when one of its routes matches both path and method.
        Everything else falls through to those branches and, finally, to the
        native app (its 404 or 405).
        """
        app = self._native_read_api_app
        if app is None:
            return False
        router = getattr(app, 'router', None)
        if router is None:
            # A bare ASGI callable (unit-test stand-ins) has no route table to
            # consult; it owns whatever reaches this branch.
            return True
        probe = {'type': 'http', 'path': path, 'method': scope.get('method', 'GET'), 'root_path': ''}
        for route in router.routes:
            match, _ = route.matches(probe)
            if match is Match.FULL:
                return True
        return False

    @native_companion_cors
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(receive, send)
        elif scope["type"] == "http":
            path = scope["path"]
            if _vary_cookie_required(path):
                cookie_downstream_send = send

                async def send_with_cookie_vary(message):
                    await cookie_downstream_send(_ensure_cookie_vary(message))

                send = send_with_cookie_vary

            # Liveness has no DB, session, or app-context dependency. Keep it
            # available to the container probe without constructing Flask on
            # the first HTTP request. Normal lifespan startup may still eager
            # initialize Flask for the remaining compatibility routes.
            if path == '/pulse' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_liveness(scope, send)
                return

            if path == '/pulse' and scope.get('method') != 'OPTIONS':
                await self._handle_liveness_method_not_allowed(scope, send)
                return

            if path == '/awake' and scope.get('method') in ('GET', 'HEAD'):
                await self._ensure_native_database()
                await self._handle_readiness(scope, send)
                return

            if path == '/awake' and scope.get('method') != 'OPTIONS':
                await self._handle_get_head_method_not_allowed(scope, send)
                return

            if (
                path in ('/manifest.webmanifest', '/offline', '/sw.js', '/vr/sw.js')
                and scope.get('method') == 'OPTIONS'
            ):
                if await self._send_setup_redirect_if_required(scope, send):
                    return

            if await self._send_legacy_setup_gate_if_required(scope, send):
                return

            if scope.get('method', '').upper() == 'OPTIONS':
                if await self._handle_automatic_options(scope, receive, send):
                    return

            if path == '/manifest.webmanifest' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_app_manifest(scope, send)
                return

            if path == '/offline' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_offline(scope, send)
                return

            if path == '/offline' and scope.get('method') != 'OPTIONS':
                await self._handle_get_head_method_not_allowed(scope, send)
                return

            if path == '/manifest.webmanifest' and scope.get('method') != 'OPTIONS':
                await self._handle_get_head_method_not_allowed(scope, send)
                return

            if path in ('/sw.js', '/vr/sw.js') and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_service_worker(scope, send, path)
                return

            if path in ('/sw.js', '/vr/sw.js') and scope.get('method') != 'OPTIONS':
                await self._handle_get_head_method_not_allowed(scope, send)
                return

            if path == '/favicon.ico' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_favicon(scope, send)
                return

            if path == '/favicon.ico' and scope.get('method') != 'OPTIONS':
                await self._handle_get_head_method_not_allowed(scope, send)
                return

            if path == '/api/emulator/installed-cores.js' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_installed_cores(scope, send)
                return

            if path == '/api/emulator/installed-cores.js' and scope.get('method') != 'OPTIONS':
                await self._handle_api_method_not_allowed(scope, receive, send)
                return

            if (
                is_email_confirmation_page_route(path)
                and scope.get('method') in ('GET', 'HEAD')
            ):
                headers = dict(scope.get('headers', []))
                # This document route has no token side effect. Preserve queued
                # Flask flashes and request-loader auth whenever credentials
                # are present; a first-time credential-free visit can use the
                # shipped React shell directly.
                if not headers.get(b'cookie') and not headers.get(b'authorization'):
                    await self._handle_confirmation_shell(scope, send)
                    return

            if (
                path in {'/login', '/reset_password_request'}
                and scope.get('method') in ('GET', 'HEAD')
            ):
                headers = dict(scope.get('headers', []))
                # Existing sessions must retain the Flask-Login redirect and
                # request-loader credentials must retain their auth behavior.
                if not headers.get(b'cookie') and not headers.get(b'authorization'):
                    await self._handle_confirmation_shell(scope, send)
                    return

            if path.startswith('/download_zip/') or path.startswith('/api/downloadrom/'):
                await self._handle_download(scope, receive, send)
                return

            # Long-lived SSE must not run through request router middleware — a single
            # sync stream holds a bridge thread for the life of the connection
            # and freezes Discover/Admin/API fetches. True of any bridge.
            sse_key = path.rstrip('/') or '/'
            if sse_key in self._SSE_ROUTES:
                cfg = self._SSE_ROUTES[sse_key]
                await self._handle_sse(
                    scope,
                    receive,
                    send,
                    channel=cfg['channel'],
                    event_types=cfg['event_types'],
                    restrict_child=cfg['restrict_child'],
                )
                return

            # Serve /static/* natively. This began as a workaround for the
                # bridge failing under concurrent CSS/JS — it stays because the native path streams with
            # aiofiles and owns its own cache-control and security headers.
            if path.startswith('/static/'):
                await self._handle_static(scope, receive, send, path)
                return

            await self._ensure_flask()
            from oneirodex.runtime_native.admin_csrf_preflight import (
                admin_request_wants_json,
                bearer_admin_csrf_exempt,
                csrf_session_has_token,
                empty_admin_mutation_csrf_error,
                inspect_multipart_csrf_body,
                inspect_urlencoded_csrf_body,
                is_admin_mutation_scope,
                native_route_matches,
            )

            csrf_error = None
            native_admin_mutation = is_admin_mutation_scope(scope) and (
                    native_route_matches(self._native_read_api_app, scope)
                    or native_route_matches(self._native_admin_pilot, scope)
            )
            if native_admin_mutation:
                csrf_error = empty_admin_mutation_csrf_error(
                    scope, self._flask_app.config,
                )
            headers = {key.lower(): value for key, value in scope.get('headers', ())}
            content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
            if (
                csrf_error is None
                and native_admin_mutation
                and content_type in {
                    b'multipart/form-data', b'application/x-www-form-urlencoded',
                }
                and not bearer_admin_csrf_exempt(scope)
                and not csrf_session_has_token(scope, self._flask_app.config)
            ):
                # A body form token cannot validate without the signed
                # per-session CSRF value. Reject before consuming a request
                # body that cannot pass CSRF, except on exact Bearer routes
                # whose handlers validate token and admin scope themselves.
                csrf_error = empty_admin_mutation_csrf_error(
                    scope, self._flask_app.config, form_inspected=True,
                )
            if (
                csrf_error is None
                and (path == '/admin' or path.startswith('/admin/'))
                and scope.get('method', '').upper() in {'POST', 'PUT', 'PATCH', 'DELETE'}
                and not bearer_admin_csrf_exempt(scope)
            ):
                form_token, replay_receive, form_inspected = await inspect_urlencoded_csrf_body(
                    scope, receive, self._flask_app.config,
                )
                if not form_inspected:
                    form_token, replay_receive, form_inspected = await inspect_multipart_csrf_body(
                        scope, receive, self._flask_app.config,
                    )
                if form_inspected:
                    receive = replay_receive
                    csrf_error = empty_admin_mutation_csrf_error(
                        scope,
                        self._flask_app.config,
                        form_token=form_token,
                        form_inspected=True,
                    )
            if csrf_error is not None:
                close_replay = getattr(receive, 'close', None)
                if close_replay is not None:
                    close_replay()
                from starlette.responses import HTMLResponse, JSONResponse
                from oneirodex.utils.security_headers import security_header_values

                response_headers = security_header_values(self._flask_app.config)
                if admin_request_wants_json(scope):
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(csrf_error, code='bad_request')
                    response = JSONResponse(
                        payload, status_code=status, headers=response_headers,
                    )
                else:
                    response = HTMLResponse(
                        '<!doctype html>\n<html lang=en>\n'
                        '<title>400 Bad Request</title>\n<h1>Bad Request</h1>\n'
                        f'<p>{csrf_error}</p>\n',
                        status_code=400,
                        headers=response_headers,
                    )
                response.headers.setdefault('Vary', 'Cookie')
                await response(scope, receive, send)
                return
            if await self._send_legacy_setup_gate_if_required(
                scope, send, after_csrf=True,
            ):
                close_replay = getattr(receive, 'close', None)
                if close_replay is not None:
                    close_replay()
                return
            close_replay = getattr(receive, 'close', None)
            if close_replay is not None:
                replay_downstream_send = send

                async def send_with_replay_cleanup(message):
                    await replay_downstream_send(message)
                    if (
                        message.get('type') == 'http.response.body'
                        and not message.get('more_body', False)
                    ):
                        close_replay()

                send = send_with_replay_cleanup

            from oneirodex.runtime_native.member_shell import member_shell_route

            if (
                self._native_member_shell_app is not None
                and member_shell_route(path)
                and scope.get('method') in ('GET', 'HEAD')
            ):
                await self._native_member_shell_app(scope, receive, send)
                return
            if (
                self._native_read_api_app is not None
                and path in {'/admin/integrations/igdb/save', '/admin/integrations/igdb/test'}
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path in {'/admin/settings', '/admin/new_server_settings'}
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/admin/attract_mode_settings'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/admin/edit_filters'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/admin/reference_sets'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/admin/chat_emoji'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and is_local_game_image_route(path)
                and scope.get('method') in ('GET', 'HEAD')
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and is_game_image_refresh_route(path)
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and is_single_image_upload_route(path)
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and scope.get('method') == 'POST'
                and (path == '/admin/library/add' or is_library_edit_route(path))
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and (path == '/add_game_manual' or is_game_edit_route(path))
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path in {'/login/oidc', '/login/oidc/callback'}
                and scope.get('method') == 'GET'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            # Admin pages can share a path with their legacy POST compatibility
            # handler (for example GET /admin/smtp_settings and POST to the
            # same path). Resolve page GETs to the React shell before the API
            # router sees the POST-only route and turns the request into 405.
            if (
                self._native_admin_pilot is not None
                and path in self._native_admin_routes
                and scope.get('method') in ('GET', 'HEAD')
            ):
                await self._native_admin_pilot(scope, receive, send)
                return

            if self._is_native_read_api_request(path, scope):
                await self._native_read_api_app(scope, receive, send)
                return
            if path == '/api/auth/runtime-bootstrap' and scope['method'] in ('GET', 'HEAD'):
                from starlette.requests import Request
                from oneirodex.runtime_native.auth_runtime_bootstrap import member_auth_runtime_bootstrap

                response = member_auth_runtime_bootstrap(
                    self._flask_app,
                    Request(scope, receive),
                    database_scope=self._native_database_scope,
                    runtime='fastapi-session-compat',
                )
                if scope['method'] == 'HEAD':
                    response.body = b''
                await response(scope, receive, send)
                return
            if (self._native_admin_pilot is not None
                    and (
                        scope['method'] in ('GET', 'HEAD')
                        or (path == '/admin/manage-downloads' and scope['method'] == 'POST')
                    )
                    and (path in self._native_admin_routes
                         or is_game_edit_route(path)
                         or is_game_images_edit_route(path)
                         or is_numeric_admin_detail(path)
                         or is_library_edit_route(path))):
                await self._native_admin_pilot(scope, receive, send)
                return
            if (
                member_shell_route(path)
                and scope.get('method', '').upper() not in ('GET', 'HEAD', 'OPTIONS')
            ):
                # Native member document routes are GET/HEAD-only. Let all
                # explicit API/admin method handlers above win first, then
                # preserve Flask's 405 for unsupported methods instead of
                # letting the native API fallback turn them into 404s.
                # The invites document retains its legacy browser form POST,
                # which is dispatched before this fallback. Keep POST in the
                # 405 Allow header for other methods on that same path.
                if path == '/user/invites':
                    await self._send_method_not_allowed(
                        scope, send, {'GET', 'HEAD', 'OPTIONS', 'POST'},
                    )
                else:
                    await self._handle_get_head_method_not_allowed(scope, send)
                return
            if (
                self._native_admin_pilot is not None
                and path in self._native_admin_routes
                and scope.get('method', '').upper() not in ('GET', 'HEAD', 'OPTIONS')
                and await self._handle_native_admin_method_not_allowed(
                    scope, send,
                )
            ):
                return
            await self._native_read_api_app(scope, receive, send)

    async def _handle_automatic_options(self, scope, receive, send) -> bool:
        """Preserve Flask's automatic OPTIONS reply across split native apps."""
        from starlette.responses import Response

        direct_routes = {
            '/api/emulator/installed-cores.js',
            '/awake',
            '/favicon.ico',
            '/manifest.webmanifest',
            '/offline',
            '/pulse',
            '/sw.js',
            '/vr/sw.js',
        }
        path = scope.get('path', '/')
        if path in direct_routes:
            response = Response(
                content=b'',
                status_code=200,
                headers={
                    'Allow': 'OPTIONS, GET, HEAD',
                    **self._configured_security_headers(),
                },
                media_type='text/html',
            )
            await response(scope, receive, send)
            return True

        await self._ensure_flask()
        route_apps = [
            self._native_read_api_app,
            self._native_member_shell_app,
            self._native_admin_pilot,
        ]
        route_apps = [app for app in route_apps if app is not None]

        # Some routes deliberately implement OPTIONS. Preserve their handler
        # instead of replacing it with Flask's generated empty response. A
        # mounted Starlette app can match every method at its prefix, so walk
        # into mounts and require an actual route that declares OPTIONS.
        for app in route_apps:
            if self._matches_native_options_route(app, scope):
                await app(scope, receive, send)
                return True

        from starlette.requests import Request
        from oneirodex.runtime_native.response_compat import flask_auto_options_response

        response = flask_auto_options_response(
            self._flask_app,
            Request(scope, receive),
            route_app=route_apps,
            routing_app=self._flask_app,
        )
        if response is None:
            return False
        await response(scope, receive, send)
        return True

    @staticmethod
    def _configured_security_headers():
        """Return the same configured security policy used by Flask responses."""
        from config import Config
        from oneirodex.utils.security_headers import security_header_values

        return security_header_values({
            key: getattr(Config, key, None)
            for key in (
                'CSP_ENABLED', 'CSP_ENFORCE', 'HSTS_SECONDS',
                'SESSION_COOKIE_SECURE',
            )
        })

    async def _handle_liveness(self, scope, send):
        """Serve the existing GET/HEAD liveness contract as a native ASGI route."""
        from oneirodex import app_version
        from oneirodex.runtime_native.health import liveness_payload

        payload = json.dumps(
            liveness_payload(app_version), separators=(',', ':'), ensure_ascii=False,
            sort_keys=True,
        ).encode('utf-8') + b'\n'
        headers = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(payload)),
            **self._configured_security_headers(),
        }
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(key.lower().encode('ascii'), value.encode('latin-1'))
                        for key, value in headers.items()],
        })
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    async def _handle_liveness_method_not_allowed(self, scope, send):
        """Match Flask's 405 response without constructing an app or DB scope."""
        await self._handle_get_head_method_not_allowed(scope, send)

    async def _handle_get_head_method_not_allowed(self, scope, send):
        """Match the shared GET/HEAD 405 contract without constructing Flask."""
        await self._send_method_not_allowed(
            scope, send, {'GET', 'HEAD', 'OPTIONS'},
        )

    async def _handle_native_admin_method_not_allowed(self, scope, send) -> bool:
        """Preserve Flask's 405 when a native admin shell path has no handler.

        Admin document shells live in a separate FastAPI app from their legacy
        form/API handlers. The final ASGI fallback otherwise turns a path that
        exists in the admin pilot into a 404 when its method is unsupported.
        Collect methods from both native route tables so compatibility POSTs
        such as SMTP settings remain represented in ``Allow``.
        """
        from starlette.routing import Match

        methods: set[str] = set()
        matched_shell_path = False

        def partial_route_methods(routes, route_scope):
            """Walk FastAPI routers, including their lazily included routers."""
            for route in routes:
                original_router = getattr(route, 'original_router', None)
                if original_router is not None:
                    context = getattr(route, 'include_context', None)
                    prefix = str(getattr(context, 'prefix', '') or '').rstrip('/')
                    nested_scope = route_scope
                    if prefix:
                        path = str(route_scope.get('path') or '')
                        if path != prefix and not path.startswith(prefix + '/'):
                            continue
                        nested_scope = dict(route_scope)
                        nested_scope['path'] = path[len(prefix):] or '/'
                    yield from partial_route_methods(
                        getattr(original_router, 'routes', ()), nested_scope,
                    )
                    continue

                match, _child_scope = route.matches(route_scope)
                if match is Match.PARTIAL:
                    yield from (getattr(route, 'methods', None) or ())

        for native_app in (self._native_admin_pilot, self._native_read_api_app):
            router = getattr(native_app, 'router', None)
            for method in partial_route_methods(
                getattr(router, 'routes', ()), scope,
            ):
                if native_app is self._native_admin_pilot:
                    matched_shell_path = True
                methods.add(str(method).upper())

        if not matched_shell_path:
            return False
        methods.add('OPTIONS')
        await self._send_method_not_allowed(scope, send, methods)
        return True

    async def _send_method_not_allowed(self, scope, send, allowed_methods):
        """Emit the common HTML 405 while retaining route-specific methods."""
        body = (
            b'<!doctype html>\n<html lang=en>\n'
            b'<title>405 Method Not Allowed</title>\n'
            b'<h1>Method Not Allowed</h1>\n'
            b'<p>The method is not allowed for the requested URL.</p>\n'
        )
        allowed = {str(method).upper() for method in allowed_methods}
        preferred_order = ('OPTIONS', 'GET', 'HEAD')
        ordered = [method for method in preferred_order if method in allowed]
        ordered.extend(sorted(allowed.difference(ordered)))
        allow = ', '.join(ordered)
        headers = {
            'Allow': allow,
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(body)),
            **self._configured_security_headers(),
        }
        await send({
            'type': 'http.response.start',
            'status': 405,
            'headers': [(key.lower().encode('ascii'), value.encode('latin-1'))
                        for key, value in headers.items()],
        })
        await send({
            'type': 'http.response.body',
            'body': body,
            'more_body': False,
        })

    async def _handle_api_method_not_allowed(self, scope, receive, send):
        """Return the JSON 405 envelope for native API paths without Flask."""
        from starlette.responses import Response
        from oneirodex.utils.api_contract import api_error_payload

        message = 'The method is not allowed for the requested URL.'
        payload, status = api_error_payload(message, code='bad_request', status=405)
        body = json.dumps(
            payload, separators=(',', ':'), ensure_ascii=False, sort_keys=True,
        ).encode('utf-8') + b'\n'
        response = Response(
            content=body,
            status_code=status,
            headers={
                'Content-Type': 'application/json',
                **self._configured_security_headers(),
            },
        )
        await response(scope, receive, send)

    async def _handle_readiness(self, scope, send):
        """Run readiness with request-local DB scope without Flask dispatch."""
        from oneirodex.runtime_native.db_session import native_db
        from oneirodex.utils.health_probes import build_readiness
        from oneirodex.utils.security_headers import security_header_values

        config = self._runtime_config or {}
        with self._native_database_scope():
            body, status = build_readiness(
                config=config, database=native_db,
            )
        payload = json.dumps(
            body, separators=(',', ':'), ensure_ascii=False, sort_keys=True,
        ).encode('utf-8') + b'\n'
        header_values = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(payload)),
            **security_header_values(config),
        }
        headers = [(key.lower().encode('ascii'), value.encode('latin-1'))
                   for key, value in header_values.items()]
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    async def _handle_installed_cores(self, scope, send):
        """Serve the public WebRetro core allowlist without Flask startup."""
        from oneirodex.utils.webretro_cores import get_effective_installed_cores

        cores = sorted(get_effective_installed_cores())
        payload = ('var OD_INSTALLED_CORES = ' + json.dumps(cores) + ';\n').encode('utf-8')
        headers = {
            'Content-Type': 'application/javascript; charset=utf-8',
            'Content-Length': str(len(payload)),
            'Cache-Control': 'private, max-age=300',
            **self._configured_security_headers(),
        }
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(key.lower().encode('ascii'), value.encode('latin-1'))
                        for key, value in headers.items()],
        })
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    async def _handle_app_manifest(self, scope, send):
        """Build the install manifest in a request-local DB scope."""
        from oneirodex.utils.pwa_manifest import build_app_manifest
        from oneirodex.utils.processors import get_global_settings

        if await self._send_setup_redirect_if_required(scope, send):
            return
        with self._native_database_scope():
            settings = get_global_settings() or {}
        manifest = build_app_manifest(settings.get('site_name'))
        payload = json.dumps(
            manifest, separators=(',', ':'), ensure_ascii=True, sort_keys=True,
        ).encode('utf-8') + b'\n'
        headers = {
            'Content-Type': 'application/manifest+json',
            'Content-Length': str(len(payload)),
            'Cache-Control': 'public, max-age=3600',
            **self._configured_security_headers(),
        }
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(key.lower().encode('ascii'), value.encode('latin-1'))
                        for key, value in headers.items()],
        })
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    async def _send_legacy_setup_gate_if_required(
        self, scope, send, *, after_csrf=False,
    ) -> bool:
        """Apply Flask's before-request setup gate before native dispatch."""
        path = scope.get('path', '/')
        method = str(scope.get('method', 'GET')).upper()
        is_auth_page = (
            path == '/register'
            or (path != '/login' and _is_native_auth_page_path(path))
        )
        if is_auth_page and method not in {'GET', 'HEAD'}:
            # Flask-WTF runs before the legacy setup hook on unsafe methods.
            # Let native form handlers validate CSRF first, then apply the
            # same setup redirect before doing any form action.
            return False
        is_admin_path = path == '/admin' or path.startswith('/admin/')
        if (
            is_admin_path
            and method in {'POST', 'PUT', 'PATCH', 'DELETE'}
            and not after_csrf
        ):
            # Flask-WTF rejects an unsafe admin request before the setup hook.
            # Let the ASGI preflight preserve that order, then call this gate
            # again with after_csrf=True before dispatching any admin action.
            return False
        if (
            not (
                path == '/register'
                or path == '/scan_management'
                or is_admin_path
                or path.startswith('/admin/api/')
                or is_auth_page
            )
        ):
            return False

        # The native dispatcher also supports database-free route tests and
        # shell serving. The setup gate needs a configured database to know
        # whether setup is incomplete. Normal ASGI startup initializes the
        # native database before serving requests; leave framework-free shell
        # requests alone instead of constructing the runtime just to check.
        if self._native_sqlalchemy_engine is None:
            return False

        await self._ensure_flask()

        from oneirodex.runtime_native.runtime_context import NativeRuntimeContext

        if isinstance(self._flask_app, NativeRuntimeContext):
            # The native runtime deliberately exposes only URL-build helpers,
            # not Flask's full URL map. Use method-aware matches from the
            # mounted ASGI routers so unknown paths and unsupported methods
            # retain their normal 404/405 behavior.
            route_exists = (
                self._matches_native_app_route(self._native_admin_pilot, scope)
                or self._matches_native_app_route(self._native_read_api_app, scope)
            )
            if not route_exists:
                return False
        else:
            from werkzeug.exceptions import HTTPException

            try:
                self._flask_app.url_map.bind('localhost').match(
                    path, method=method,
                )
            except HTTPException:
                return False

        return await self._send_setup_redirect_if_required(
            scope, send, skip_active_step=True,
        )

    @staticmethod
    def _matches_native_app_route(app, scope) -> bool:
        """Return whether a concrete method/path matches a mounted native route."""
        if app is None:
            return False

        from starlette.routing import Match

        for route in getattr(getattr(app, 'router', None), 'routes', ()):
            match, _child_scope = route.matches(scope)
            if match is Match.FULL:
                return True
        return False

    @staticmethod
    def _matches_native_options_route(app, scope) -> bool:
        """Return whether a concrete native route explicitly handles OPTIONS."""
        if app is None:
            return False

        from starlette.routing import Match

        def matches(routes, route_scope) -> bool:
            for route in routes:
                match, child_scope = route.matches(route_scope)
                if match is Match.NONE:
                    continue
                methods = {str(method).upper() for method in (getattr(route, 'methods', ()) or ())}
                if match is Match.FULL and 'OPTIONS' in methods:
                    return True
                child_router = (
                    getattr(route, 'original_router', None)
                    or getattr(getattr(route, 'app', None), 'router', None)
                )
                if child_router is not None and matches(
                    getattr(child_router, 'routes', ()), {**route_scope, **child_scope},
                ):
                    return True
            return False

        return matches(
            getattr(getattr(app, 'router', None), 'routes', ()),
            {**scope, 'method': 'OPTIONS'},
        )

    async def _send_setup_redirect_if_required(
        self, scope, send, *, skip_active_step=False,
    ) -> bool:
        """Apply Flask's first-run redirect to direct ASGI documents and assets."""
        from oneirodex.runtime_native.response_compat import flask_redirect_response
        from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

        await self._ensure_native_database()
        with self._native_database_scope():
            if not should_redirect_to_setup():
                return False
            target = get_setup_redirect_url()
            if skip_active_step and target == scope.get('path', '/'):
                return False
            response = flask_redirect_response(
                target, status_code=302,
            )
        for key, value in self._configured_security_headers().items():
            response.headers.setdefault(key, value)
        if scope.get('method') == 'HEAD':
            response.body = b''
        await response(scope, None, send)
        return True

    async def _handle_offline(self, scope, send):
        """Serve the self-contained offline fallback without Flask request state."""
        if await self._send_setup_redirect_if_required(scope, send):
            return
        from oneirodex.utils.asset_version import asset_version
        from oneirodex.utils.offline_page import render_offline_page

        static_root = self._static_root or (
            Path(__file__).resolve().parent / 'oneirodex' / 'static'
        )
        retry_script = static_root / 'js' / 'od_offline_retry.js'
        retry_url = f'/static/js/od_offline_retry.js?v={asset_version(retry_script)}'
        payload = render_offline_page(retry_url).encode('utf-8')
        headers = {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(payload)),
            'Cache-Control': 'no-cache',
            **self._configured_security_headers(),
        }
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(key.lower().encode('ascii'), value.encode('latin-1'))
                        for key, value in headers.items()],
        })
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    async def _send_conditional_static_file(
        self,
        scope,
        send,
        candidate: Path,
        *,
        mimetype: str,
        max_age: int | None,
        additional_headers: dict[str, str] | None = None,
        security_headers: dict[str, str] | None = None,
        skip_additional_headers_for_status: tuple[int, ...] = (),
    ):
        """Send a trusted static file with Werkzeug-compatible validators and ranges."""
        try:
            headers_in = {
                key.decode('latin-1').upper().replace('-', '_'): value.decode('latin-1')
                for key, value in scope.get('headers', ())
            }
            environ = {
                'REQUEST_METHOD': scope.get('method', 'GET'),
                'SCRIPT_NAME': '',
                'PATH_INFO': scope.get('path', ''),
                'QUERY_STRING': '',
                'SERVER_NAME': 'localhost',
                'SERVER_PORT': '80',
                'SERVER_PROTOCOL': 'HTTP/1.1',
                'wsgi.version': (1, 0),
                'wsgi.url_scheme': scope.get('scheme', 'http'),
                'wsgi.input': io.BytesIO(),
                'wsgi.errors': io.StringIO(),
                'wsgi.multithread': True,
                'wsgi.multiprocess': False,
                'wsgi.run_once': False,
            }
            for key, value in headers_in.items():
                if key == 'CONTENT_TYPE':
                    environ['CONTENT_TYPE'] = value
                elif key == 'CONTENT_LENGTH':
                    environ['CONTENT_LENGTH'] = value
                else:
                    environ[f'HTTP_{key}'] = value

            response = await asyncio.to_thread(
                werkzeug_send_file,
                candidate,
                environ,
                mimetype=mimetype,
                max_age=max_age,
            )
        except RequestedRangeNotSatisfiable as exc:
            response = exc.get_response(environ)
        except OSError:
            await self._send_error(send, 404, 'Not Found')
            return

        response_headers = response.get_wsgi_headers(environ)
        for key, value in (security_headers or self._configured_security_headers()).items():
            response_headers.set(key, value)
        if response.status_code not in skip_additional_headers_for_status:
            for key, value in (additional_headers or {}).items():
                response_headers.set(key, value)
        headers = [(key.lower().encode('ascii'), value.encode('latin-1'))
                   for key, value in response_headers]
        status_code = response.status_code
        await send({
            'type': 'http.response.start',
            'status': status_code,
            'headers': headers,
        })
        try:
            if scope.get('method') == 'HEAD' or status_code == 304:
                await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
                return
            for chunk in response.response:
                if chunk:
                    await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        finally:
            response.close()

    async def _handle_service_worker(self, scope, send, path: str):
        """Serve origin-scoped PWA workers with the same no-cache policy."""
        if await self._send_setup_redirect_if_required(scope, send):
            return
        root = self._static_root or (
            Path(__file__).resolve().parent / 'oneirodex' / 'static'
        )
        filename, allowed_scope = (
            ('app-sw.js', '/') if path == '/sw.js'
            else ('vr-sw.js', '/vr')
        )
        # Service workers have origin-wide authority. Do not let mutable
        # library static overrides replace the shipped worker script.
        candidate = resolve_static_path(root, f'/static/{filename}')
        if candidate is None or not candidate.is_file():
            await self._send_error(send, 404, 'Not Found')
            return
        await self._send_conditional_static_file(
            scope,
            send,
            candidate,
            mimetype='application/javascript; charset=utf-8',
            max_age=None,
            additional_headers={'Service-Worker-Allowed': allowed_scope},
            skip_additional_headers_for_status=(416,),
        )

    async def _handle_favicon(self, scope, send):
        """Serve the browser icon with Werkzeug's conditional and range semantics."""
        root = self._static_root or (
            Path(__file__).resolve().parent / 'oneirodex' / 'static'
        )
        candidate = resolve_static_path(root, '/static/icons/favicon.ico')
        if candidate is None or not candidate.is_file():
            await self._send_error(send, 404, 'Not Found')
            return
        await self._send_conditional_static_file(
            scope,
            send,
            candidate,
            mimetype='image/vnd.microsoft.icon',
            max_age=None,
            additional_headers={'Cache-Control': 'public, max-age=3600'},
            skip_additional_headers_for_status=(416,),
        )

    async def _handle_confirmation_shell(self, scope, send):
        """Serve the read-only confirmation document for a fresh visitor."""
        root = self._static_root or (
            Path(__file__).resolve().parent / 'oneirodex' / 'static'
        )
        candidate = resolve_static_path(root, '/static/dist/member-auth/auth.html')
        if candidate is None:
            await self._send_error(send, 503, 'Service Unavailable')
            return
        try:
            payload = await asyncio.to_thread(candidate.read_bytes)
        except OSError:
            await self._send_error(send, 503, 'Service Unavailable')
            return
        if payload.count(b'id="member-auth-root"') != 1 or b'</body>' not in payload:
            await self._send_error(send, 503, 'Service Unavailable')
            return

        header_values = {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(payload)),
            'Cache-Control': 'no-store',
            'Vary': 'Cookie',
            **self._configured_security_headers(),
        }
        headers = [(key.lower().encode('ascii'), value.encode('latin-1'))
                   for key, value in header_values.items()]
        await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
        await send({
            'type': 'http.response.body',
            'body': b'' if scope.get('method') == 'HEAD' else payload,
            'more_body': False,
        })

    # path (no trailing slash) → native async SSE config
    _SSE_ROUTES = {
        '/api/activity/stream': {
            'channel': 'activity',
            'event_types': frozenset({'activity', 'presence', 'hello', 'test'}),
            'restrict_child': True,
        },
        '/api/events/stream': {
            'channel': 'events',
            # scan/download/ops fan-out — emit all bus types
            'event_types': None,
            'restrict_child': False,
        },
    }

    def _event_visible(self, event, user_id) -> bool:
        """Per-viewer filter for the live streams (utils/event_visibility.py)."""
        payload = getattr(event, 'payload', None) or {}
        if (
            getattr(event, 'visibility_user_id', None) is None
            and payload.get('user_id') is None
            and not payload.get('game_uuid')
        ):
            return True  # about no member and no game: no lookup needed
        try:
            from oneirodex.utils.event_visibility import event_visible_to

            with self._native_database_scope(self._flask_app):
                return event_visible_to(event, user_id)
        except Exception:  # noqa: BLE001 — when in doubt, do not send it
            return False

    async def _authorize_sse_user(self, user_id, *, restrict_child: bool) -> int | None:
        """Return HTTP error status, or None if the user may open SSE."""
        if not user_id:
            return 401
        from oneirodex.models import User
        from oneirodex.runtime_native.db_session import native_db
        from oneirodex.utils.rbac import normalize_role

        with self._native_database_scope(self._flask_app):
            user = native_db.session.get(User, user_id)
            if not user:
                return 401
            if restrict_child and normalize_role(getattr(user, 'role', None)) == 'child':
                return 403
        return None

    async def _handle_sse(
        self,
        scope,
        receive,
        send,
        *,
        channel: str,
        event_types: frozenset[str] | None,
        restrict_child: bool,
    ):
        """Async SSE — keeps the uvicorn event loop free (not WsgiToAsgi)."""
        if scope.get("method") != "GET":
            await self._send_error(send, 405, "Method Not Allowed")
            return

        await self._ensure_flask()
        user_id = await self._get_user_from_session(scope)
        auth_status = await self._authorize_sse_user(user_id, restrict_child=restrict_child)
        if auth_status is not None:
            await self._send_error(
                send,
                auth_status,
                "Unauthorized" if auth_status == 401 else "Restricted",
            )
            return

        from oneirodex.utils.event_bus import encode_sse, event_bus

        subscriber = event_bus.subscribe_async(asyncio.get_running_loop())

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-cache"),
                (b"x-accel-buffering", b"no"),
                (b"connection", b"keep-alive"),
            ],
        })

        disconnected = asyncio.Event()

        async def _watch_disconnect():
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected.set()
                    return

        hello = (
            f'event: hello\ndata: {{"ok": true, "channel": "{channel}"}}\n\n'
        ).encode('utf-8')
        watcher = asyncio.create_task(_watch_disconnect())
        try:
            await send({
                "type": "http.response.body",
                "body": hello,
                "more_body": True,
            })
            while not disconnected.is_set():
                next_event = asyncio.create_task(subscriber.get())
                done, _pending = await asyncio.wait(
                    (next_event, watcher),
                    timeout=1.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if watcher in done:
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                    break
                if next_event in done:
                    event = next_event.result()
                else:
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                    event = None
                if event is None:
                    await send({
                        "type": "http.response.body",
                        "body": b": keepalive\n\n",
                        "more_body": True,
                    })
                    continue
                if (event_types is None or event.type in event_types) and await asyncio.to_thread(
                    self._event_visible, event, user_id,
                ):
                    await send({
                        "type": "http.response.body",
                        "body": encode_sse(event),
                        "more_body": True,
                    })
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            print(f"Error in {channel} SSE: {exc}")
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            event_bus.unsubscribe(subscriber)
            try:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:
                pass

    async def _handle_static(self, scope, receive, send, path: str):
        """Stream static files with path-traversal protection."""
        if scope.get("method") not in ("GET", "HEAD"):
            await self._send_error(send, 405, "Method Not Allowed")
            return

        root = self._static_root
        if root is None or not root.is_dir():
            await self._send_error(send, 500, "Static root not configured")
            return

        # Members' private files under /static/library/ are never static; BIOS
        # needs a signed-in member. 404 either way, so nothing is confirmed.
        access = static_access(root, path)
        if access == 'private':
            await self._send_error(send, 404, "Not Found")
            return
        if access == 'member':
            # Only this protected static class needs the configured Flask
            # session boundary. Public files stay on the pure ASGI path.
            await self._ensure_flask()
            root = self._static_root
            if (root is None or not root.is_dir()
                    or static_access(root, path) != 'member'
                    or await self._get_user_from_session(scope) is None):
                await self._send_error(send, 404, "Not Found")
                return
        if root is None:
            await self._send_error(send, 404, "Not Found")
            return

        candidate = resolve_served_static(root, path)
        if candidate is None:
            await self._send_error(send, 404, "Not Found")
            return

        if not candidate.is_file():
            await self._send_error(send, 404, "Not Found")
            return

        content_type, _ = mimetypes.guess_type(str(candidate))
        if not content_type:
            content_type = 'application/octet-stream'
        # CSS/JS under themes often mis-detected on some platforms
        lower = candidate.name.lower()
        if lower.endswith('.css'):
            content_type = 'text/css; charset=utf-8'
        elif lower.endswith('.js'):
            content_type = 'application/javascript; charset=utf-8'
        elif lower.endswith('.map'):
            content_type = 'application/json'
        elif lower.endswith('.svg'):
            content_type = 'image/svg+xml'
        elif lower.endswith('.woff2'):
            content_type = 'font/woff2'
        elif lower.endswith('.woff'):
            content_type = 'font/woff'

        try:
            candidate.stat()
        except OSError:
            await self._send_error(send, 404, "Not Found")
            return

        # Two families of file are rewritten in place at a stable path, so an
        # hour of blind caching hides a change that has already shipped. Images
        # and fonts are genuinely static and keep the hour.
        #
        # Theme files are rewritten by Reset Themes while every template keeps
        # pointing at the same path. `theme_asset` versions those URLs, and this
        # is the second half: even an unversioned reference revalidates instead
        # of being assumed fresh.
        normalized = path.replace('\\', '/')
        is_mutable_theme_asset = '/static/library/themes/' in normalized
        # The SPA *entry* bundle is unhashed on purpose so the page shell can link it,
        # and the `?v=` on that link makes the script tag fetch fresh. But the
        # lazy route chunks `import` the entry by its bare path, with no query,
        # and that unversioned URL was cached for an hour — so after a rebuild
        # every lazily-loaded route went on running the *previous* build's
        # shared code while the versioned script tag reported the new one.
        # Observed directly: a fixed component kept rendering its old markup,
        # and `performance` showed two fetches of member-app.js at two sizes.
        # `chunks/` keeps the hour — those names carry a content hash, so a new
        # build is a new URL and caching them hard is the point.
        is_spa_entry = '/static/dist/' in normalized and '/chunks/' not in normalized
        cache_control = (
            b"no-cache"
            if (is_mutable_theme_asset or is_spa_entry)
            else b"public, max-age=3600"
        )

        # Static is served directly by ASGI, so Flask's after_request never
        # sees it. Preserve the established cache/security policy while using
        # Werkzeug for ETag, conditional and byte-range behavior.
        baseline = {
            key.decode('ascii').title(): value.decode('latin-1')
            for key, value in baseline_static_headers()
        }
        await self._send_conditional_static_file(
            scope,
            send,
            candidate,
            mimetype=content_type,
            max_age=3600 if cache_control == b'public, max-age=3600' else None,
            additional_headers={
                **baseline,
                **theme_document_security_headers(path, content_type),
                'Cache-Control': cache_control.decode('ascii'),
            },
            security_headers=baseline,
        )

    async def _handle_download(self, scope, receive, send):
        """Handle download routes with async file streaming"""
        path = scope["path"]
        method = scope["method"]

        if method != "GET":
            await self._send_error(send, 405, "Method Not Allowed")
            return

        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._ensure_flask()

            if path.startswith('/download_zip/'):
                await self._handle_zip_download(scope, receive, tracked_send, path)
            elif path.startswith('/api/downloadrom/'):
                await self._handle_rom_download(scope, receive, tracked_send, path)

        except Exception as e:
            print(f"Error in async download handler: {str(e)}")
            if response_started:
                # Status and part of the body are already out. A second response
                # cannot be sent, and ending the body cleanly would hand the
                # client a truncated download that looks complete: let the
                # server drop the connection so the transfer visibly fails.
                raise
            try:
                await self._send_error(tracked_send, 500, "Internal Server Error")
            except Exception as error_e:
                print(f"Could not send error response (response may have already started): {str(error_e)}")

    async def _handle_zip_download(self, scope, receive, send, path):
        """Handle ZIP file downloads"""
        from oneirodex.models import DownloadRequest, Game, User

        download_id_match = re.match(r'/download_zip/(\d+)', path)
        if not download_id_match:
            await self._send_error(send, 400, "Invalid download ID")
            return

        download_id = int(download_id_match.group(1))

        user_id = await self._get_user_id(scope)
        if not user_id:
            await self._send_error(send, 401, "Unauthorized")
            return

        from oneirodex.runtime_native.db_session import native_db

        with self._native_database_scope(self._flask_app):
            user = native_db.session.get(User, user_id)
            if not user or 'write:download' in forbidden_scopes_for_role(user.role):
                await self._send_error(send, 403, "Access denied")
                return

            download_request = native_db.session.execute(
                select(DownloadRequest).filter_by(id=download_id, user_id=user_id)
            ).scalars().first()

            if not download_request:
                await self._send_error(send, 404, "Download not found")
                return

            game = native_db.session.execute(
                select(Game).filter_by(uuid=download_request.game_uuid)
            ).scalars().first()
            if not game or not user_can_access_game(user, game):
                await self._send_error(send, 403, "Access denied")
                return

            if download_request.status != 'available':
                await self._send_error(send, 400, "Download not ready")
                return

            file_path = download_request.zip_file_path

            # Existing tickets may still point at a single launcher from a
            # previous release. Re-evaluate base directories before serving.
            base_path = getattr(game, 'full_disk_path', None)
            is_base = bool(base_path and getattr(download_request, 'file_location', None) == base_path)
            if is_base:
                bases = get_allowed_base_directories(self._flask_app)
                if not bases or not is_safe_path(base_path, bases)[0]:
                    await self._send_error(send, 403, "Access denied")
                    return
                if os.path.isdir(base_path):
                    from oneirodex.runtime_native.download_mutations import DownloadMutationData
                    file_path = DownloadMutationData().legacy_zip_path(game)
            if not file_path:
                await self._send_error(send, 404, "File not found")
                return
            from urllib.parse import parse_qs

            query = parse_qs(scope.get('query_string', b''))
            wrap_file = query.get(b'representation') == [b'companion_zip'] and (
                file_path and not file_path.lower().endswith('.zip')
            )
            if os.path.isdir(file_path) or wrap_file:
                from oneirodex.runtime_native.download_mutations import base_download_exclusions
                excluded = base_download_exclusions() if is_base else ()
                await self._handle_streaming_download(send, download_request, file_path, excluded_folders=excluded)
                return

            allowed_bases = get_allowed_base_directories(self._flask_app)
            if not allowed_bases:
                await self._send_error(send, 500, "Server configuration error")
                return

            # Resolved once and vetted; the file is then opened pinned to that
            # location and streamed from the open descriptor, so a link swapped
            # in while the log rows below are written is refused, not followed.
            try:
                real_path = os.path.realpath(file_path)
            except (OSError, ValueError):
                real_path = file_path
            is_safe, error_message = is_safe_path(real_path, allowed_bases)
            if not is_safe:
                log_system_event(
                    f"Security violation - game file outside allowed directories: {file_path[:100]}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            try:
                handle = open_plain_file_within(os.path.dirname(real_path), real_path, base_is_resolved=True)
            except FileNotFoundError:
                await self._send_error(send, 404, "File not found")
                return
            except OSError as exc:
                if not _is_link_or_escape_refusal(exc):
                    # Locked by another program (a Windows sharing violation),
                    # unreadable, or an I/O error: not an attack, just unavailable.
                    log_system_event(
                        f"Download file could not be opened: {os.path.basename(file_path)} ({type(exc).__name__})",
                        event_type='download',
                        event_level='warning',
                    )
                    await self._send_error(send, 503, "File is temporarily unavailable")
                    return
                log_system_event(
                    f"Security violation - download file is not a plain file in place: {file_path[:100]}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            filename = os.path.basename(file_path)
            try:
                log_system_event(
                    f"Async file download: {filename}",
                    event_type='download',
                    event_level='information',
                )
            except BaseException:
                handle.close()
                raise
            headers = dict(scope.get('headers', ()))
            if filename.lower().endswith('.zip') and headers.get(b'x-oneirodex-resume') == b'1':
                await self._stream_file(send, handle, filename, resume=headers)
            else:
                await self._stream_file(send, handle, filename)

    async def _handle_rom_download(self, scope, receive, send, path):
        """Handle ROM file downloads for emulator"""
        from oneirodex.models import Game, User
        from oneirodex.utils.rom_archive import ArchiveRomError
        from oneirodex.utils.rom_archive_types import (
            DEFAULT_MAX_ROM_OUTPUT_BYTES,
            RomExpansionBudget,
        )

        rom_match = re.match(r'/api/downloadrom/([a-f0-9-]+)', path)
        if not rom_match:
            await self._send_error(send, 400, "Invalid game UUID")
            return

        game_uuid = rom_match.group(1)

        try:
            uuid.UUID(game_uuid)
        except ValueError:
            log_system_event(
                f"Invalid UUID format attempted for ROM download: {game_uuid}",
                event_type='security',
                event_level='warning',
            )
            await self._send_error(send, 400, "Invalid game identifier")
            return

        user_id = await self._get_user_id(scope)
        if not user_id:
            await self._send_error(send, 401, "Unauthorized")
            return

        from oneirodex.runtime_native.db_session import native_db

        with self._native_database_scope(self._flask_app):
            game = native_db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

            if not game:
                log_system_event(
                    f"ROM download attempt for non-existent game UUID: {game_uuid}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 404, "Game not found")
                return

            user = native_db.session.get(User, user_id)
            if not user or not user_can_access_game(user, game):
                log_system_event(
                    f"ROM download blocked by library ACL for user_id={user_id} game={game_uuid[:8]}...",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            if not game.full_disk_path or not os.path.exists(game.full_disk_path):
                log_system_event(
                    f"ROM download attempt for missing file: {game.name} at {game.full_disk_path}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 404, "ROM file not found on disk")
                return

            allowed_bases = get_allowed_base_directories(self._flask_app)
            # Resolved once, here. Every later check and the open compare against
            # this string, so a game folder swapped for a link afterwards reads
            # as "outside" instead of moving the boundary with it.
            try:
                real_game = os.path.realpath(game.full_disk_path)
            except (OSError, ValueError):
                real_game = game.full_disk_path
            is_safe, error_message = is_safe_path(real_game, allowed_bases)

            if not is_safe:
                log_system_event(
                    f"Path traversal attempt blocked for ROM download: {game.full_disk_path} - {error_message}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            game_is_dir = os.path.isdir(real_game)
            cache_root = os.path.join(library_dir(self._flask_app.root_path), 'rom_cache')
            os.makedirs(cache_root, exist_ok=True)
            needs_expansion = game_is_dir or Path(real_game).suffix.lower() in {
                '.zip', '.7z', '.rar', '.gz', '.cue',
            }
            if needs_expansion and not _ROM_EXTRACTION_LIMITER.acquire(blocking=False):
                await self._send_error(
                    send,
                    503,
                    'ROM conversion is busy. Try again shortly.',
                    code='rom_processing_busy',
                )
                return

            cache_dir = None
            rom_expansion_lock = None
            try:
                if needs_expansion:
                    from oneirodex.utils.rom_archive_lock import (
                        try_acquire_rom_expansion_lock,
                    )

                    rom_expansion_lock = try_acquire_rom_expansion_lock(cache_root)
                    if rom_expansion_lock is None:
                        await self._send_error(
                            send,
                            503,
                            'ROM conversion is busy. Try again shortly.',
                            code='rom_processing_busy',
                        )
                        return

                    # Respect both the configured per-request ceiling and the
                    # free-space reserve on the writable library volume. The
                    # process-shared lock makes this a volume-wide bound even
                    # when Uvicorn uses multiple worker processes.
                    configured_limit = int(
                        self._flask_app.config.get('ROM_MAX_OUTPUT_BYTES')
                        or DEFAULT_MAX_ROM_OUTPUT_BYTES
                    )
                    configured_limit = max(1, configured_limit)
                    reserve = max(
                        0,
                        int(self._flask_app.config.get('ROM_CACHE_RESERVE_BYTES') or 0),
                    )
                    free_for_rom = max(0, shutil.disk_usage(cache_root).free - reserve)
                    rom_budget = RomExpansionBudget(min(configured_limit, free_for_rom))
                else:
                    rom_budget = RomExpansionBudget()

                # Extraction output is request-scoped and remains protected by
                # the limiter until streaming ends and the directory is removed.
                cache_dir = tempfile.mkdtemp(prefix=f'{game_uuid}-', dir=cache_root)
                platform_key = library_platform_key(game)
                source_path = game.full_disk_path
                try:
                    def resolve_download_target():
                        rom_path, resolved_filename = resolve_playable_rom_path(
                            source_path,
                            cache_dir=cache_dir,
                            platform=platform_key,
                            budget=rom_budget,
                        )
                        resolved_target, resolved_root, resolved_root_is_resolved = _rom_location(
                            rom_path, cache_dir, real_game, game_is_dir
                        )
                        # Multi-track discs (.cue + .bin/.img/...) need every
                        # file in one response; WebRetro cannot fetch companions later.
                        bundled_path, bundled_name = bundle_playable_rom_zip(
                            resolved_target,
                            cache_dir,
                            root=resolved_root if resolved_root_is_resolved else None,
                            budget=rom_budget,
                        )
                        if bundled_path != resolved_target:
                            resolved_target, resolved_root, resolved_root_is_resolved = (
                                bundled_path, cache_dir, False
                            )
                            resolved_filename = bundled_name
                        return (
                            resolved_target,
                            resolved_root,
                            resolved_root_is_resolved,
                            resolved_filename,
                        )

                    # Archive listing, extraction, CUE bundling, and their file
                    # copies are synchronous; keep that work off the ASGI loop.
                    from starlette.concurrency import run_in_threadpool

                    target, root, root_is_resolved, filename = await run_in_threadpool(
                        resolve_download_target
                    )
                except ArchiveRomError as exc:
                    log_system_event(
                        f"ROM resolve failed for {game.name}: {exc.message}",
                        event_type='download',
                        event_level='warning',
                    )
                    await self._send_error(
                        send,
                        exc.status_code,
                        exc.message,
                        code=exc.code,
                        hint=exc.hint,
                    )
                    return

                # Keep temporary output alive until streaming closes the file.
                try:
                    handle = open_plain_file_within(root, target, base_is_resolved=root_is_resolved)
                except FileNotFoundError:
                    await self._send_error(send, 404, "ROM file not found on disk")
                    return
                except OSError:
                    log_system_event(
                        f"ROM download refused, file is not a plain file in place: {game.name}",
                        event_type='security',
                        event_level='warning',
                    )
                    await self._send_error(send, 403, "Access denied")
                    return

                try:
                    log_system_event(
                        f"ROM file downloaded for WebRetro: {game.name}",
                        event_type='download',
                        event_level='information',
                    )
                except BaseException:
                    handle.close()
                    raise
                await self._stream_file(send, handle, filename)
            finally:
                if cache_dir:
                    shutil.rmtree(cache_dir, ignore_errors=True)
                try:
                    if rom_expansion_lock is not None:
                        from oneirodex.utils.rom_archive_lock import (
                            release_rom_expansion_lock,
                        )

                        release_rom_expansion_lock(rom_expansion_lock)
                finally:
                    if needs_expansion:
                        _ROM_EXTRACTION_LIMITER.release()

    async def _get_user_id(self, scope):
        """Resolve user id from Bearer token (API clients) or Flask session cookie (web)."""
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")
        if auth_header.lower().startswith("bearer "):
            await self._ensure_flask()
            from starlette.requests import Request

            from oneirodex.runtime_native.admin_pilot import _native_auth_backend
            from oneirodex.runtime_native.request_auth import request_auth_context

            find_user, find_token, commit_token_touch = _native_auth_backend(self._flask_app)
            # The ASGI download adapter historically gives an explicit Bearer
            # credential precedence over cookies; don't let a parallel browser
            # session change which credential is evaluated.
            bearer_scope = {
                **scope,
                'type': 'http',
                'headers': [
                    (key, value) for key, value in scope.get('headers', [])
                    if key.lower() != b'cookie'
                ],
            }
            with self._native_database_scope(self._flask_app):
                auth = request_auth_context(
                    Request(bearer_scope), self._flask_app.config,
                    find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    login_manager=getattr(self._flask_app, 'login_manager', None),
                )
                user = auth.user
                if (
                    user
                    and auth.token
                    and auth.has_scope('write:download')
                ):
                    return user.id
            return None

        return await self._get_user_from_session(scope)

    async def _get_user_from_session(self, scope):
        """Extract user ID from Flask session cookie"""
        try:
            await self._ensure_flask()
            from starlette.requests import Request

            from oneirodex.runtime_native.admin_pilot import _native_auth_backend
            from oneirodex.runtime_native.request_auth import request_auth_context

            request_scope = {**scope, 'type': 'http'}
            request = Request(request_scope)
            config = dict(self._flask_app.config)
            find_user, find_token, commit_token_touch = _native_auth_backend(self._flask_app)
            with self._native_database_scope(self._flask_app):
                auth = request_auth_context(
                    request, config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    login_manager=getattr(self._flask_app, 'login_manager', None),
                    allow_bearer=False,
                    touch_bearer=False,
                    allow_remember=False,
                )
                return auth.user.id if auth.user is not None else None

        except Exception as e:
            log_system_event(
                f"Error parsing signed session for download authorization: {type(e).__name__}",
                event_type='security',
                event_level='warning',
            )
            return None

    async def _stream_file(self, send, handle, filename, *, resume=None):
        """Stream an open file that ``open_plain_file_within`` already vetted.

        The size is the descriptor's and so are the bytes, so what is announced
        is what is sent whatever happens to the path meanwhile. *handle* is
        closed here.
        """
        started = False
        try:
            with handle:
                size = os.fstat(handle.fileno()).st_size

                status = 200
                headers = _file_headers(filename, size)
                if resume is not None:
                    from oneirodex.utils.archive_range import archive_identity, resolve_range
                    etag, total = await asyncio.to_thread(archive_identity, handle)
                    status, start, size = resolve_range(
                        total, resume.get(b'range', b'').decode('latin1'),
                        resume.get(b'if-range', b'').decode('latin1'), etag)
                    headers = _file_headers(filename, size) + [
                        (b'accept-ranges', b'bytes'), (b'etag', etag.encode('ascii')),
                    ]
                    if status == 416:
                        headers.append((b'content-range', f'bytes */{total}'.encode()))
                    if status == 206:
                        headers.append((b'content-range', f'bytes {start}-{total-1}/{total}'.encode()))
                    handle.seek(start)
                started = True
                await send({'type': 'http.response.start', 'status': status, 'headers': headers})

                async for chunk in _read_chunks(handle, size):
                    await send({
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    })

                await send({
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                })

        except Exception as e:
            log_system_event(
                f"Download of {filename} ended early: the client closed the connection"
                if isinstance(e, _CLIENT_GONE) else f"Error streaming file {filename}: {str(e)}",
                event_type='download',
                event_level='information' if isinstance(e, _CLIENT_GONE) else 'error',
            )
            if started:
                # Past the status line the only honest ending is an aborted
                # transfer; see _handle_download.
                raise
            await self._send_error(send, 500, "Error streaming file")

    async def _handle_streaming_download(self, send, download_request, source_path, *, excluded_folders=None):
        """Handle zipstream downloads for multi-file games"""
        started = False
        try:
            allowed_bases = get_allowed_base_directories(self._flask_app)
            if not allowed_bases:
                await self._send_error(send, 500, "Server configuration error")
                return

            # Resolved once, here, and the resolved path is what gets checked and
            # what the zip is built from. The generator compares every file
            # against this string and never resolves the folder again, so a game
            # folder swapped for a link after this point cannot widen "inside".
            try:
                real_root = os.path.realpath(source_path)
            except (OSError, ValueError):
                real_root = source_path
            is_safe, error_message = is_safe_path(real_root, allowed_bases)
            if not is_safe:
                print(f"Security violation - streaming source outside allowed directories: {source_path[:100]}")
                await self._send_error(send, 403, "Access denied")
                return

            if not os.path.exists(real_root):
                await self._send_error(send, 404, "Source path not found")
                return

            chunk_size = self._flask_app.config.get('ZIPSTREAM_CHUNK_SIZE', 65536)
            compression_level = self._flask_app.config.get('ZIPSTREAM_COMPRESSION_LEVEL', 0)
            enable_zip64 = self._flask_app.config.get('ZIPSTREAM_ENABLE_ZIP64', True)

            if download_request.file_location:
                base_name = os.path.basename(download_request.file_location)
                filename = f"{base_name}.zip" if not base_name.lower().endswith('.zip') else base_name
            else:
                game = download_request.game
                filename = f"{game.name}.zip" if game else "download.zip"

            print(f"Starting zipstream download: {filename}")

            async_generator, headers = async_generate_zipstream_response(
                real_root, filename, chunk_size, compression_level, enable_zip64,
                source_is_resolved=True, excluded_folders=excluded_folders,
            )

            started = True
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            })

            async for chunk in async_generator:
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                })

            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            })

            print(f"Completed zipstream download: {filename}")

        except Exception as e:
            error_filename = locals().get('filename', 'unknown')
            print(f"Error streaming ZIP {error_filename}: {str(e)}")
            if started:
                # A member failed (or vanished, or was swapped for a link) after
                # the archive was already on its way. Finishing the body here
                # would give the client a corrupt zip with a clean 200; raising
                # drops the connection, so the download shows as incomplete.
                log_system_event(
                    f"ZIP download of {error_filename} ended early: the client closed the connection"
                    if isinstance(e, _CLIENT_GONE) else f"ZIP download aborted mid-stream: {error_filename}",
                    event_type='download',
                    event_level='information' if isinstance(e, _CLIENT_GONE) else 'error',
                )
                raise
            await self._send_error(send, 500, "Error streaming ZIP file")

    async def _send_error(self, send, status_code, message, *, code=None, hint=None):
        """Send an HTTP error response (JSON). Optional code/hint for ROM extract failures."""
        payload = {"error": message}
        if code:
            payload["code"] = code
        if hint:
            payload["hint"] = hint
        response_body = json.dumps(payload).encode()

        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(response_body)).encode()),
            ],
        })

        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False,
        })

    async def _handle_lifespan(self, receive, send):
        """Handle startup and shutdown until the ASGI server finishes its cycle."""
        while True:
            message = await receive()

            if message["type"] == "lifespan.startup":
                try:
                    from oneirodex.utils.shutdown import begin_lifespan

                    begin_lifespan()
                    # Eager-init Flask so the first browser burst does not race bridge setup.
                    await self._ensure_flask()

                    # Background schedulers live here now, not in create_app().
                    # Wrapped so a scheduler that throws on start can never wedge
                    # lifespan and take the whole server down with it.
                    try:
                        from oneirodex.background import WorkersStillRunning, start_background_workers

                        start_background_workers(self._flask_app)
                    except WorkersStillRunning:
                        raise
                    except Exception as e:
                        print(f"Background workers failed to start: {e}")

                    await send({"type": "lifespan.startup.complete"})
                except Exception as e:
                    print(f"Startup failed: {e}")
                    await send({"type": "lifespan.startup.failed", "message": "Startup failed"})
                    return

            elif message["type"] == "lifespan.shutdown":
                try:
                    from oneirodex.background import stop_background_workers
                    from oneirodex.utils.shutdown import request_shutdown

                    request_shutdown()
                    stop_background_workers()
                    if self._native_sqlalchemy_engine is not None:
                        self._native_sqlalchemy_engine.dispose()
                        self._native_sqlalchemy_engine = None
                    print("🛑 ASGI lifespan shutdown initiated")
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as e:
                    print(f"Shutdown failed: {e}")
                    await send({"type": "lifespan.shutdown.failed", "message": "Shutdown failed"})
                return


def _configure_process_logging():
    """Install the app's logging config for the served process.

    ``create_app()`` used to do this, but the served runtime never builds the
    Flask app, so ONEIRODEX_LOG_LEVEL / ONEIRODEX_LOG_JSON had no effect and
    INFO records went nowhere. Skipped under pytest, whose log capture owns
    the root logger there.
    """
    import sys

    if 'pytest' in sys.modules:
        return
    from oneirodex.utils.logging_setup import configure_logging

    configure_logging()


_configure_process_logging()
asgi_app = LazyASGIApp()
