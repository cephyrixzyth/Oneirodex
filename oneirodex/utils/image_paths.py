"""Safe filesystem resolution for stored library image URLs."""

from pathlib import Path, PurePosixPath, PureWindowsPath


def image_path_under_save_dir(image_url, image_save_path):
    """Return an image entry under IMAGE_SAVE_PATH, or None if it escapes.

    Image rows normally store generated filenames, while older rows may store
    the public ``/static/library/images/...`` URL. Parent directories are
    resolved to catch symlink/junction escapes. The final entry stays lexical
    so unlinking a symlink removes the link itself rather than its target.
    """
    if not isinstance(image_url, str) or not image_url.strip():
        return None

    relative_url = image_url.strip().replace('\\', '/')
    if relative_url.startswith('/static/library/images/'):
        relative_url = relative_url[len('/static/library/images/'):]
    elif relative_url.startswith('static/library/images/'):
        relative_url = relative_url[len('static/library/images/'):]
    relative_url = relative_url.lstrip('/')

    posix_path = PurePosixPath(relative_url)
    windows_path = PureWindowsPath(relative_url)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or not posix_path.parts
        or any(part in {'.', '..'} for part in posix_path.parts)
    ):
        return None

    root = Path(image_save_path).resolve()
    target = root.joinpath(*posix_path.parts)
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError:
        return None
    return target
