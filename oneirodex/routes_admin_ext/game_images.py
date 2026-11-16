"""Admin: game image-CRUD routes.

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1c): the image editor
page (``edit_game_images``), single-file upload / delete for game artwork
(``upload_image`` / ``delete_game_image``), and the IGDB image-refresh trigger
plus its progress poll (``refresh_game_images`` /
``check_image_refresh_progress``).

The blueprint is ``admin2_bp`` (registered with **no** ``url_prefix``), so every
URL rule here is byte-identical to when these lived on the ``main`` blueprint;
only the endpoint names change (``main.*`` -> ``admin2.*``).

The one rename: the old ``main.delete_image`` view becomes ``delete_game_image``
here, because ``routes_admin_ext/images.py`` already owns the
``admin2.delete_image`` endpoint (a different route,
``/admin/api/delete_image/<int:image_id>`` [DELETE]). The URL rule this view
serves -- ``/delete_image`` [POST] -- is unchanged; nothing in-repo referenced
it by endpoint name.

Route bodies moved verbatim; the nine ``print()`` calls become module-level
``logger.{info,warning,error}``.
"""

import hashlib
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    abort, current_app, flash, jsonify, redirect, request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import cache, db
from oneirodex.models import Game, Image
from oneirodex.schemas.admin_game_images import DeleteGameImageBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.auth import admin_required
from oneirodex.utils.background import run_in_background
from oneirodex.utils.gamenames import get_game_name_by_uuid
from oneirodex.utils.image_kinds import (
    IMAGE_KIND_ORDER,
    SINGULAR_IMAGE_KINDS,
    image_kinds_error_message,
    parse_image_kind,
)
from oneirodex.utils.image_paths import image_path_under_save_dir
from oneirodex.utils.image_upload_limits import (
    GAME_IMAGE_MAX_BYTES,
    GAME_IMAGE_MAX_PIXELS,
    ImageWorkBusy,
    prepare_game_image,
)
from oneirodex.utils.scanning import refresh_images_in_background, is_scan_job_running
from oneirodex.utils.validation import validate_body

from . import admin2_bp

logger = logging.getLogger(__name__)


@admin2_bp.route('/edit_game_images/<game_uuid>', methods=['GET'])
@login_required
@admin_required
def edit_game_images(game_uuid):
    if is_scan_job_running():
        flash('A scan is running. Image editing is available again as soon as it finishes.', 'warning')
    db.session.execute(select(Game.id).filter_by(uuid=game_uuid)).scalar_one_or_none() or abort(404)
    return render_admin_spa(title='Edit artwork - Oneirodex Admin')


# Per-upload ceiling for game artwork. The global MAX_CONTENT_LENGTH in config
# is the outer bound that stops an unbounded body being buffered at all; this is
# the one a user actually hits, and it is the number the error message quotes.
MAX_IMAGE_UPLOAD_BYTES = GAME_IMAGE_MAX_BYTES

# Decompression-bomb ceiling — roughly a 60-megapixel image, comfortably above
# any real cover or screenshot. verify() does not decode pixel data, so without
# this the resize below is where a 40000x40000 PNG would land.
MAX_IMAGE_PIXELS = GAME_IMAGE_MAX_PIXELS


def _game_filename_key(game_uuid: str) -> str:
    """Return a fixed safe filename component independent of route syntax."""
    return hashlib.sha256(str(game_uuid).encode('utf-8')).hexdigest()[:16]


def _publish_image_bytes(save_dir: Path, filename: str, content: bytes) -> Path:
    """Durably publish a new immutable image file before changing its DB row."""
    save_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.oneirodex-image-', suffix='.tmp', dir=save_dir,
    )
    temporary_path = Path(temporary_name)
    destination = save_dir / filename
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
        if os.name != 'nt' and hasattr(os, 'O_DIRECTORY'):
            directory_fd = os.open(save_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return destination
    finally:
        temporary_path.unlink(missing_ok=True)


@admin2_bp.route('/upload_image/<game_uuid>', methods=['POST'])
@login_required
@admin_required
def upload_image(game_uuid):
    logger.info(f"Uploading image for game {game_uuid}")
    if is_scan_job_running():
        logger.warning(f"Attempt to upload image for game UUID: {game_uuid} while scan job is running")
        flash('A scan is running. Image uploads are available again as soon as it finishes.', 'error')
        return api_error('A scan is running. Image uploads are available again as soon as it finishes.', code='forbidden')

    game_exists = db.session.execute(
        select(Game.uuid).filter_by(uuid=game_uuid)
    ).scalar_one_or_none()
    if game_exists is None:
        return api_error('Game not found', code='not_found', game_uuid=game_uuid)

    if 'file' not in request.files:
        return api_error('No file was included.', code='bad_request')

    file = request.files['file']
    try:
        image_type = parse_image_kind(
            request.form.get('image_type') or request.form.get('kind'),
            default='screenshot',
        )
    except ValueError:
        return api_error(image_kinds_error_message(), code='bad_request')

    if file.filename == '':
        return api_error('No file was selected.', code='bad_request')

    # Ignore the client suffix and select the stored suffix from the decoder so
    # a mismatched filename cannot mislabel the saved content.

    # Size first, before anything decodes the file. The previous version read
    # `file.content_length`, which is 0 for an ordinary multipart upload, so the
    # limit never applied — and it checked *after* Pillow had already opened the
    # image twice, which is the expensive half.
    file.seek(0, os.SEEK_END)
    upload_bytes = file.tell()
    file.seek(0)
    if upload_bytes > MAX_IMAGE_UPLOAD_BYTES:
        limit_mb = MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)
        return api_error(f'File size exceeds the {limit_mb}MB limit', code='bad_request')

    # Decode under the shared per-process work slot. The helper validates the
    # actual format/dimensions and only materializes pixels for a cover resize.
    try:
        file.seek(0)
        image_content, file_extension = prepare_game_image(file.read(upload_bytes), image_type)
    except ImageWorkBusy as exc:
        return api_error(str(exc), code='unavailable')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')

    # Resolve old files before publication, but leave the current rows and
    # bytes untouched until the replacement file is complete and durable.
    existing_paths = []
    if image_type in SINGULAR_IMAGE_KINDS:
        existing_rows = db.session.execute(
            select(Image).filter_by(game_uuid=game_uuid, image_type=image_type)
        ).scalars().all()
        for existing in existing_rows:
            old_path = image_path_under_save_dir(
                existing.url, current_app.config['IMAGE_SAVE_PATH'],
            )
            if old_path is None:
                return api_error('Stored image path is invalid', code='bad_request')
            existing_paths.append((existing, old_path, existing.url))
    short_uuid = str(uuid.uuid4())[:8]
    # game_uuid is a route parameter and must never become a filesystem path
    # component directly. Hash it so encoded separators and Windows traversal
    # syntax cannot escape IMAGE_SAVE_PATH.
    game_file_key = _game_filename_key(game_uuid)
    if image_type in SINGULAR_IMAGE_KINDS:
        unique_identifier = str(uuid.uuid4())[:8]
        filename = f"{game_file_key}_{image_type}_{unique_identifier}.{file_extension}"
    else:
        unique_identifier = datetime.now().strftime('%Y%m%d%H%M%S')
        short_uuid = str(uuid.uuid4())[:8]
        filename = f"{game_file_key}_{unique_identifier}_{short_uuid}.{file_extension}"
    save_dir = Path(current_app.config['IMAGE_SAVE_PATH'])
    _publish_image_bytes(save_dir, filename, image_content)
    logger.info("Game image file published")
    for existing, _old_path, _old_url in existing_paths:
        db.session.delete(existing)
    if existing_paths:
        # PostgreSQL's partial unique index for singular image kinds checks
        # uniqueness at statement time; flush the deletion inside this same
        # transaction before inserting the replacement row.
        db.session.flush()
    new_image = Image(game_uuid=game_uuid, image_type=image_type, url=filename)
    db.session.add(new_image)
    db.session.commit()
    for _existing, old_path, old_url in existing_paths:
        still_referenced = db.session.execute(
            select(Image.id).where(Image.url == old_url).limit(1)
        ).first()
        if still_referenced is not None:
            continue
        try:
            old_path.unlink(missing_ok=True)
        except OSError:
            # The DB already points at the replacement. Keep a harmless orphan
            # for later operator cleanup rather than turning success into a
            # misleading failure or risking another user's referenced file.
            logger.warning("Obsolete game image cleanup failed after replacement")
    logger.info("Game image row committed")

    return api_ok({
        'message': 'File uploaded successfully',
        'url': url_for('static', filename=f'library/images/{filename}'),
        'flash': 'Image uploaded successfully!',
        'image_id': new_image.id,
        'image_type': image_type,
        'kind': image_type,
    })

@admin2_bp.route('/delete_image', methods=['POST'])
@login_required
@admin_required
@validate_body(DeleteGameImageBody)
def delete_game_image(body: DeleteGameImageBody):
    if is_scan_job_running():
        logger.warning("Attempt to delete image while scan job is running")
        return api_error('A scan is running. Deleting images is available again as soon as it finishes.', code='forbidden')

    try:
        image_id = body.image_id
        is_cover = body.is_cover
        image = db.session.get(Image, image_id)
        if not image:
            return api_error('Image not found', code='not_found')

        # Delete image file from disk
        image_path = image_path_under_save_dir(
            image.url, current_app.config['IMAGE_SAVE_PATH'],
        )
        if image_path is None:
            raise ValueError('Invalid image path')
        if os.path.exists(image_path):
            logger.info(f"Deleting image file: {image_path}")
            os.remove(image_path)

        # Delete image record from database
        db.session.delete(image)
        db.session.commit()

        response_data = {'message': 'Image deleted successfully'}
        if is_cover:
            response_data['default_cover'] = url_for('static', filename='newstyle/default_cover.jpg')

        return api_ok(response_data)
    except Exception as e:
        # Log the error for debugging purposes
        logger.error(f"Error deleting image: {str(e)}")
        return api_error(
            'An unexpected error occurred while deleting the image',
            code='internal',
        )


@admin2_bp.route('/refresh_game_images/<game_uuid>', methods=['POST'])
@login_required
@admin_required
def refresh_game_images(game_uuid):
    game_name = get_game_name_by_uuid(game_uuid)
    logger.info(f"Route: /refresh_game_images - {current_user.name} - {current_user.role} method: {request.method} UUID: {game_uuid} Name: {game_name}")

    # Own app context, own session (utils/background.py). The uuid is a plain
    # string and `refresh_images_in_background` already guards its flash calls
    # with has_request_context(), so nothing here wanted the request anyway.
    run_in_background(
        current_app._get_current_object(),
        refresh_images_in_background,
        game_uuid,
        name=f'oneirodex-refresh-images-{str(game_uuid)[:8]}',
    )
    logger.info(f"Refresh images thread started for game UUID: {game_uuid} and Name: {game_name}.")

    # Check if the request is an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return a JSON response for AJAX requests
        return api_ok({"message": f"Game images refresh process started for {game_name}.", "status": "info"})
    else:
        # For non-AJAX requests, perform the usual redirec
        flash(f"Game images refresh process started for {game_name}.", "info")
        return redirect(url_for('library.library'))


@admin2_bp.route('/check_image_refresh_progress/<game_uuid>', methods=['GET'])
@login_required
@admin_required
def check_image_refresh_progress(game_uuid):
    """Check the progress of an image refresh operation."""
    # `status` on the cached dict is job progress (`complete` / `error` /
    # `in_progress`), not an envelope marker. Wrapping with api_ok would stamp
    # ok=True onto a failed refresh. image_refresh_progress.js branches on it.
    progress_data = cache.get(f'image_refresh_progress_{game_uuid}')

    if progress_data is None:
        return api_ok({'status': 'not_found', 'progress': 0})

    return jsonify(progress_data)
