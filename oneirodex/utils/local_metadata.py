"""
Local filesystem metadata persistence utilities.
Implements Jellyfin-style metadata files for IGDB ID persistence.
"""
import os
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from flask import current_app
from oneirodex.utils.security import (
    get_allowed_base_directories,
    is_path_within,
    is_plain_file_within,
    is_safe_path,
    open_plain_file_within,
)
from oneirodex.utils.functions import sanitize_string_input

logger = logging.getLogger(__name__)

DEFAULT_METADATA_FILENAME = 'oneirodex.json'
LEGACY_METADATA_FILENAME = 'oneirodex.json'
#: A real sidecar is a few hundred bytes; the folder is share-writable.
_MAX_SIDECAR_BYTES = 256 * 1024


def _resolve_metadata_path(full_disk_path, filename):
    """Return path to existing metadata file, falling back to legacy name if needed.

    A sidecar that is a symlink (or resolves outside the game folder) is treated
    as absent: the folder's contents are scanned, not trusted.
    """
    primary = os.path.join(full_disk_path, filename)
    if is_plain_file_within(full_disk_path, primary):
        return primary
    if filename != LEGACY_METADATA_FILENAME:
        legacy = os.path.join(full_disk_path, LEGACY_METADATA_FILENAME)
        if is_plain_file_within(full_disk_path, legacy):
            return legacy
    return None


def read_local_metadata(full_disk_path, filename=DEFAULT_METADATA_FILENAME):
    """
    Read local metadata file from game folder.

    Args:
        full_disk_path: Full path to game folder
        filename: Metadata filename (default: oneirodex.json). Falls back to
            oneirodex.json when the primary file is missing.

    Returns:
        dict or None: Metadata dict with keys like 'igdb_id', or None if not found/error

    Example return:
    {
        "igdb_id": 7331,
        "title": "DOOM",
        "identified_at": "2025-11-04T10:30:00Z",
        "manually_verified": true,
        "version": "1.0"
    }
    """
    metadata_path = None
    try:
        # Security check
        if current_app:
            allowed_bases = get_allowed_base_directories(current_app)
            if not allowed_bases:
                logger.warning(f"No allowed base directories configured for {full_disk_path}")
                return None

            is_safe, error_message = is_safe_path(full_disk_path, allowed_bases)
            if not is_safe:
                logger.warning(f"Security: Unsafe path {full_disk_path}: {error_message}")
                return None

        # Check if path exists and is directory
        if not os.path.exists(full_disk_path):
            return None
        if not os.path.isdir(full_disk_path):
            logger.debug(f"Path is not a directory: {full_disk_path}")
            return None

        metadata_path = _resolve_metadata_path(full_disk_path, filename)
        if not metadata_path:
            return None

        # Read and parse JSON. The sidecar sits in a share-writable folder and
        # may have been swapped for a link since _resolve_metadata_path vetted
        # it, so the check runs again on the descriptor that is actually read.
        with open_plain_file_within(full_disk_path, metadata_path) as f:
            raw = f.read(_MAX_SIDECAR_BYTES + 1)
        if len(raw) > _MAX_SIDECAR_BYTES:
            logger.warning(f"Ignoring oversized metadata file {metadata_path}")
            return None
        metadata = json.loads(raw)

        # Validate required fields
        if not isinstance(metadata, dict):
            logger.warning(f"Invalid metadata format in {metadata_path}: not a dict")
            return None

        if 'igdb_id' not in metadata:
            logger.warning(f"Invalid metadata in {metadata_path}: missing igdb_id")
            return None

        logger.info(f"✅ Found local metadata: IGDB ID {metadata['igdb_id']} in {metadata_path}")
        return metadata

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON in {metadata_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading local metadata from {full_disk_path}: {e}")
        return None


def _replace_with_json(target, payload):
    """Write *payload* as JSON so that *target* ends up a new plain file.

    ``open(target, 'w')`` follows a link and truncates what it names, and
    whoever can write to the game folder can plant that link between any check
    and the open. This never opens *target*: the JSON goes to a new file made
    with ``O_EXCL`` (which refuses an existing name, link or not) next to it,
    and ``os.replace`` then swaps it in, replacing a link instead of following
    it. A failed write leaves the previous sidecar as it was.

    The game folder keeps its timestamps: creating and renaming the temporary
    file would otherwise move the folder's mtime, which the freshness check
    reads as "the game was updated locally".
    """
    folder, name = os.path.split(target)
    try:
        before = os.stat(folder)
    except OSError:
        before = None
    temp = os.path.join(folder, f'.{name}.{secrets.token_hex(6)}.tmp')
    # 0o666 is cut down by the umask, as it is for open(..., 'w').
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o666)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        _replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    if before is not None:
        try:
            os.utime(folder, ns=(before.st_atime_ns, before.st_mtime_ns))
        except OSError:
            pass


def _replace(temp, target, attempts=5):
    """``os.replace``, retried briefly on Windows, where a reader that has the
    sidecar open (a scan, an antivirus) makes it fail with a sharing violation."""
    for attempt in range(attempts):
        try:
            os.replace(temp, target)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == attempts - 1:
                raise
            time.sleep(0.05)


def write_local_metadata(full_disk_path, igdb_id, game_title=None, manually_verified=False,
                         filename=DEFAULT_METADATA_FILENAME):
    """
    Write local metadata file to game folder.

    Args:
        full_disk_path: Full path to game folder
        igdb_id: IGDB ID number
        game_title: Game title (optional, for human readability)
        manually_verified: Whether this was manually identified by admin
        filename: Metadata filename (default: oneirodex.json)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"💾 [LOCAL METADATA] Starting write process for IGDB ID {igdb_id}")
        logger.info(f"💾 [LOCAL METADATA] Target path: {full_disk_path}")
        logger.info(f"💾 [LOCAL METADATA] Filename: {filename}")

        # Security check
        if current_app:
            allowed_bases = get_allowed_base_directories(current_app)
            if not allowed_bases:
                logger.error(f"🚫 [LOCAL METADATA] No allowed base directories configured for {full_disk_path}")
                return False

            is_safe, error_message = is_safe_path(full_disk_path, allowed_bases)
            if not is_safe:
                logger.error(f"🚫 [LOCAL METADATA] Security: Cannot write to unsafe path {full_disk_path}: {error_message}")
                return False
            logger.info("✅ [LOCAL METADATA] Security check passed")

        # Check if path exists and is directory
        if not os.path.exists(full_disk_path):
            logger.error(f"🚫 [LOCAL METADATA] Path does not exist: {full_disk_path}")
            return False
        if not os.path.isdir(full_disk_path):
            logger.error(f"🚫 [LOCAL METADATA] Path is not a directory: {full_disk_path}")
            return False
        logger.info("✅ [LOCAL METADATA] Path exists and is a directory")

        # Build metadata object
        metadata = {
            "igdb_id": int(igdb_id),
            "identified_at": datetime.now(timezone.utc).isoformat(),
            "manually_verified": bool(manually_verified),
            "version": "1.0"
        }

        # Add optional fields
        if game_title:
            metadata["title"] = sanitize_string_input(game_title, 255)
            logger.info(f"💾 [LOCAL METADATA] Game title: {game_title}")

        # Write to file
        metadata_path = os.path.join(full_disk_path, filename)
        logger.info(f"💾 [LOCAL METADATA] Full metadata path: {metadata_path}")

        # A planted ``oneirodex.json -> /x`` must not be overwritten with this
        # JSON. Refuse a link that is already there, and a target that would
        # land outside the game folder. The link can also appear after this
        # check, so the write itself never follows one (see _replace_with_json).
        if os.path.islink(metadata_path) or not is_path_within(full_disk_path, metadata_path):
            logger.error(f"🚫 [LOCAL METADATA] Refusing to write metadata through a link or outside {full_disk_path}")
            return False

        _replace_with_json(metadata_path, metadata)

        # Verify the file was created
        if os.path.exists(metadata_path):
            file_size = os.path.getsize(metadata_path)
            logger.info(f"✅✅✅ [LOCAL METADATA] SUCCESS! File written to: {metadata_path}")
            logger.info(f"✅ [LOCAL METADATA] File size: {file_size} bytes")
            logger.info(f"✅ [LOCAL METADATA] IGDB ID {igdb_id} saved for game: {game_title or 'Unknown'}")
        else:
            logger.error(f"🚫 [LOCAL METADATA] File was not created at: {metadata_path}")
            return False

        return True

    except PermissionError as e:
        logger.error(f"🚫 [LOCAL METADATA] Permission denied writing to {full_disk_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"🚫 [LOCAL METADATA] Error writing local metadata to {full_disk_path}: {e}")
        return False


def has_local_metadata(full_disk_path, filename=DEFAULT_METADATA_FILENAME):
    """
    Quick check if local metadata file exists.

    Args:
        full_disk_path: Full path to game folder
        filename: Metadata filename. Also checks legacy oneirodex.json when
            the primary filename is missing.

    Returns:
        bool: True if metadata file exists
    """
    try:
        if not os.path.isdir(full_disk_path):
            return False
        return _resolve_metadata_path(full_disk_path, filename) is not None
    except Exception:
        return False


def delete_local_metadata(full_disk_path, filename=DEFAULT_METADATA_FILENAME):
    """
    Delete local metadata file from game folder.

    Args:
        full_disk_path: Full path to game folder
        filename: Metadata filename

    Returns:
        bool: True if deleted or didn't exist, False on error
    """
    try:
        metadata_path = os.path.join(full_disk_path, filename)
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
            logger.info(f"Deleted local metadata: {metadata_path}")
        # Also remove legacy sidecar if present
        if filename != LEGACY_METADATA_FILENAME:
            legacy_path = os.path.join(full_disk_path, LEGACY_METADATA_FILENAME)
            if os.path.exists(legacy_path):
                os.remove(legacy_path)
                logger.info(f"Deleted legacy local metadata: {legacy_path}")
        return True
    except Exception as e:
        logger.error(f"Error deleting local metadata from {full_disk_path}: {e}")
        return False


def get_local_cover_path(full_disk_path):
    """
    Get path to local cover image if it exists.

    Checks for (in priority order):
    1. cover.jpg
    2. cover.png
    3. folder.jpg
    4. folder.png

    Args:
        full_disk_path: Full path to game folder

    Returns:
        str or None: Absolute path to cover image, or None if not found
    """
    try:
        if not os.path.isdir(full_disk_path):
            return None

        # Check each filename in priority order
        cover_filenames = ['cover.jpg', 'cover.png', 'folder.jpg', 'folder.png']

        for filename in cover_filenames:
            cover_path = os.path.join(full_disk_path, filename)
            # ``cover.jpg -> /etc/whatever`` would otherwise be served by
            # send_file to any member who may see the game.
            if is_plain_file_within(full_disk_path, cover_path):
                logger.info(f"📷 Found local cover: {cover_path}")
                return cover_path

        return None

    except Exception as e:
        logger.error(f"Error checking for local cover in {full_disk_path}: {e}")
        return None


def get_local_screenshots(full_disk_path):
    """
    Get paths to local screenshot images.

    Looks for files matching pattern:
    - screenshot-1.jpg, screenshot-2.jpg, etc.
    - screenshot-1.png, screenshot-2.png, etc.

    Args:
        full_disk_path: Full path to game folder

    Returns:
        list: List of absolute paths to screenshot images (sorted by number)
    """
    try:
        if not os.path.isdir(full_disk_path):
            return []

        screenshots = []

        # Check for numbered screenshots (screenshot-1.jpg through screenshot-99.jpg)
        for i in range(1, 100):
            for ext in ['.jpg', '.png']:
                filename = f'screenshot-{i}{ext}'
                screenshot_path = os.path.join(full_disk_path, filename)
                if is_plain_file_within(full_disk_path, screenshot_path):
                    screenshots.append(screenshot_path)
                    break  # Found jpg or png, don't check other extension

        if screenshots:
            logger.info(f"📷 Found {len(screenshots)} local screenshots in {full_disk_path}")

        return screenshots

    except Exception as e:
        logger.error(f"Error checking for local screenshots in {full_disk_path}: {e}")
        return []


def has_local_images(full_disk_path):
    """
    Quick check if folder has any local images (cover or screenshots).

    Args:
        full_disk_path: Full path to game folder

    Returns:
        bool: True if local cover or screenshots exist
    """
    return (get_local_cover_path(full_disk_path) is not None or
            len(get_local_screenshots(full_disk_path)) > 0)


def check_write_permissions(directory_path, test_filename='_oneirodex_write_test.tmp'):
    """
    Check if we have write permissions to a directory by attempting to create a test file.

    Args:
        directory_path: Path to directory to check
        test_filename: Name of temporary test file

    Returns:
        tuple: (bool, str) - (success, error_message)
            - (True, "") if write permissions are OK
            - (False, "error message") if write fails
    """
    try:
        # Check if directory exists
        if not os.path.exists(directory_path):
            return False, f"Directory does not exist: {directory_path}"

        if not os.path.isdir(directory_path):
            return False, f"Path is not a directory: {directory_path}"

        # Attempt to create a test file
        test_file_path = os.path.join(directory_path, test_filename)

        try:
            # The folder is somebody's share: a planted ``_oneirodex_write_test.tmp
            # -> /x`` must not be opened for writing (it would truncate /x).
            # O_EXCL refuses an existing name, link or not. A name that is
            # already there is a leftover of an interrupted check, or a link;
            # unlink removes either without following it.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
            try:
                fd = os.open(test_file_path, flags, 0o666)
            except FileExistsError:
                os.unlink(test_file_path)
                fd = os.open(test_file_path, flags, 0o666)
            with os.fdopen(fd, 'w') as f:
                f.write('test')

            # Clean up test file
            if os.path.exists(test_file_path):
                os.remove(test_file_path)

            logger.info(f"✅ [PERMISSIONS] Write permission check passed for: {directory_path}")
            return True, ""

        except PermissionError as e:
            error_msg = f"Permission denied: Cannot write to {directory_path}"
            logger.error(f"🚫 [PERMISSIONS] {error_msg}: {e}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Write test failed for {directory_path}: {str(e)}"
            logger.error(f"🚫 [PERMISSIONS] {error_msg}")
            return False, error_msg

    except Exception as e:
        error_msg = f"Permission check failed: {str(e)}"
        logger.error(f"🚫 [PERMISSIONS] {error_msg}")
        return False, error_msg


def check_library_write_permissions(library_path):
    """
    Check write permissions for a library by testing the root directory
    and optionally some subdirectories.

    Args:
        library_path: Root path of the library to scan

    Returns:
        tuple: (bool, list) - (all_ok, failed_paths)
            - all_ok: True if all checks passed
            - failed_paths: List of paths that failed with error messages
    """
    failed_paths = []

    # Check root directory
    success, error = check_write_permissions(library_path)
    if not success:
        failed_paths.append({
            'path': library_path,
            'error': error
        })

    # Try to check a few subdirectories (first level only)
    try:
        if os.path.isdir(library_path):
            subdirs = [d for d in os.listdir(library_path)
                      if os.path.isdir(os.path.join(library_path, d))]

            # Test up to 3 subdirectories as a sample
            for subdir in subdirs[:3]:
                subdir_path = os.path.join(library_path, subdir)
                success, error = check_write_permissions(subdir_path)
                if not success:
                    failed_paths.append({
                        'path': subdir_path,
                        'error': error
                    })
    except Exception as e:
        logger.warning(f"⚠️ [PERMISSIONS] Could not check subdirectories: {e}")

    return len(failed_paths) == 0, failed_paths
