# /oneirodex/routes_apis/download.py
import os
import re
from typing import Tuple

from flask import current_app, jsonify, request

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from oneirodex import db
from oneirodex.models import DownloadRequest, Game, GlobalSettings
from oneirodex.utils.api_tokens import require_api_scope
from oneirodex.utils.auth import admin_required
from oneirodex.utils.event_bus import publish_download_event
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.game_versions import (
    cleanup_orphan_versions,
    list_game_versions,
    resolve_version_file,
)
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.rbac import librarian_required
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
from oneirodex.utils.global_settings import global_settings_row

from . import apis_bp

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _resolve_zip_file_path(game: Game, file_location: str) -> str:
    """Pick a zip/file path for streaming from a game folder or file."""
    if not os.path.isdir(file_location):
        return file_location

    # Folder download of an update/extra path: stream the folder/file as-is.
    if os.path.normpath(file_location) != os.path.normpath(game.full_disk_path):
        return file_location

    settings = global_settings_row()
    files_in_directory = []
    for entry in os.listdir(file_location):
        full_path = os.path.join(file_location, entry)
        if os.path.isdir(full_path) and settings and (
            entry.lower() == settings.update_folder_name.lower()
            or entry.lower() == settings.extras_folder_name.lower()
        ):
            continue
        if os.path.isfile(full_path):
            files_in_directory.append(entry)

    significant_files = [
        entry
        for entry in files_in_directory
        if not entry.lower().endswith(('.nfo', '.sfv'))
        and entry.lower() not in ('file_id.diz', 'oneirodex.json')
    ]

    if len(significant_files) == 1:
        return os.path.join(file_location, significant_files[0])
    return file_location


def _create_or_get_download_request(
    game: Game,
    *,
    file_location: str,
    zip_file_path: str,
) -> DownloadRequest:
    existing_request = db.session.execute(
        select(DownloadRequest).filter_by(
            user_id=current_user.id,
            file_location=file_location,
        )
    ).scalars().first()
    if existing_request:
        return existing_request

    new_request = DownloadRequest(
        user_id=current_user.id,
        game_uuid=game.uuid,
        status='available',
        download_size=game.size if file_location == game.full_disk_path else 0,
        file_location=file_location,
        zip_file_path=zip_file_path,
    )
    db.session.add(new_request)
    if file_location == game.full_disk_path:
        game.times_downloaded += 1
    db.session.commit()

    try:
        publish_download_event(
            new_request.id,
            'available',
            game_uuid=game.uuid,
            game_name=game.name,
            user_id=new_request.user_id,  # streams send it to this member (and admins) only
        )
    except Exception:
        pass

    log_system_event(
        f"API download request created for game: {game.name}",
        event_type='game',
        event_level='information',
    )
    return new_request


def _downloadable_game(game_uuid: str):
    """Load a game the caller may download, or the response that refuses it.

    Three handlers opened with the same three guards — malformed uuid, missing
    game, no access. Returns ``(game, None)`` or ``(None, response)``.
    """
    if not _UUID_RE.match(game_uuid):
        return None, api_error('Invalid game UUID', code='bad_request')
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return None, api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return None, api_error('Access denied', code='forbidden')
    return game, None


@apis_bp.route('/games/<game_uuid>/versions', methods=['GET'])
@login_required
@require_api_scope('read:library')
def api_list_game_versions(game_uuid: str) -> Tuple[dict, int]:
    game, refusal = _downloadable_game(game_uuid)
    if refusal is not None:
        return refusal

    versions = list_game_versions(game)
    # Do not expose raw disk paths to clients
    public = [
        {
            'kind': v['kind'],
            'id': v['id'],
            'uuid': v['uuid'],
            'label': v['label'],
            'is_default': v['is_default'],
            'size': v.get('size'),
            'path_missing': bool(v.get('path_missing')),
            'downloadable': bool(v.get('downloadable')),
        }
        for v in versions
    ]
    return jsonify({'game_uuid': game_uuid, 'versions': public}), 200


@apis_bp.route('/games/<game_uuid>/versions/cleanup_orphans', methods=['POST'])
@login_required
@librarian_required
def api_cleanup_orphan_versions(game_uuid: str) -> Tuple[dict, int]:
    """Delete GameUpdate/GameExtra rows for this game whose files are gone."""
    game, refusal = _downloadable_game(game_uuid)
    if refusal is not None:
        return refusal

    try:
        result = cleanup_orphan_versions(game)
        log_system_event(
            f"Orphan version cleanup for {game.name}: "
            f"removed={len(result['removed'])} kept={len(result['kept'])}",
            event_type='game',
            event_level='information',
        )
        return api_ok(result)
    except Exception as exc:
        db.session.rollback()
        log_system_event(
            f'Error cleaning orphan versions for {game_uuid}: {exc}',
            event_type='game',
            event_level='error',
        )
        return api_error('Failed to clean orphan versions', code='internal')


@apis_bp.route('/downloads/games/<game_uuid>', methods=['POST'])
@login_required
@require_api_scope('write:download')
def api_initiate_game_download(game_uuid: str) -> Tuple[dict, int]:
    """Create or reuse a download request for companion clients."""
    game, refusal = _downloadable_game(game_uuid)
    if refusal is not None:
        return refusal

    payload = request.get_json(silent=True) or {}
    kind = (payload.get('kind') or request.args.get('kind') or 'base').strip().lower()
    version_uuid = (
        payload.get('version_uuid')
        or payload.get('version_id')
        or request.args.get('version_uuid')
        or request.args.get('version_id')
    )

    try:
        file_location, zip_hint, resolved_version = resolve_version_file(
            game,
            kind=kind,
            version_uuid=version_uuid,
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except LookupError as exc:
        return api_error(str(exc), code='not_found')

    # Refuse downloads when the version path is gone (Wave 14b residual / 15a).
    if (
        file_location is None
        or not str(file_location).strip()
        or not (os.path.isfile(file_location) or os.path.isdir(file_location))
    ):
        return api_error(
            'Version file is missing on disk',
            code='not_found',
            status=410,
            body_code='path_missing',
            hint=(
                'This install path is gone. Use game details → Remove missing versions '
                '(librarian+) or re-scan after restoring files.'
            ),
            path_missing=True,
            downloadable=False,
        )

    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        return api_error('Server configuration error', code='internal')

    is_safe, _error_message = is_safe_path(file_location, allowed_bases)
    if not is_safe:
        return api_error('Access denied', code='forbidden')

    zip_file_path = _resolve_zip_file_path(game, file_location if kind == 'base' else zip_hint)

    try:
        download_request = _create_or_get_download_request(
            game,
            file_location=file_location,
            zip_file_path=zip_file_path,
        )
        return api_ok({
            'download_id': download_request.id,
            'status': download_request.status,
            'stream_url': f'/download_zip/{download_request.id}',
            'kind': kind if kind in ('base', 'update', 'extra') else 'base',
            'version_uuid': resolved_version,
        })
    except Exception as exc:
        db.session.rollback()
        log_system_event(
            f'Error creating API download request for {game_uuid}: {exc}',
            event_type='game',
            event_level='error',
        )
        return api_error('Failed to create download request', code='internal')


def _download_file_name(download_request: DownloadRequest):
    if not download_request.zip_file_path:
        return None
    normalized = download_request.zip_file_path.replace("\\", "/")
    return os.path.basename(normalized) or None


def _serialize_download_request(download_request: DownloadRequest) -> dict:
    status = download_request.status or "pending"
    return {
        "id": download_request.id,
        "game_name": download_request.game.name if download_request.game else None,
        "status": status,
        "file_name": _download_file_name(download_request),
        "download_url": (
            f"/download_zip/{download_request.id}" if status == "available" else None
        ),
        "download_size": download_request.download_size,
    }


@apis_bp.route("/my_downloads", methods=["GET"])
@login_required
def api_my_downloads():
    """List the current user's download requests for the member SPA."""
    download_requests = db.session.execute(
        select(DownloadRequest)
        .options(joinedload(DownloadRequest.game))
        .filter_by(user_id=current_user.id)
        .order_by(DownloadRequest.request_time.desc())
    ).scalars().unique().all()

    return jsonify([_serialize_download_request(item) for item in download_requests]), 200


@apis_bp.route('/delete_download/<int:request_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_download_request(request_id: int) -> Tuple[dict, int]:
    """Delete a download request."""
    if request_id <= 0:
        log_system_event(f'Invalid request ID: {request_id}', event_type='download_api', event_level='warning')
        return api_error('Invalid request ID', code='bad_request')

    try:
        download_request = db.session.get(DownloadRequest, request_id)
        if not download_request:
            return api_error('Download request not found', code='not_found')

        log_system_event(
            f'Deleting download request {request_id} for user {download_request.user_id}',
            event_type='download_api',
            event_level='info',
        )

        db.session.delete(download_request)
        db.session.commit()

        log_system_event(
            f'Successfully deleted download request {request_id}',
            event_type='download_api', event_level='info',
        )

        return api_ok({'message': 'Download request deleted successfully'})

    except Exception as e:
        db.session.rollback()
        log_system_event(
            f'Error deleting download request {request_id}: {str(e)}',
            event_type='download_api',
            event_level='error',
        )
        current_app.logger.warning('delete download request failed: %s', e)
        return api_error('Could not delete the download request', code='internal')
