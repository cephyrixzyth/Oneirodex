"""Avatar upload: validate, square, thumbnail, and retire the previous file.

Extracted from ``routes_settings.settings_profile_edit`` so the Jinja page and
the JSON API that backs the account modal run the same code. It was ~90 lines
inline in a route; duplicating it for the API would have meant two definitions
of "what counts as a valid avatar" drifting apart.
"""

from __future__ import annotations

import os
from uuid import uuid4

from PIL import Image as PILImage
from werkzeug.utils import secure_filename

from oneirodex.utils.functions import square_image
from oneirodex.utils.library_paths import library_dir

MAX_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_AVATAR_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})

# The unset-avatar mark: a gamepad in grey rather than the accent, so it reads
# as "no picture chosen" while still saying *games*. It replaced a headset,
# which named one peripheral and one way of playing.
DEFAULT_AVATAR = 'newstyle/avatars/default.svg'

# The previous default. Rows created before the change still point at it and
# must keep resolving, so the file stays on disk and stays undeletable.
LEGACY_DEFAULT_AVATAR = 'newstyle/avatar_default.jpg'

STOCK_AVATAR_DIR = 'newstyle/avatars/'
AVATAR_URL_PREFIX = 'library/images/avatars_users/'

# Six picks spanning how people actually played, not six variations on one era.
# Ordered roughly by era so the row reads as a timeline.
STOCK_AVATARS = (
    {'id': 'controller', 'label': 'Gamepad', 'path': f'{STOCK_AVATAR_DIR}controller.svg'},
    {'id': 'dpad', 'label': 'D-pad', 'path': f'{STOCK_AVATAR_DIR}dpad.svg'},
    {'id': 'cartridge', 'label': 'Cartridge', 'path': f'{STOCK_AVATAR_DIR}cartridge.svg'},
    {'id': 'arcade', 'label': 'Arcade cabinet', 'path': f'{STOCK_AVATAR_DIR}arcade.svg'},
    {'id': 'joystick', 'label': 'Arcade stick', 'path': f'{STOCK_AVATAR_DIR}joystick.svg'},
    {'id': 'disc', 'label': 'Disc', 'path': f'{STOCK_AVATAR_DIR}disc.svg'},
)

_STOCK_BY_ID = {entry['id']: entry for entry in STOCK_AVATARS}


def stock_avatar(avatar_id: str | None) -> dict | None:
    """Look up a stock avatar by id. Unknown ids are not paths — they are None.

    The id is the only thing a client may send: accepting a *path* would make
    this an arbitrary-file setter pointed at the static tree.
    """
    if not avatar_id or not isinstance(avatar_id, str):
        return None
    return _STOCK_BY_ID.get(avatar_id.strip())


def is_shipped_avatar(path: str | None) -> bool:
    """True for anything that ships with Oneirodex rather than being uploaded.

    Used to keep the cleanup pass from deleting files it does not own — a member
    switching from a stock avatar to an upload must not take the stock file
    with them for everybody else.
    """
    if not path:
        return True
    return (
        path == DEFAULT_AVATAR
        or path == LEGACY_DEFAULT_AVATAR
        or path.startswith(STOCK_AVATAR_DIR)
    )


def avatar_url(path: str | None, *, theme: str | None = None) -> str:
    """Browser URL for an avatar, themed when it is one of ours.

    Two kinds of avatar, two resolutions:

    * **Shipped** (`newstyle/avatars/*.svg`, and the legacy default) — served
      from the *active theme*, because the preset generator writes a recoloured
      copy of each one into every theme folder. These are flat SVGs rendered as
      `<img>`, so they can neither inherit `currentColor` nor read a custom
      property: without this they stay default-green on all nine presets while
      the rest of the UI changes around them.
    * **Uploaded** (`library/images/avatars_users/…`) — a member's own picture.
      Served exactly as before; recolouring someone's photograph would be
      absurd, and there is no themed copy of it to serve.

    Falls back to the plain static path whenever the themed file is absent,
    which covers an install whose theme folders predate the recoloured avatars
    and the moment before the first boot-time sync has run.

    `theme` is accepted for callers outside a request (tests, the CLI); left
    unset it reads the signed-in member's preference the same way `theme_asset`
    does.
    """
    from flask import current_app, url_for

    if not path:
        path = DEFAULT_AVATAR

    if not is_shipped_avatar(path):
        return url_for('static', filename=path)

    name = os.path.basename(path)
    # The legacy default is a JPG that never had a themed twin; point it at the
    # current default SVG, which does.
    if path == LEGACY_DEFAULT_AVATAR:
        name = os.path.basename(DEFAULT_AVATAR)

    if theme is None:
        theme = _current_theme()

    root = os.path.join(library_dir(), 'themes')
    for candidate in (theme, 'default'):
        if not candidate:
            continue
        themed = os.path.join(root, candidate, 'avatars', name)
        if os.path.isfile(themed):
            return url_for(
                'static', filename=f'library/themes/{candidate}/avatars/{name}'
            )

    return url_for('static', filename=path)


def _current_theme() -> str:
    """The signed-in member's theme slug, or 'default'."""
    try:
        from flask_login import current_user

        if current_user.is_authenticated:
            prefs = getattr(current_user, 'preferences', None)
            if prefs is not None:
                return getattr(prefs, 'theme', None) or 'default'
    except Exception:  # noqa: BLE001 — outside a request, or no login manager
        pass
    return 'default'


# Full size and thumbnail. The thumbnail is what the rail and chat rows use, so
# it is generated up front rather than resized in the browser on every render.
AVATAR_MAX_EDGE = 500
THUMBNAIL_MAX_EDGE = 50


def avatar_upload_folder(app) -> str:
    """Where avatars live on disk. Created on demand."""
    return os.path.join(app.config['UPLOAD_FOLDER'], 'images/avatars_users')


def _thumbnail_path(image_path: str) -> str:
    stem, extension = os.path.splitext(image_path)
    return f'{stem}_thumbnail{extension}'


def _file_size(file) -> int:
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size


def validate_avatar(file) -> str | None:
    """Return a human-readable reason to reject this upload, or None."""
    if not file or not getattr(file, 'filename', ''):
        return 'Choose an image first.'

    extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if extension not in ALLOWED_AVATAR_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_AVATAR_EXTENSIONS))
        return f'Unsupported image type. Use one of: {allowed}.'

    if _file_size(file) > MAX_AVATAR_BYTES:
        return f'Image is larger than the {MAX_AVATAR_BYTES // 1024 // 1024}MB limit.'

    return None


def _resize_animated_gif(img, image_path: str) -> None:
    """Keep the animation. Resizing frame by frame is the only way to."""
    frames = []
    try:
        while True:
            frame = img.copy()
            frame.thumbnail((AVATAR_MAX_EDGE, AVATAR_MAX_EDGE), PILImage.LANCZOS)
            frames.append(frame)
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    frames[0].save(
        image_path,
        save_all=True,
        append_images=frames[1:],
        format='GIF',
        duration=img.info.get('duration', 100),
        loop=img.info.get('loop', 0),
    )

    # First frame only — an animated 50px thumbnail in a list of forty rows is
    # forty animations competing for attention beside the text.
    thumbnail = frames[0].copy()
    thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), PILImage.LANCZOS)
    thumbnail.save(_thumbnail_path(image_path), 'GIF')


def _remove_previous(upload_folder: str, previous_path: str | None) -> None:
    """Delete the avatar being replaced. Never anything Oneirodex ships."""
    if is_shipped_avatar(previous_path):
        return
    for candidate in (previous_path, _thumbnail_path(previous_path)):
        full_path = os.path.join(upload_folder, os.path.basename(candidate))
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
        except OSError:
            # A stale file left behind costs disk space; failing the upload
            # over it would cost the user their new avatar.
            pass


def save_avatar(file, user, app) -> tuple[str | None, str | None]:
    """Store ``file`` as ``user``'s avatar.

    Returns ``(avatarpath, error)`` — exactly one of the two is set. The caller
    commits; this function only touches the filesystem and the in-memory user,
    so a failed commit does not leave a half-applied change.
    """
    error = validate_avatar(file)
    if error:
        return None, error

    upload_folder = avatar_upload_folder(app)
    try:
        os.makedirs(upload_folder, exist_ok=True)
    except OSError as exc:
        app.logger.warning('avatar upload folder unavailable: %s', exc)
        return None, 'Could not write to the avatar folder.'

    filename = secure_filename(file.filename)
    extension = filename.rsplit('.', 1)[-1].lower()
    stored_name = f'{uuid4()}.{extension}'
    image_path = os.path.join(upload_folder, stored_name)

    previous = user.avatarpath
    try:
        file.save(image_path)
        img = PILImage.open(image_path)
        if img.format == 'GIF' and 'duration' in img.info:
            _resize_animated_gif(img, image_path)
        else:
            squared = square_image(img, AVATAR_MAX_EDGE)
            squared.save(image_path)
            thumbnail = squared.copy()
            thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), PILImage.LANCZOS)
            thumbnail.save(_thumbnail_path(image_path))
    except Exception as exc:  # Pillow raises a wide family for bad image data
        app.logger.warning('avatar processing failed: %s', exc)
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except OSError:
            pass
        return None, 'That file could not be read as an image.'

    _remove_previous(upload_folder, previous)
    user.avatarpath = AVATAR_URL_PREFIX + stored_name
    return user.avatarpath, None


def thumbnail_for(path: str | None) -> str:
    """The small variant of an avatar, or the avatar itself when there is none.

    Uploads get a real `_thumbnail` file written beside them. The shipped
    avatars do not and do not need one — they are SVGs, which scale — so
    deriving the name for them produced a request for a file that was never
    written and a broken image beside "Thumbnail preview".
    """
    if not path:
        return DEFAULT_AVATAR
    if is_shipped_avatar(path):
        return path
    stem, extension = os.path.splitext(path)
    return f'{stem}_thumbnail{extension}'


def set_stock_avatar(avatar_id: str, user, app) -> tuple[str | None, str | None]:
    """Point ``user`` at one of the shipped avatars.

    Same contract as :func:`save_avatar` — ``(avatarpath, error)`` — so the
    route can treat "uploaded a file" and "picked a stock one" identically. The
    previously uploaded file is retired here too; otherwise switching to a stock
    avatar would quietly leave an orphan behind on every switch.
    """
    entry = stock_avatar(avatar_id)
    if entry is None:
        return None, 'That is not one of the avatars we ship.'

    _remove_previous(avatar_upload_folder(app), user.avatarpath)
    user.avatarpath = entry['path']
    return user.avatarpath, None
