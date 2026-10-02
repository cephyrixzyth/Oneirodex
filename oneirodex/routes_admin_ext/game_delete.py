"""Admin: game-deletion routes.

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1d): the
library-only game removal (``delete_game_route``), the unmatched-folder /
loose-file deletion helper (``delete_folder``), and the disk + library
deletion (``delete_full_game``).

The blueprint is ``admin2_bp`` (registered with **no** ``url_prefix``), so every
URL rule here is byte-identical to when these lived on the ``main`` blueprint;
only the endpoint names change (``main.*`` -> ``admin2.*``).

Route bodies moved verbatim; the ``print()`` calls become module-level
``logger.{info,warning,error}``.
"""

import logging
import os
import shutil

from flask import current_app, request
from flask_login import current_user, login_required
from sqlalchemy import select
from werkzeug.exceptions import NotFound

from oneirodex import db
from oneirodex.models import Game, UnmatchedFolder
from oneirodex.schemas.admin_game_delete import DeleteFullGameBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.game_core import delete_game
from oneirodex.utils.scanning import is_scan_job_running
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path_strict
from oneirodex.utils.validation import validate_body

from . import admin2_bp

logger = logging.getLogger(__name__)


@admin2_bp.route('/delete_game/<string:game_uuid>', methods=['POST'])
@login_required
@admin_required
def delete_game_route(game_uuid):
    logger.info(f"Route: /delete_game - {current_user.name} - {current_user.role} method: {request.method} UUID: {game_uuid}")

    if is_scan_job_running():
        logger.warning(f"Error: Attempt to delete game UUID: {game_uuid} while scan job is running")
        return api_error('A scan is running. Deleting games is available again as soon as it finishes.', code='forbidden')

    try:
        delete_game(game_uuid)
        return api_ok({'message': 'Game removed from library successfully.'})
    except NotFound:
        logger.warning(f"Error: game UUID {game_uuid} not found")
        return api_error('Game not found.', code='not_found')
    except Exception as e:
        logger.error(f"Error deleting game {game_uuid}: {e}")
        return api_error("Couldn't remove that game. Nothing was changed.", code='internal')


@admin2_bp.route('/delete_folder', methods=['POST'])
@login_required
@admin_required
def delete_folder():
    data = request.get_json()
    folder_path = data.get('folder_path') if data else None

    if not folder_path:
        return api_error('Path is required.', code='bad_request', body_status='error')

    if is_scan_job_running():
        return api_error(
            'A scan is running. Deleting is available again as soon as it finishes.',
            code='forbidden',
            body_status='error',
        )

    allowed_bases = get_allowed_base_directories(current_app)
    is_safe, error_message = is_safe_path_strict(folder_path, allowed_bases)
    if not is_safe:
        logger.warning(f"Security error: delete_folder path validation failed for {folder_path}: {error_message}")
        return api_error('Access denied.', code='forbidden', body_status='error')

    full_path = os.path.abspath(folder_path)

    folder_entry = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=folder_path)).scalar_one_or_none()

    if not os.path.exists(full_path):
        if folder_entry:
            db.session.delete(folder_entry)
            db.session.commit()
        return api_error(
            'The specified path does not exist. Entry removed if it was in the database.',
            code='not_found',
            body_status='error',
        )

    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
        else:
            shutil.rmtree(full_path)

        if not os.path.exists(full_path):
            if folder_entry:
                db.session.delete(folder_entry)
                db.session.commit()
            return api_ok({'status': 'success', 'message': 'Item deleted successfully. Database entry removed.'})
    except PermissionError:
        return api_error(
            'Failed to delete the item due to insufficient permissions. Database entry retained.',
            code='forbidden',
            body_status='error',
        )
    except Exception as e:
        current_app.logger.warning('delete unmatched item failed: %s', e)
        return api_error(
            'Could not delete the item. Database entry retained.',
            code='internal',
            body_status='error',
        )


@admin2_bp.route('/delete_full_game', methods=['POST'])
@login_required
@admin_required
@validate_body(DeleteFullGameBody)
def delete_full_game(body: DeleteFullGameBody):
    logger.info(f"Route: /delete_full_game - {current_user.name} - {current_user.role} method: {request.method}")
    game_uuid = body.game_uuid
    logger.info(f"Route: /delete_full_game - Game UUID: {game_uuid}")

    if is_scan_job_running():
        logger.warning(f"Error: Attempt to delete full game UUID: {game_uuid} while scan job is running")
        return api_error('A scan is running. Deleting games is available again as soon as it finishes.', code='forbidden')

    game_to_delete = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
    logger.info(f"Route: /delete_full_game - Game to delete: {game_to_delete}")

    if not game_to_delete:
        logger.warning("Route: /delete_full_game - Game not found.")
        return api_error('Game not found.', code='not_found')

    full_path = game_to_delete.full_disk_path
    logger.info(f"Route: /delete_full_game - Full path: {full_path}")

    # A game whose files are already gone must still be removable from the
    # library, otherwise the entry is stranded with no way to delete it.
    on_disk = bool(full_path) and os.path.exists(full_path)
    if not on_disk:
        logger.info("Route: /delete_full_game - Nothing on disk, cleaning up database entry only.")

    try:
        is_directory = on_disk and os.path.isdir(full_path)

        if on_disk:
            allowed_bases = get_allowed_base_directories(current_app)
            is_safe, error_message = is_safe_path_strict(full_path, allowed_bases)
            if not is_safe:
                logger.warning(f"Security error: delete_full_game path validation failed for {full_path}: {error_message}")
                return api_error('Access denied.', code='forbidden')

            if is_directory:
                logger.info(f"Deleting game folder: {full_path}")
                shutil.rmtree(full_path)
            else:
                logger.info(f"Deleting game file: {full_path}")
                os.remove(full_path)

            if os.path.exists(full_path):
                raise Exception("Deletion failed - file/folder still exists")

            logger.info(f"Game deleted from disk: {full_path} - initiating database cleanup.")

        delete_game(game_uuid)
        logger.info("Database and image cleanup complete.")

        if not on_disk:
            success_message = 'Game was not present on disk; removed from the library.'
        elif is_directory:
            success_message = 'Game and its folder have been deleted successfully.'
        else:
            success_message = 'Game file has been deleted successfully.'
        return api_ok({'message': success_message})
    except Exception as e:
        error_message = f"Error deleting game from disk: {e}"
        logger.error(error_message)
        return api_error(error_message, code='internal')
