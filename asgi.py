"""ASGI runtime for Oneirodex.

FastAPI owns application route dispatch. Flask still initializes the shared
configuration, extension registry, and mapped models during this migration;
the WSGI fallback has been retired after the legacy method/path inventory
reached full native coverage.
"""

from __future__ import annotations

from oneirodex.runtime_native import (
    is_admin_redirect_path,
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
import uuid
from pathlib import Path
from importlib import import_module

import aiofiles
from werkzeug.exceptions import RequestedRangeNotSatisfiable
from werkzeug.utils import secure_filename, send_file as werkzeug_send_file

from sqlalchemy import select


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
    from starlette.responses import JSONResponse, Response
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


def _is_native_library_api_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 3 and parts[:2] == ['api', 'library'] and bool(parts[2])
    ) or (
        len(parts) == 4 and parts[:2] == ['api', 'library']
        and bool(parts[2]) and parts[3] == 'watch'
    ) or (
        len(parts) == 4 and parts[:3] == ['api', 'admin', 'libraries']
        and bool(parts[3]) and parts[3] != 'batch'
    )


def _is_native_library_tools_path(path: str) -> bool:
    return path in {
        '/api/library_tools/manual_identify/preview',
        '/api/library_tools/manual_identify/list',
        '/api/library_tools/propose_leaf_libraries',
        '/api/library_tools/import_leaf_libraries/preview',
        '/api/library_tools/proposals',
        '/api/library_tools/proposals/scan_roots',
        '/api/library_tools/doctor/dry_run',
        '/api/library_tools/rename/preview',
        '/api/library_tools/proposals/approve',
        '/api/library_tools/doctor/write_proposals',
        '/api/library_tools/link_existing_game',
        '/api/library_tools/rename/apply',
        '/api/library_tools/doctor/apply_renames',
        '/api/library_tools/backfill_steam_metadata',
        '/api/library_tools/check_freshness',
    }


def _is_native_library_admin_mutation_path(path: str) -> bool:
    return path in {
        '/api/admin/libraries',
        '/api/admin/libraries/scan',
        '/api/admin/libraries/refresh_all',
        '/api/admin/libraries/batch/scan',
        '/api/admin/libraries/batch/delete',
    }


def _is_native_support_reads_path(path: str) -> bool:
    if path == '/api/support/tickets':
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4 and parts[:3] == ['api', 'support', 'tickets']
        and parts[3].isdigit()
    )


def _is_native_theme_fonts_read_path(path: str) -> bool:
    return path == '/api/theme/fonts'


def _is_native_admin_theme_font_path(path: str, method: str) -> bool:
    return (
        (path == '/admin/api/theme/fonts' and method == 'POST')
        or (path.startswith('/admin/api/theme/fonts/') and method == 'DELETE')
    )


def _is_native_admin_art_studio_download_path(path: str, method: str) -> bool:
    return path.startswith('/admin/api/art-studio/download/') and method == 'GET'


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


def _is_native_library_delete_form_path(path: str, method: str) -> bool:
    parts = path.strip('/').split('/')
    return method == 'POST' and len(parts) == 2 and parts[0] == 'delete_full_library' and bool(parts[1])


def _is_native_game_delete_path(path: str, method: str) -> bool:
    if path in {'/delete_folder', '/delete_full_game', '/delete_image'}:
        return method == 'POST'
    parts = path.strip('/').split('/')
    return method == 'POST' and len(parts) == 2 and parts[0] == 'delete_game' and bool(parts[1])


def _is_native_unmatched_compat_mutation_path(path: str, method: str) -> bool:
    if method != 'POST':
        return False
    if path in {'/delete_all_unmatched_folders', '/update_unmatched_folder_status'}:
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 2 and parts[0] in {
        'clear_unmatched_entry', 'toggle_ignore_status',
    } and bool(parts[1])


def _is_native_admin_delete_image_path(path: str, method: str) -> bool:
    value = path.removeprefix('/admin/api/delete_image/')
    return method == 'DELETE' and bool(value) and value.isdigit()


def _is_native_provider_catalog_path(path: str) -> bool:
    return path in {
        '/api/providers', '/api/patch-catalog/providers',
        '/api/patch-catalog/search', '/api/patch-catalog/attach',
    }


def _is_native_integrations_inventory_path(path: str) -> bool:
    return path == '/api/admin/integrations/inventory'


def _is_native_integration_settings_path(path: str) -> bool:
    return path in {'/api/admin/integrations/oidc', '/api/admin/integrations/community', '/admin/integrations/oidc/save', '/admin/integrations/community'}


def _is_native_artwork_apply_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5 and parts[:2] == ['api', 'games']
        and bool(parts[2]) and parts[3:] == ['artwork', 'steamgriddb']
    )


def _is_native_admin_scan_filters_path(path: str) -> bool:
    if path == '/api/admin/scan-filters':
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['api', 'admin', 'scan-filters'] and parts[3].isdigit()


def _is_native_admin_discovery_sections_path(path: str) -> bool:
    if path in {
        '/admin/api/discovery_sections',
        '/admin/api/discovery_sections/order',
        '/admin/api/discovery_sections/visibility',
    }:
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4
        and parts[:3] == ['admin', 'api', 'discovery_sections']
        and parts[3].isdigit()
    ) or (
        len(parts) == 5
        and parts[:3] == ['admin', 'api', 'discovery_sections']
        and parts[3].isdigit()
        and parts[4] in {'schedule', 'pin'}
    )


def _is_native_admin_invites_path(path: str) -> bool:
    return path in {'/admin/api/invites', '/admin/api/invites/quota', '/admin/manage_invites'}


def _is_native_admin_users_read_path(path: str) -> bool:
    if path == '/admin/api/users':
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['admin', 'api', 'user'] and parts[3].isdigit()


def _is_native_admin_user_create_path(path: str) -> bool:
    return path == '/admin/api/user/0'


def _is_native_admin_user_mutation_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4 and parts[:3] == ['admin', 'api', 'user']
        and parts[3].isdigit() and int(parts[3]) > 0
    )


def _is_native_admin_whitelist_path(path: str) -> bool:
    if path in {'/admin/api/whitelist', '/admin/whitelist'}:
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 3 and parts[:2] == ['admin', 'whitelist'] and parts[2].isdigit()


def _is_native_admin_plugin_path(path: str) -> bool:
    if path == '/api/plugins':
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 3 and parts[:2] == ['api', 'plugins'] and bool(parts[2])


def _is_native_admin_newsletter_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return path == '/api/admin/newsletters' or (
        len(parts) == 4 and parts[:3] == ['api', 'admin', 'newsletters']
        and parts[3].isdigit()
    )


def _is_native_auth_confirmation_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['api', 'auth', 'confirm'] and bool(parts[3])


def _is_native_auth_page_path(path: str) -> bool:
    if path in {'/login', '/register', '/reset_password_request'}:
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 2 and parts[0] == 'confirm' and bool(parts[1])
    ) or (
        len(parts) == 2 and parts[0] == 'reset_password' and bool(parts[1])
    )


def _is_native_setup_page_path(path: str) -> bool:
    return path in {
        '/setup', '/setup/smtp', '/setup/features', '/setup/igdb',
        '/setup/integrations', '/setup/library',
    }


def _is_native_password_reset_confirm_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['api', 'auth', 'password-reset'] and bool(parts[3])


def _is_native_invite_delete_path(path: str) -> bool:
    return re.fullmatch(r'/delete_invite/[^/]+', path) is not None


def _is_native_download_request_reads_path(path: str) -> bool:
    if path in {'/api/my_downloads', '/api/admin/download-requests'}:
        return True
    parts = path.strip('/').split('/')
    return (
        (len(parts) == 2 and parts[0] == 'check_download_status')
        or (len(parts) == 2 and parts[0] == 'delete_download' and parts[1].isdigit())
        or (len(parts) == 2 and parts[0] == 'delete_download_request' and parts[1].isdigit())
        or (len(parts) == 3 and parts[:2] == ['api', 'delete_download'] and parts[2].isdigit())
    )


def _is_native_manual_identify_read_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        path == '/api/admin/manual-identify/options'
        or (len(parts) == 4 and parts[:3] == ['api', 'admin', 'manual-identify'])
    )


def _is_native_manual_identify_mutation_path(path: str, method: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        path == '/api/admin/manual-identify' and method == 'POST'
    ) or (
        len(parts) == 4
        and parts[:3] == ['api', 'admin', 'manual-identify']
        and method == 'PUT'
    )


def _is_native_retroachievements_settings_path(path: str) -> bool:
    if path in {
        '/api/admin/integrations/retroachievements',
        '/api/retroachievements/status',
        '/api/retroachievements/match',
        '/api/me/retroachievements',
    }:
        return True
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:2] == ['api', 'games'] and parts[3] == 'achievements'


def _is_native_admin_policy_settings_path(path: str) -> bool:
    return path in {'/api/admin/remote-play/config', '/api/admin/scan-match/config'}


def _is_native_launcher_import_read_path(path: str) -> bool:
    return path == '/api/imports/launchers'


def _is_native_download_mutation_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (path.startswith('/download_game/') and len(parts) == 2 and bool(parts[1])) or (
        path.startswith('/download_other/') and len(parts) == 4 and all(parts[1:])
    ) or (
        len(parts) == 5 and parts[:2] == ['api', 'games']
        and parts[2] and parts[3:] == ['versions', 'cleanup_orphans']
    ) or (
        len(parts) == 4 and parts[:3] == ['api', 'downloads', 'games'] and parts[3]
    )


def _is_native_support_mutation_path(path: str) -> bool:
    if path == '/api/support/tickets':
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5 and parts[:3] == ['api', 'support', 'tickets']
        and parts[3].isdigit() and parts[4] == 'resolve'
    )


def _is_native_launcher_import_mutation_path(path: str) -> bool:
    return path in {'/api/imports/playnite', '/api/imports/launcher'}


def _is_native_chat_messages_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'channels']
        and parts[3].isdigit()
        and parts[4] == 'messages'
    )


def _is_native_chat_attachment_upload_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'channels']
        and parts[3].isdigit()
        and parts[4] == 'attachments'
    )


def _is_native_layout_preset_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:4] == ['api', 'layouts', 'detail', 'presets']
        and parts[4].isdigit()
    )


def _is_native_chat_mute_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'channels']
        and parts[3].isdigit()
        and parts[4] in ('mute', 'archive', 'leave')
    )


def _is_native_chat_reaction_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'messages']
        and parts[3].isdigit()
        and parts[4] == 'reactions'
    )


def _is_native_chat_space_read_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'spaces']
        and parts[3].isdigit()
        and parts[4] in ('members', 'invites')
    )


def _is_native_chat_space_member_delete_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 6
        and parts[:3] == ['api', 'chat', 'spaces']
        and parts[3].isdigit()
        and parts[4] == 'members'
        and parts[5].isdigit()
    )


def _is_native_chat_space_channel_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'chat', 'spaces']
        and parts[3].isdigit()
        and parts[4] == 'channels'
    )


def _is_native_chat_space_invite_revoke_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 6
        and parts[:4] == ['api', 'chat', 'spaces', 'invites']
        and parts[4].isdigit()
        and parts[5] == 'revoke'
    )


def _is_native_chat_emoji_delete_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['api', 'chat', 'emoji'] and bool(parts[3])


def _is_native_chat_voice_room_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 7
        and parts[:3] == ['api', 'chat', 'spaces']
        and parts[3].isdigit()
        and parts[4] == 'voice'
        and parts[5].isdigit()
        and parts[6] == 'room'
    )


def _is_native_game_read_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4
        and parts[0:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3] in {
            'details', 'more_from', 'editions', 'versions', 'freshness', 'assists',
            'input_family',
        }
    ) or (
        len(parts) == 5
        and parts[0:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3:] == ['freshness', 'check']
    )


def _is_native_playtime_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    if parts in (['api', 'playtime', 'me'], ['api', 'playtime', 'sessions']):
        return True
    if (
        len(parts) == 4 and parts[:3] == ['api', 'playtime', 'share']
        and parts[3].endswith('.svg') and len(parts[3]) > 4
    ):
        return True
    if len(parts) == 4 and parts[:3] == ['api', 'playtime', 'games'] and parts[3]:
        return True
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'playtime', 'sessions']
        and parts[3].isdigit()
        and parts[4] in {'heartbeat', 'stop'}
    )


def _is_native_related_media_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4
        and parts[:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3] == 'related_media'
    ) or (
        len(parts) == 5
        and parts[:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3] == 'related_media'
        and parts[4].isdigit()
    )


def _is_native_game_asset_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 3
        and parts[0] == 'api'
        and parts[1] in {'game_screenshots', 'game_images'}
        and bool(parts[2])
    )


def _is_native_member_game_state_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 3
        and parts[0] == 'api'
        and parts[1] in {
            'check_favorite', 'toggle_favorite', 'get_game_status', 'set_game_status',
        }
        and bool(parts[2])
    )


def _is_native_member_profile_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    if len(parts) == 4:
        return parts[:2] == ['api', 'users'] and parts[2].isdigit() and parts[3] == 'profile'
    return (
        len(parts) == 5
        and parts[:2] == ['api', 'users']
        and parts[2].isdigit()
        and parts[3] == 'compare'
        and parts[4].isdigit()
    )


def _is_native_vr_game_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return len(parts) == 4 and parts[:3] == ['api', 'vr', 'games'] and bool(parts[3])


def _is_native_vr_profile_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4
        and parts[:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3] in {'vr_profiles', 'vr_compat'}
    ) or (
        len(parts) == 5
        and parts[:2] == ['api', 'games']
        and bool(parts[2])
        and parts[3] == 'vr_profiles'
        and bool(parts[4])
    )


def _is_native_saved_filter_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4
        and parts[:3] == ['api', 'filters', 'saved']
        and parts[3].isdigit()
    )


def _is_native_ownership_candidate_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'ownership', 'titles']
        and parts[3].isdigit()
        and parts[4] == 'candidates'
    )


def _is_native_ownership_decision_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'ownership', 'titles']
        and parts[3].isdigit()
        and parts[4] == 'match'
    ) or (
        len(parts) == 6
        and parts[:3] == ['api', 'ownership', 'titles']
        and parts[3].isdigit()
        and parts[4:] == ['match', 'undo']
    )


def _is_native_ownership_cancel_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:2] == ['api', 'ownership']
        and bool(parts[2])
        and parts[3:] == ['sync', 'cancel']
    )


def _is_native_ownership_action_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 3
        and parts[:2] == ['api', 'ownership']
        and bool(parts[2])
        and parts[2] != 'sync-all'
    ) or (
        len(parts) == 4
        and parts[:2] == ['api', 'ownership']
        and bool(parts[2])
        and parts[3] in {'sync', 'csv'}
    ) or path == '/api/ownership/sync-all'


def _is_native_game_server_path(path: str) -> bool:
    if path in ('/api/game-servers', '/api/game-servers/acl-check'):
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 3
        and parts[:2] == ['api', 'game-servers']
        and bool(parts[2])
    ) or (
        len(parts) == 4
        and parts[:2] == ['api', 'game-servers']
        and bool(parts[2])
        and parts[3] == 'status'
    )


def _is_native_admin_ownership_sync_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 7
        and parts[:3] == ['api', 'admin', 'ownership']
        and parts[3] == 'connections'
        and parts[4].isdigit()
        and bool(parts[5])
        and parts[6] in {'sync', 'cancel'}
    )


def _is_native_emulator_mutation_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    if len(parts) == 3 and parts[:2] == ['api', 'emulator-bios']:
        return parts[2] in {'scan', 'install'}
    if path == '/api/emulator-bios':
        return True
    if len(parts) < 4 or parts[:2] != ['api', 'games'] or not parts[2]:
        return False
    if len(parts) == 4 and parts[3] in {'cheats', 'saves', 'pc_cheats'}:
        return True
    return (
        len(parts) >= 5
        and parts[3] in {'cheats', 'saves', 'pc_cheats'}
        and bool('/'.join(parts[4:]))
        and (parts[3] != 'pc_cheats' or len(parts) == 5 and parts[4].isdigit())
    )


def _is_native_game_mods_path(path: str) -> bool:
    if path == '/api/mods/summary':
        return True
    parts = path.strip('/').split('/')
    if len(parts) < 4 or parts[:2] != ['api', 'games'] or not parts[2] or parts[3] != 'mods':
        return False
    if len(parts) == 4:
        return True
    if len(parts) == 5:
        return parts[4] in {'catalog', 'profiles', 'pack'} or bool(parts[4])
    if len(parts) == 6:
        return parts[4] == 'profiles' and bool(parts[5])
    return len(parts) == 7 and parts[4] == 'profiles' and bool(parts[5]) and parts[6] in {'activate', 'export'}


def _is_native_unmatched_mutation_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    if len(parts) != 4 or parts[:2] != ['api', 'unmatched_folders']:
        return False
    if parts[2] == 'batch':
        return parts[3] in {'clear', 'mark_kind', 'fix', 'amend'}
    return bool(parts[2]) and parts[3] in {
        'name', 'fix', 'mark_kind', 'retry_match', 'place_update',
    }


def _is_native_unmatched_feedback_path(path: str) -> bool:
    if path in {
        '/api/unmatched_folders/reclassify_duplicates',
        '/api/unmatched_folders/backfill_suggested_kind',
        '/api/unmatched/bad_match_reasons',
    }:
        return True
    parts = path.strip('/').split('/')
    return (
        len(parts) == 4 and parts[:2] == ['api', 'unmatched']
        and bool(parts[2]) and parts[3] == 'bad_match'
    )


def _is_native_emulator_platform_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return len(parts) == 3 and parts[:2] == ['api', 'emulators'] and bool(parts[2])


def _is_native_file_type_path(path: str) -> bool:
    return path in ('/api/file_types/allowed', '/api/file_types/ignored')


def _is_native_free_games_claim_path(path: str) -> bool:
    parts = path.strip('/').split('/')
    return (
        len(parts) == 5
        and parts[:3] == ['api', 'news', 'free-games']
        and parts[3].isdigit()
        and parts[4] == 'claim-assist'
    )


class LazyASGIApp:
    def __init__(self):
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
            from oneirodex.runtime_native.db_session import native_engine_session_scope
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
            from oneirodex.runtime_native.locale import mount_locale_routes
            from oneirodex.runtime_native.account_stock_avatar import mount_account_stock_avatar_routes
            from oneirodex.runtime_native.account_avatar_upload import mount_account_avatar_upload_routes
            from oneirodex.runtime_native.account_password import mount_account_password_routes
            from oneirodex.runtime_native.release_calendar import mount_release_calendar_routes
            from oneirodex.runtime_native.account_tokens import mount_account_tokens_routes
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
            from oneirodex.runtime_native.legacy_manual_identify_forms import mount_legacy_manual_identify_routes
            from oneirodex.runtime_native.retroachievements_settings import mount_retroachievements_settings_routes
            from oneirodex.runtime_native.admin_policy_settings import mount_admin_policy_settings_routes
            from oneirodex.runtime_native.admin_attract_mode import mount_admin_attract_mode_routes
            from oneirodex.runtime_native.admin_features import mount_admin_features_routes
            from oneirodex.runtime_native.admin_scan_filters import mount_admin_scan_filters_routes
            from oneirodex.runtime_native.legacy_scan_forms import mount_legacy_scan_form_routes
            from oneirodex.runtime_native.legacy_scan_management import mount_legacy_scan_management_routes
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
            mount_auth_logout_routes(self._native_read_api_app, self._flask_app)
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
            mount_legacy_manual_identify_routes(
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
            mount_legacy_scan_form_routes(
                self._native_read_api_app,
                self._flask_app,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=manager,
                database_scope=lambda app: self._native_database_scope(app),
            )
            mount_legacy_scan_management_routes(
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

            if path == '/awake' and scope.get('method') in ('GET', 'HEAD'):
                await self._ensure_native_database()
                await self._handle_readiness(scope, send)
                return

            if path == '/manifest.webmanifest' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_app_manifest(scope, send)
                return

            if path == '/offline' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_offline(scope, send)
                return

            if path in ('/sw.js', '/vr/sw.js') and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_service_worker(scope, send, path)
                return

            if path == '/favicon.ico' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_favicon(scope, send)
                return

            if path == '/api/emulator/installed-cores.js' and scope.get('method') in ('GET', 'HEAD'):
                await self._handle_installed_cores(scope, send)
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
                empty_admin_mutation_csrf_error,
                inspect_multipart_csrf_body,
                inspect_urlencoded_csrf_body,
                native_route_matches,
            )

            csrf_error = (
                empty_admin_mutation_csrf_error(scope, self._flask_app.config)
                if native_route_matches(self._native_read_api_app, scope)
                else None
            )
            if (
                csrf_error is None
                and (path == '/admin' or path.startswith('/admin/'))
                and scope.get('method', '').upper() in {'POST', 'PUT', 'PATCH', 'DELETE'}
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
                and path == '/link_existing_game'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/scan_manual_folder'
                and scope.get('method') == 'POST'
            ):
                await self._native_read_api_app(scope, receive, send)
                return

            if (
                self._native_read_api_app is not None
                and path == '/scan_management'
                and scope.get('method') == 'POST'
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

            if (
                self._native_read_api_app is not None
                and (
                    path in self._native_read_api_routes
                    or (path.startswith('/play_game/') and scope.get('method') in ('GET', 'HEAD'))
                    or (path.startswith('/delete_filter/') and scope.get('method') in ('GET', 'HEAD', 'POST'))
                    or (path == '/dev/styleguide' and scope.get('method') in ('GET', 'HEAD'))
                    or (
                        path in {'/settings_profile_view', '/settings_password', '/settings_panel'}
                        and scope.get('method') in ('GET', 'HEAD')
                    )
                    or _is_native_library_api_path(path)
                    or _is_native_admin_newsletter_path(path)
                    or _is_native_auth_confirmation_path(path)
                    or (
                        _is_native_auth_page_path(path)
                    )
                    or (
                        _is_native_setup_page_path(path)
                    )
                    or path == '/user/invites'
                    or _is_native_invite_delete_path(path)
                    or (
                        path in {
                            '/setup/submit', '/setup/smtp', '/setup/features',
                            '/setup/igdb', '/setup/integrations', '/setup/library',
                        }
                        and (
                            scope.get('method') == 'POST'
                            or (
                                scope.get('method') in ('GET', 'HEAD')
                            )
                        )
                    )
                    or (is_admin_redirect_path(path)
                        and scope.get('method') in ('GET', 'HEAD'))
                    or _is_native_password_reset_confirm_path(path)
                    or _is_native_chat_messages_path(path)
                    or _is_native_chat_attachment_upload_path(path)
                    or _is_native_chat_mute_path(path)
                    or _is_native_chat_reaction_path(path)
                    or _is_native_chat_space_read_path(path)
                    or _is_native_chat_space_member_delete_path(path)
                    or _is_native_chat_space_channel_path(path)
                    or _is_native_chat_space_invite_revoke_path(path)
                    or _is_native_chat_emoji_delete_path(path)
                    or _is_native_chat_voice_room_path(path)
                    or _is_native_layout_preset_path(path)
                    or _is_native_game_read_path(path)
                    or _is_native_playtime_path(path)
                    or _is_native_related_media_path(path)
                    or _is_native_game_asset_path(path)
                    or _is_native_member_game_state_path(path)
                    or _is_native_member_profile_path(path)
                    or _is_native_vr_game_path(path)
                    or _is_native_vr_profile_path(path)
                    or _is_native_saved_filter_path(path)
                    or _is_native_ownership_candidate_path(path)
                    or _is_native_ownership_decision_path(path)
                    or _is_native_ownership_cancel_path(path)
                    or _is_native_ownership_action_path(path)
                    or _is_native_game_server_path(path)
                    or _is_native_emulator_mutation_path(path)
                    or _is_native_game_mods_path(path)
                    or _is_native_unmatched_mutation_path(path)
                    or _is_native_unmatched_feedback_path(path)
                    or _is_native_emulator_platform_path(path)
                    or _is_native_file_type_path(path)
                    or _is_native_library_tools_path(path)
                    or _is_native_library_admin_mutation_path(path)
                    or _is_native_support_reads_path(path)
                    or _is_native_theme_fonts_read_path(path)
                    or _is_native_provider_catalog_path(path)
                    or _is_native_integrations_inventory_path(path)
                    or _is_native_integration_settings_path(path)
                    or (
                        path in {'/admin/integrations/igdb/save', '/admin/integrations/igdb/test'}
                        and scope.get('method') == 'POST'
                    )
                    or _is_native_download_request_reads_path(path)
                    or _is_native_manual_identify_read_path(path)
                    or _is_native_manual_identify_mutation_path(path, scope.get('method', ''))
                    or _is_native_retroachievements_settings_path(path)
                    or _is_native_admin_policy_settings_path(path)
                    or path == '/api/admin/attract-mode/settings'
                    or _is_native_admin_scan_filters_path(path)
                    or _is_native_admin_discovery_sections_path(path)
                    or (
                        _is_native_admin_invites_path(path)
                        and (path != '/admin/manage_invites' or scope.get('method') == 'POST')
                    )
                    or (
                        _is_native_admin_whitelist_path(path)
                        and (
                            (path == '/admin/api/whitelist' and scope.get('method') in ('GET', 'HEAD', 'POST'))
                            or (path == '/admin/whitelist' and scope.get('method') == 'POST')
                            or (path != '/admin/api/whitelist' and scope.get('method') == 'DELETE')
                        )
                    )
                    or (
                        _is_native_admin_users_read_path(path)
                        and scope.get('method') in ('GET', 'HEAD')
                    )
                    or (
                        _is_native_admin_user_create_path(path)
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        _is_native_admin_user_mutation_path(path)
                        and scope.get('method') in ('PUT', 'DELETE')
                    )
                    or _is_native_admin_plugin_path(path)
                    or (
                        path == '/admin/api/system_logs/clear'
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/admin/clear_permission_errors'
                        and scope.get('method') == 'POST'
                    )
                    or _is_native_admin_theme_font_path(path, scope.get('method', ''))
                    or _is_native_admin_art_studio_download_path(path, scope.get('method', ''))
                    or _is_native_image_refresh_progress_path(path, scope.get('method', ''))
                    or _is_native_library_delete_progress_path(path, scope.get('method', ''))
                    or _is_native_library_delete_sse_path(path, scope.get('method', ''))
                    or _is_native_scan_job_mutation_path(path, scope.get('method', ''))
                    or _is_native_library_delete_form_path(path, scope.get('method', ''))
                    or _is_native_game_delete_path(path, scope.get('method', ''))
                    or _is_native_unmatched_compat_mutation_path(path, scope.get('method', ''))
                    or _is_native_admin_delete_image_path(path, scope.get('method', ''))
                    or path in {
                        '/api/admin/features/settings',
                        '/api/admin/features/challenge',
                        '/api/admin/features/challenge/test',
                    }
                    or (path == '/admin/features' and scope.get('method') == 'POST')
                    or (path in {'/admin/settings', '/admin/new_server_settings'} and scope.get('method') == 'POST')
                    or (path in {'/admin/igdb_settings', '/admin/test_igdb', '/admin/integrations/igdb/save', '/admin/integrations/igdb/test'} and scope.get('method') == 'POST')
                    or _is_native_launcher_import_read_path(path)
                    or _is_native_download_mutation_path(path)
                    or _is_native_support_mutation_path(path)
                    or _is_native_launcher_import_mutation_path(path)
                    or _is_native_artwork_apply_path(path)
                    or path == '/api/admin/ownership/connections'
                    or _is_native_admin_ownership_sync_path(path)
                    or path in {
                        '/api/providers/steamgriddb/search',
                        '/api/providers/igdb/search',
                        '/api/providers/giantbomb/search',
                        '/api/providers/pcgamingwiki/search',
                        '/api/providers/meta_quest/search',
                        '/admin/api/ops/logs',
                        '/admin/api/ops/system',
                        '/admin/api/ops/summary',
                        '/admin/api/ops/devices',
                        '/admin/api/library/health',
                    }
                    or path.startswith('/api/health/games/')
                    or path.startswith('/api/discover/rows/')
                    or path.startswith('/api/discover/zones/')
                    or path.startswith('/api/discover/hubs/genre/')
                    or path.startswith('/api/account/invites/')
                    or path.startswith('/api/tokens/')
                    or path.startswith('/api/client/commands/')
                    or path.startswith('/api/collections/')
                    or path.startswith('/api/social/friends/')
                    or path.startswith('/api/requests/')
                    or path.startswith('/api/admin/chat-emoji/')
                    or path.startswith('/api/chat/attachments/')
                    or path.startswith('/api/admin/themes/')
                    or path == '/admin/themes/reset'
                    or (
                        path == '/admin/themes'
                        and scope.get('method') == 'POST'
                    )
                    or path.startswith('/admin/themes/delete/')
                    or path.startswith('/api/admin/reference-sets/')
                    or (
                        path.startswith('/api/reference-sets/')
                        and path.rsplit('/', 1)[-1].isdigit()
                    )
                    or path.startswith('/api/arr/indexers/')
                    or path.startswith('/api/quality-profiles/')
                    or path.startswith('/api/hltb/refresh/')
                    or _is_native_free_games_claim_path(path)
                )
                and (
                    scope.get('method') in ('GET', 'HEAD')
                    or (
                        _is_native_library_api_path(path)
                        and path.endswith('/watch')
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        _is_native_library_api_path(path)
                        and path.startswith('/api/admin/libraries/')
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/reorder_libraries'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in (
                            '/api/storage/hardlink/preview',
                            '/api/storage/hardlink/apply',
                        )
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/malware-scan'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/library/preview-cropped-image'
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/rtc/token' and scope.get('method') == 'POST')
                    or (
                        _is_native_free_games_claim_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_password_reset_confirm_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/auth/login' and scope.get('method') == 'POST')
                    or (path == '/api/auth/register' and scope.get('method') == 'POST')
                    or (path == '/user/invites' and scope.get('method') == 'POST')
                    or (_is_native_invite_delete_path(path) and scope.get('method') == 'POST')
                    or path in {'/login', '/register', '/reset_password_request'}
                    and scope.get('method') == 'POST'
                    or (
                        _is_native_auth_page_path(path)
                        and path.startswith('/reset_password/')
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/setup/step' and scope.get('method') == 'POST')
                    or (
                        path in {
                            '/setup/submit', '/setup/smtp', '/setup/features',
                            '/setup/igdb', '/setup/integrations', '/setup/library',
                        }
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/libraries/batch/edit'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/account/invites'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/account/preferences'
                        and scope.get('method') == 'PUT'
                    )
                    or (path == '/api/locale' and scope.get('method') == 'POST')
                    or (
                        path == '/api/admin/loading-icon/config'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/attract-mode/user-override'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/integrations/metadata-providers'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        _is_native_integration_settings_path(path)
                        and scope.get('method') in ('PUT', 'POST')
                    )
                    or (
                        _is_native_download_request_reads_path(path)
                        and path.startswith('/api/delete_download/')
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        _is_native_retroachievements_settings_path(path)
                        and (
                            (path in {
                                '/api/admin/integrations/retroachievements',
                                '/api/me/retroachievements',
                            } and scope.get('method') == 'PUT')
                            or (path == '/api/retroachievements/match' and scope.get('method') == 'POST')
                        )
                    )
                    or (
                        _is_native_admin_policy_settings_path(path)
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/admin/attract-mode/settings'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        _is_native_admin_scan_filters_path(path)
                        and scope.get('method') in ('POST', 'DELETE')
                    )
                    or _is_native_admin_discovery_sections_path(path)
                    or (
                        _is_native_admin_invites_path(path)
                        and (path != '/admin/manage_invites' or scope.get('method') == 'POST')
                    )
                    or (
                        _is_native_admin_whitelist_path(path)
                        and (
                            (path == '/admin/api/whitelist' and scope.get('method') in ('GET', 'HEAD', 'POST'))
                            or (path == '/admin/whitelist' and scope.get('method') == 'POST')
                            or (path != '/admin/api/whitelist' and scope.get('method') == 'DELETE')
                        )
                    )
                    or (
                        path == '/admin/api/system_logs/clear'
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/admin/clear_permission_errors'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_admin_users_read_path(path)
                        and scope.get('method') in ('GET', 'HEAD')
                    )
                    or (
                        _is_native_admin_user_create_path(path)
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        _is_native_admin_user_mutation_path(path)
                        and scope.get('method') in ('PUT', 'DELETE')
                    )
                    or (
                        path in {
                            '/api/admin/features/settings',
                            '/api/admin/features/challenge',
                        }
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/admin/features/challenge/test'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_admin_ownership_sync_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_download_mutation_path(path)
                        and scope.get('method') in ('GET', 'HEAD', 'POST')
                    )
                    or (
                        _is_native_support_mutation_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_launcher_import_mutation_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_artwork_apply_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/patch-catalog/attach'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/igdb/settings'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/arr/config'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/discover/pins'
                        and scope.get('method') == 'PUT'
                    )
                    or (path == '/api/admin/themes' and scope.get('method') == 'POST')
                    or (
                        path in {'/admin/themes', '/admin/themes/reset'}
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/admin/themes/delete/')
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/admin/notify-bus/test' and scope.get('method') == 'POST')
                    or (path == '/api/chat/channels' and scope.get('method') == 'POST')
                    or (
                        path == '/api/emulator-profiles'
                        and scope.get('method') in ('POST', 'PUT')
                    )
                    or (
                        path == '/api/browser-player-settings'
                        and scope.get('method') in ('POST', 'PUT')
                    )
                    or (
                        _is_native_file_type_path(path)
                        and scope.get('method') in ('POST', 'PUT', 'DELETE')
                    )
                    or (path == '/api/chat/dm' and scope.get('method') == 'POST')
                    or (path == '/api/chat/emoji' and scope.get('method') == 'POST')
                    or (path == '/api/admin/chat-emoji' and scope.get('method') == 'POST')
                    or (
                        _is_native_chat_emoji_delete_path(path)
                        and scope.get('method') == 'DELETE'
                    )
                    or (path == '/api/chat/spaces' and scope.get('method') == 'POST')
                    or (
                        path in ('/api/layouts/detail', '/api/layouts/detail/mine')
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/layouts/detail/mine'
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/api/layouts/detail/presets'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_layout_preset_path(path)
                        and scope.get('method') == 'DELETE'
                    )
                    or (path == '/api/chat/spaces/join' and scope.get('method') == 'POST')
                    or (
                        _is_native_chat_space_read_path(path)
                        and path.endswith('/invites')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_chat_space_invite_revoke_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_chat_space_channel_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (_is_native_chat_mute_path(path) and scope.get('method') == 'POST')
                    or (_is_native_chat_messages_path(path) and scope.get('method') == 'POST')
                    or (
                        _is_native_chat_attachment_upload_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (_is_native_chat_reaction_path(path) and scope.get('method') == 'POST')
                    or (
                        _is_native_ownership_decision_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_ownership_cancel_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_ownership_action_path(path)
                        and scope.get('method') in {'POST', 'DELETE'}
                    )
                    or (
                        path == '/api/game-servers'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_game_server_path(path)
                        and path != '/api/game-servers'
                        and scope.get('method') in {'PUT', 'PATCH', 'DELETE'}
                    )
                    or (
                        _is_native_emulator_mutation_path(path)
                        and scope.get('method') in {'POST', 'DELETE'}
                    )
                    or (
                        _is_native_game_mods_path(path)
                        and scope.get('method') in {
                            'POST', 'PUT', 'PATCH', 'DELETE',
                        }
                    )
                    or (
                        _is_native_unmatched_mutation_path(path)
                        and scope.get('method') in {'POST', 'PATCH'}
                    )
                    or (
                        _is_native_unmatched_feedback_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in {
                            '/api/library_tools/manual_identify/list',
                            '/api/library_tools/propose_leaf_libraries',
                            '/api/library_tools/import_leaf_libraries/preview',
                            '/api/library_tools/proposals/scan_roots',
                            '/api/library_tools/doctor/dry_run',
                            '/api/library_tools/rename/preview',
                            '/api/library_tools/proposals/approve',
                            '/api/library_tools/doctor/write_proposals',
                            '/api/library_tools/link_existing_game',
                            '/api/library_tools/rename/apply',
                            '/api/library_tools/doctor/apply_renames',
                            '/api/library_tools/backfill_steam_metadata',
                            '/api/library_tools/check_freshness',
                        }
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_library_admin_mutation_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/newsletters'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/admin/newsletter'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.endswith('/members')
                        and _is_native_chat_space_read_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_chat_space_member_delete_path(path)
                        and scope.get('method') == 'DELETE'
                    )
                    or (path == '/api/ai/config' and scope.get('method') == 'PUT')
                    or (
                        path in ('/api/ai/triage', '/api/ai/doctor-notes', '/api/ai/apply-triage')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in (
                            '/api/admin/challenge-solver/config',
                            '/api/admin/ambient-lighting/config',
                        )
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path in (
                            '/api/admin/challenge-solver/test',
                            '/api/admin/ambient-lighting/test',
                        )
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/admin/themes/')
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/api/arr/module'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/quality-profiles'
                        and scope.get('method') in ('POST', 'PUT')
                    )
                    or (
                        path == '/api/quality-profiles/active'
                        and scope.get('method') in ('POST', 'PUT')
                    )
                    or (
                        path == '/api/quality-profiles/score'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/quality-profiles/')
                        and path.count('/') == 3
                        and path.rsplit('/', 1)[-1] not in ('active', 'score')
                        and scope.get('method') in ('PUT', 'PATCH', 'DELETE')
                    )
                    or (
                        path == '/api/admin/igdb/test'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/smtp/settings'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/admin/server-settings'
                        and scope.get('method') == 'PUT'
                    )
                    or (
                        path == '/api/admin/smtp/test'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in {'/admin/smtp_settings', '/admin/smtp_test'}
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/reference-sets'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/reference-sets'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in ('/api/reference-sets/rehash', '/api/reference-sets/repair-preview')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/reference-sets/')
                        and path.rsplit('/', 1)[-1].isdigit()
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path.startswith('/api/admin/reference-sets/')
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/api/arr/indexers'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/arr/download'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in ('/api/arr/hardlink/preview', '/api/arr/hardlink/apply')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/hltb/refresh/')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/hltb/bulk-refresh'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/arr/indexers/')
                        and scope.get('method') in ('PUT', 'PATCH', 'DELETE')
                    )
                    or (
                        path in ('/api/arr/indexers/bulk', '/api/arr/indexers/enable-presets')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/licensed-catalog/refresh'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/account/avatar/stock'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/account/avatar'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/settings_profile_edit'
                        and scope.get('method') in ('GET', 'HEAD', 'POST')
                    )
                    or (
                        path == '/api/account/password'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/settings_panel'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/settings_password'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/client/lifecycle'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/client/heartbeat'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/client/commands'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/announcements'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/collections'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/collections/')
                        and scope.get('method') in ('PATCH', 'DELETE', 'POST', 'PUT')
                    )
                    or (
                        path == '/api/requests'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/requests/')
                        and scope.get('method') in ('PATCH', 'DELETE')
                    )
                    or (path == '/api/social/friends' and scope.get('method') == 'POST')
                    or (
                        path == '/api/notifications/read'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/notifications/preferences'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path in ('/api/updates/wanted', '/api/updates/wanted/fulfill')
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/updates/scan' and scope.get('method') == 'POST')
                    or (path == '/api/acquire/download' and scope.get('method') == 'POST')
                    or (
                        path == '/api/events/publish_test'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/move_game_to_library'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/admin/freshness/refresh'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/social/friends/')
                        and scope.get('method') in ('POST', 'DELETE')
                    )
                    or (
                        path.startswith('/api/client/commands/')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path.startswith('/api/account/invites/')
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path == '/api/tokens'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_game_read_path(path)
                        and path.endswith('/input_family')
                        and scope.get('method') == 'PATCH'
                    )
                    or (
                        _is_native_game_read_path(path)
                        and path.endswith('/freshness/check')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_playtime_path(path)
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_related_media_path(path)
                        and len(path.strip('/').split('/')) == 4
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_game_read_path(path)
                        and path.endswith('/assists')
                        and scope.get('method') in ('POST', 'PUT')
                    )
                    or _is_native_manual_identify_mutation_path(path, scope.get('method', ''))
                    or (
                        _is_native_related_media_path(path)
                        and len(path.strip('/').split('/')) == 5
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        path in ('/api/filters/saved', '/api/filters/preview')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/games/batch/favorite'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/games/batch/status'
                        and scope.get('method') == 'POST'
                    )
                    or (
                        path == '/api/games/batch/wishlist'
                        and scope.get('method') == 'POST'
                    )
                    or (path == '/api/check_username' and scope.get('method') == 'POST')
                    or (
                        path.startswith('/api/admin/chat-emoji/')
                        and scope.get('method') == 'DELETE'
                    )
                    or (
                        _is_native_member_game_state_path(path)
                        and (
                            scope.get('method') in ('GET', 'HEAD')
                            or (
                                scope.get('method') == 'POST'
                                and path.split('/')[2] in {'toggle_favorite', 'set_game_status'}
                            )
                        )
                    )
                    or (
                        _is_native_vr_profile_path(path)
                        and scope.get('method') in ('PUT', 'DELETE', 'PATCH')
                    )
                    or (
                        path in ('/api/games/batch/freshness/check', '/api/games/batch/refresh_images')
                        and scope.get('method') == 'POST'
                    )
                    or (
                        _is_native_saved_filter_path(path)
                        and scope.get('method') in ('PUT', 'DELETE')
                    )
                    or (
                        path.startswith('/api/tokens/')
                        and scope.get('method') == 'DELETE'
                    )
                    or _is_native_image_refresh_progress_path(path, scope.get('method', ''))
                    or _is_native_library_delete_progress_path(path, scope.get('method', ''))
                    or _is_native_library_delete_sse_path(path, scope.get('method', ''))
                    or _is_native_scan_job_mutation_path(path, scope.get('method', ''))
                    or _is_native_library_delete_form_path(path, scope.get('method', ''))
                    or _is_native_game_delete_path(path, scope.get('method', ''))
                    or _is_native_unmatched_compat_mutation_path(path, scope.get('method', ''))
                )
            ):
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
            await self._native_read_api_app(scope, receive, send)

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
        payload = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n'
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
        from oneirodex.runtime_native.response_compat import flask_redirect_response
        from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

        await self._ensure_native_database()
        with self._native_database_scope():
            if should_redirect_to_setup():
                response = flask_redirect_response(
                    get_setup_redirect_url(), status_code=302,
                )
                for key, value in self._configured_security_headers().items():
                    response.headers.setdefault(key, value)
                if scope.get('method') == 'HEAD':
                    response.body = b''
                await response(scope, None, send)
                return
            settings = get_global_settings() or {}
        manifest = build_app_manifest(settings.get('site_name'))
        payload = json.dumps(
            manifest, separators=(',', ':'), ensure_ascii=False, sort_keys=True,
        ).encode('utf-8')
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

    async def _handle_offline(self, scope, send):
        """Serve the self-contained offline fallback without Flask request state."""
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
            max_age=3600,
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
        if payload.get('user_id') is None and not payload.get('game_uuid'):
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
            size = candidate.stat().st_size
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

            if os.path.isdir(file_path):
                await self._handle_streaming_download(send, download_request, file_path)
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
            await self._stream_file(send, handle, filename)

    async def _handle_rom_download(self, scope, receive, send, path):
        """Handle ROM file downloads for emulator"""
        from oneirodex.models import Game, User
        from oneirodex.utils.rom_archive import ArchiveRomError

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

            if not os.path.exists(game.full_disk_path):
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
            # Extraction output is request-scoped: retries and concurrent plays
            # cannot reuse partial files or accumulate unbounded cache contents.
            cache_dir = tempfile.mkdtemp(prefix=f'{game_uuid}-', dir=cache_root)
            try:
                platform_key = library_platform_key(game)
                try:
                    rom_path, filename = resolve_playable_rom_path(
                        game.full_disk_path,
                        cache_dir=cache_dir,
                        platform=platform_key,
                    )
                    target, root, root_is_resolved = _rom_location(rom_path, cache_dir, real_game, game_is_dir)
                    # Multi-track discs (.cue + .bin/.img/...) need every file in one
                    # response — WebRetro never gets a second chance to fetch companions.
                    bundled_path, bundled_name = bundle_playable_rom_zip(
                        target, cache_dir, root=root if root_is_resolved else None
                    )
                    if bundled_path != target:
                        target, root, root_is_resolved = bundled_path, cache_dir, False
                        filename = bundled_name
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
                shutil.rmtree(cache_dir, ignore_errors=True)

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
            from oneirodex.runtime_native.auth_resolver import load_active_user_id
            from oneirodex.runtime_native.request_auth import _lifetime_seconds
            from oneirodex.runtime_native.session_compat import load_session_cookie

            request_scope = {**scope, 'type': 'http'}
            request = Request(request_scope)
            config = self._flask_app.config
            session_data = load_session_cookie(
                request.cookies.get(str(config.get('SESSION_COOKIE_NAME') or 'session')),
                config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
            )
            user_id = session_data.get('_user_id')
            if user_id is None:
                return None

            find_user, _find_token, _commit_token_touch = _native_auth_backend(self._flask_app)
            with self._native_database_scope(self._flask_app):
                user = load_active_user_id(
                    str(user_id), find_user, allow_legacy_id=bool(config.get('TESTING')),
                )
                return user.id if user is not None else None

        except Exception as e:
            log_system_event(
                f"Error parsing signed session for download authorization: {type(e).__name__}",
                event_type='security',
                event_level='warning',
            )
            return None

    async def _stream_file(self, send, handle, filename):
        """Stream an open file that ``open_plain_file_within`` already vetted.

        The size is the descriptor's and so are the bytes, so what is announced
        is what is sent whatever happens to the path meanwhile. *handle* is
        closed here.
        """
        started = False
        try:
            with handle:
                size = os.fstat(handle.fileno()).st_size

                started = True
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": _file_headers(filename, size),
                })

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

    async def _handle_streaming_download(self, send, download_request, source_path):
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
                source_is_resolved=True,
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
                    # Eager-init Flask so the first browser burst does not race bridge setup.
                    await self._ensure_flask()

                    # Background schedulers live here now, not in create_app().
                    # Wrapped so a scheduler that throws on start can never wedge
                    # lifespan and take the whole server down with it.
                    try:
                        from oneirodex.background import start_background_workers

                        start_background_workers(self._flask_app)
                    except Exception as e:
                        print(f"Background workers failed to start: {e}")

                    await send({"type": "lifespan.startup.complete"})
                except Exception as e:
                    print(f"Startup failed: {e}")
                    await send({"type": "lifespan.startup.failed", "message": "Startup failed"})
                    return

            elif message["type"] == "lifespan.shutdown":
                try:
                    try:
                        from oneirodex.background import stop_background_workers

                        stop_background_workers()
                    except Exception as e:
                        print(f"Background workers failed to stop cleanly: {e}")

                    from oneirodex.utils.shutdown import request_shutdown

                    try:
                        request_shutdown()
                    finally:
                        if self._native_sqlalchemy_engine is not None:
                            self._native_sqlalchemy_engine.dispose()
                            self._native_sqlalchemy_engine = None
                    print("🛑 ASGI lifespan shutdown initiated")
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as e:
                    print(f"Shutdown failed: {e}")
                    await send({"type": "lifespan.shutdown.failed", "message": "Shutdown failed"})
                return


asgi_app = LazyASGIApp()
