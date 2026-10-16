"""Storage helpers (hardlink preview/apply + status honesty)."""

from __future__ import annotations

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, jsonify
from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.hardlinks import (
    apply_hardlink,
    build_storage_status,
    preview_hardlink,
)
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
from oneirodex.schemas.storage import HardlinkBody
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _helpers_enabled() -> bool:
    return str(current_app.config.get('ENABLE_HARDLINK_HELPERS', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def _apply_allowed() -> bool:
    return _helpers_enabled() and str(
        current_app.config.get('ALLOW_HARDLINK_APPLY', ''),
    ).lower() in ('1', 'true', 'yes', 'on')


def _games_path() -> str:
    return current_app.config.get('DATA_FOLDER_GAMES') or ''


def _paths_allowed(source: str, dest: str) -> tuple[bool, str | None]:
    bases = get_allowed_base_directories(current_app)
    ok_s, err_s = is_safe_path(source, bases)
    if not ok_s:
        return False, err_s or 'Unsafe source path'
    ok_d, err_d = is_safe_path(dest, bases)
    if not ok_d:
        return False, err_d or 'Unsafe destination path'
    return True, None


@apis_bp.route('/storage/status', methods=['GET'])
@login_required
@admin_required
def storage_status():
    """Admin Storage UI honesty: flags + games-path probes (RO-safe)."""
    helpers = _helpers_enabled()
    # allow_apply mirrors the apply gate (helpers AND ALLOW_HARDLINK_APPLY).
    allow = _apply_allowed()
    return jsonify(build_storage_status(
        helpers_enabled=helpers,
        allow_apply=allow,
        games_path=_games_path(),
    ))


@apis_bp.route('/storage/hardlink/preview', methods=['POST'])
@login_required
@admin_required
@validate_body(HardlinkBody)
def hardlink_preview(body: HardlinkBody):
    if not _helpers_enabled():
        return api_error('Hardlink helpers are disabled', code='forbidden')
    source = body.source
    dest = body.dest
    ok, err = _paths_allowed(source, dest)
    if not ok:
        return api_error(err, code='forbidden')
    # Deliberately not api_ok: preview_hardlink returns `ok: would_succeed` —
    # the answer to "would this hardlink work", not "did the request work".
    # api_ok stamps ok=True, which would turn every "no" into a "yes".
    return jsonify(preview_hardlink(source, dest))


@apis_bp.route('/storage/hardlink/apply', methods=['POST'])
@login_required
@admin_required
@validate_body(HardlinkBody)
def hardlink_apply(body: HardlinkBody):
    if not _apply_allowed():
        return api_error('Hardlink apply is disabled. Set ALLOW_HARDLINK_APPLY=true.', code='forbidden')
    source = body.source
    dest = body.dest
    ok, err = _paths_allowed(source, dest)
    if not ok:
        return api_error(err, code='forbidden')
    try:
        result = apply_hardlink(source, dest)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except OSError as exc:
        current_app.logger.warning('Hardlink operation failed (%s)', type(exc).__name__)
        return api_error('Hardlink operation failed', code='internal')
    try:
        log_system_event(
            f'Hardlink created: {result.get("source")} -> {result.get("dest")}',
            event_type='audit',
            event_level='information',
        )
    except Exception:
        pass
    return jsonify(result), 201
