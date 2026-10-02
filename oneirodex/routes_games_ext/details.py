import mimetypes
import os
import uuid

from flask import abort, current_app, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.game_core import get_game_by_uuid
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.local_metadata import get_local_cover_path, get_local_screenshots
from oneirodex.utils.member_spa import render_member_spa
from oneirodex.utils.security import (
    get_allowed_base_directories,
    is_safe_path,
    open_plain_file_within,
    sanitize_path_for_logging,
)

# Re-export for older callers that imported get_path_size from this module.
from oneirodex.utils.functions import get_path_size  # noqa: F401

from . import games_bp


@games_bp.route('/game_details/<string:game_uuid>')
@login_required
def game_details(game_uuid):
    """Member SPA shell for game details (React page under TopNav)."""
    log_system_event(
        f"User {current_user.name} requested game details for UUID: {game_uuid[:8]}...",
        event_type='game',
        event_level='debug',
    )
    try:
        valid_uuid = uuid.UUID(game_uuid, version=4)
    except ValueError:
        log_system_event(
            f"Invalid UUID format provided by user {current_user.name}: {game_uuid[:20]}...",
            event_type='security',
            event_level='warning',
        )
        abort(404)

    game = get_game_by_uuid(str(valid_uuid))
    if not game:
        log_system_event(
            f"User {current_user.name} attempted to access non-existent game UUID: {game_uuid[:8]}...",
            event_type='security',
            event_level='warning',
        )
        abort(404)

    if not user_can_access_game(current_user, game):
        log_system_event(
            f"User {current_user.name} blocked from restricted library game {game_uuid[:8]}...",
            event_type='security',
            event_level='warning',
        )
        abort(403)

    return render_member_spa()


@games_bp.route('/game/<game_uuid>/local_image/<image_type>')
@login_required
def serve_local_image(game_uuid, image_type):
    """Serve local cover/screenshot files from the game folder."""
    try:
        uuid.UUID(game_uuid, version=4)
    except ValueError:
        log_system_event(
            f"User {current_user.name} attempted to serve local image with invalid UUID: {game_uuid}",
            event_type='security',
            event_level='warning',
        )
        abort(400, "Invalid game UUID")

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
    if not game:
        log_system_event(
            f"User {current_user.name} attempted to serve local image for non-existent game: {game_uuid}",
            event_type='security',
            event_level='warning',
        )
        abort(404, "Game not found")

    if not user_can_access_game(current_user, game):
        abort(403)

    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        log_system_event(
            "Server configuration error: No allowed base directories configured",
            event_type='security',
            event_level='error',
        )
        abort(500, "Server configuration error")

    # Resolved once, before anything is looked up under it. The checks and the
    # open below all compare against this string, so a game folder swapped for a
    # link afterwards reads as "outside" instead of moving the boundary with it.
    try:
        real_game = os.path.realpath(game.full_disk_path)
    except (OSError, TypeError, ValueError):
        real_game = game.full_disk_path  # is_safe_path refuses whatever this is
    is_safe, error_message = is_safe_path(real_game, allowed_bases)
    if not is_safe:
        log_system_event(
            f"Security: User {current_user.name} attempted access to unsafe path {sanitize_path_for_logging(game.full_disk_path)}: {error_message}",
            event_type='security',
            event_level='warning',
        )
        abort(403, "Access denied")

    image_path = None
    if image_type == 'cover':
        image_path = get_local_cover_path(real_game)
    elif image_type == 'screenshot':
        index = request.args.get('index', 0, type=int)
        screenshots = get_local_screenshots(real_game)
        if 0 <= index < len(screenshots):
            image_path = screenshots[index]
    else:
        log_system_event(
            f"User {current_user.name} requested invalid image type: {image_type}",
            event_type='security',
            event_level='warning',
        )
        abort(400, "Invalid image type")

    # The helpers already skip links, but a share writer can still swap the file
    # between their check and the read. So the file is opened here, once, and
    # what is served is that descriptor: a regular file inside the game folder,
    # nothing else, however the path changes after this line.
    handle = None
    if image_path:
        try:
            handle = open_plain_file_within(real_game, image_path, base_is_resolved=True)
        except FileNotFoundError:
            pass
        except OSError:
            log_system_event(
                f"Security: refused local {image_type} image that is a link or leaves the game folder for game {game.name}",
                event_type='security',
                event_level='warning',
            )

    if handle is None:
        log_system_event(
            f"User {current_user.name} requested local image that doesn't exist: {image_type} for game {game.name}",
            event_type='game',
            event_level='debug',
        )
        abort(404, "Image not found")

    try:
        mime_type, _ = mimetypes.guess_type(image_path)
        log_system_event(
            f"Serving local {image_type} image for game '{game.name}' to user {current_user.name}",
            event_type='game',
            event_level='debug',
        )
        info = os.fstat(handle.fileno())
        response = send_file(
            handle,
            mimetype=mime_type or 'image/jpeg',
            last_modified=info.st_mtime,
            etag=f'{info.st_mtime_ns:x}-{info.st_size:x}',
            conditional=False,
        )
        response.content_length = info.st_size
        # With a file object Werkzeug cannot know the length, so the 304 /
        # Range handling is applied here with the size from the descriptor.
        return response.make_conditional(request.environ, accept_ranges=True, complete_length=info.st_size)
    except BaseException:
        handle.close()
        raise
