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

import logging
import os
import uuid
from datetime import datetime

from flask import (
    abort, current_app, flash, jsonify, redirect, request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select
from werkzeug.utils import secure_filename
from PIL import Image as PILImage

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
MAX_IMAGE_UPLOAD_BYTES = 3 * 1024 * 1024

# Decompression-bomb ceiling — roughly a 60-megapixel image, comfortably above
# any real cover or screenshot. verify() does not decode pixel data, so without
# this the resize below is where a 40000x40000 PNG would land.
MAX_IMAGE_PIXELS = 60_000_000


@admin2_bp.route('/upload_image/<game_uuid>', methods=['POST'])
@login_required
@admin_required
def upload_image(game_uuid):
    logger.info(f"Uploading image for game {game_uuid}")
    if is_scan_job_running():
        logger.warning(f"Attempt to upload image for game UUID: {game_uuid} while scan job is running")
        flash('A scan is running. Image uploads are available again as soon as it finishes.', 'error')
        return api_error('A scan is running. Image uploads are available again as soon as it finishes.', code='forbidden')

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

    # Validate file extension and content type
    allowed_extensions = {'jpg', 'jpeg', 'png', 'gif'}
    filename = secure_filename(file.filename)
    file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    if file_extension not in allowed_extensions:
        return api_error('Upload a JPG, PNG, or GIF.', code='bad_request')

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

    # Further validate the file's data to ensure it's a valid image
    try:
        img = PILImage.open(file)
        img.verify()  # Verify that it is, in fact, an image
        file.seek(0)
        img = PILImage.open(file)
    except (IOError, SyntaxError, PILImage.DecompressionBombError):
        return api_error('Invalid image data', code='bad_request')

    # A few hundred KB of PNG can declare a 40000x40000 canvas; verify() does not
    # decode it, but the resize below would.
    if (img.width * img.height) > MAX_IMAGE_PIXELS:
        return api_error(
            f'That image is too big. The limit is {MAX_IMAGE_PIXELS // 1_000_000} megapixels.',
            code='bad_request',
        )

    # Resized output has to be *saved*, which is what was missing: thumbnail()
    # mutates `img` in place and the code then wrote the original bytes back
    # out, so oversized covers were stored at full size and the resize was dead.
    resized = None
    source_format = img.format
    max_width, max_height = 1200, 1600
    if image_type == 'cover' and (img.width > max_width or img.height > max_height):
        # LANCZOS, not ANTIALIAS: the latter was deprecated in Pillow 9.1
        # and removed in 10, so this line raised AttributeError on every
        # oversized cover upload. Same filter every other resize here uses.
        img.thumbnail((max_width, max_height), PILImage.LANCZOS)
        resized = img
    file.seek(0)

    # Singular kinds: replace existing primary of that kind
    if image_type in SINGULAR_IMAGE_KINDS:
        existing_rows = db.session.execute(
            select(Image).filter_by(game_uuid=game_uuid, image_type=image_type)
        ).scalars().all()
        for existing in existing_rows:
            old_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], existing.url)
            if os.path.exists(old_path):
                os.remove(old_path)
            db.session.delete(existing)
        db.session.commit()
    short_uuid = str(uuid.uuid4())[:8]
    if image_type in SINGULAR_IMAGE_KINDS:
        unique_identifier = str(uuid.uuid4())[:8]
        filename = f"{game_uuid}_{image_type}_{unique_identifier}.{file_extension}"
    else:
        unique_identifier = datetime.now().strftime('%Y%m%d%H%M%S')
        short_uuid = str(uuid.uuid4())[:8]
        filename = f"{game_uuid}_{unique_identifier}_{short_uuid}.{file_extension}"
    save_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], filename)
    if resized is not None:
        # Keep the uploaded format so a .png stays a PNG — inferring it from the
        # path would break RGBA on a .jpg and flatten nothing correctly.
        resized.save(save_path, format=source_format or None)
    else:
        file.save(save_path)
    logger.info(f"File saved to: {save_path}")
    new_image = Image(game_uuid=game_uuid, image_type=image_type, url=filename)
    db.session.add(new_image)
    db.session.commit()
    logger.info(f"File saved to DB with ID: {new_image.id}")

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
        image_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], image.url)
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
