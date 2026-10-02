"""Filesystem size walks + human-size formatting + NFO reading.

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""
import os
import time
from flask import current_app
from oneirodex.utils.security import (
    get_allowed_base_directories,
    is_safe_path,
    open_plain_file_within,
)
from oneirodex.utils.global_settings import global_settings_row

__all__ = [
    "_DEFAULT_FOLDER_SIZE_TIMEOUT_SEC",
    "_excluded_size_folder_names",
    "_path_has_excluded_component",
    "format_size",
    "get_path_size",
    "get_folder_size_in_bytes",
    "get_folder_size_in_bytes_updates",
    "read_first_nfo_content",
]


# Default cap for recursive size walks (NAS/Unraid trees can take minutes otherwise).
_DEFAULT_FOLDER_SIZE_TIMEOUT_SEC = 60

#: Most bytes of an NFO that are read and stored. Real ones are tens of KB of
#: ASCII art; the details page shows the first 10,000 characters anyway.
_NFO_MAX_BYTES = 256 * 1024


def _excluded_size_folder_names(settings) -> set[str]:
    """Lowercased update/extras folder basenames to skip during size walks."""
    names: set[str] = set()
    if not settings:
        return names
    for attr in ('update_folder_name', 'extras_folder_name'):
        value = getattr(settings, attr, None)
        if value and str(value).strip():
            names.add(str(value).strip().lower())
    return names


def _path_has_excluded_component(dirpath: str, root: str, excluded: set[str]) -> bool:
    if not excluded:
        return False
    try:
        rel = os.path.relpath(dirpath, root)
    except ValueError:
        rel = dirpath
    if rel in ('.', ''):
        return False
    return any(part.lower() in excluded for part in rel.replace('\\', '/').split('/'))

def format_size(size_in_bytes):
    """Format file size from bytes to human-readable format."""
    try:
        if size_in_bytes is None:
            return '0 MB'
        units = ['KB', 'MB', 'GB', 'TB', 'PB', 'EB']
        size = size_in_bytes / 1024  # Start with KB
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        return f"{size:.2f} {units[unit_index]}"
    except Exception as e:
        print(f"An error occurred: {e}")
        return '0 MB'


def get_path_size(file_path):
    """Calculate size of a file or directory in bytes (download initiate helper)."""
    try:
        if os.path.isfile(file_path):
            return os.path.getsize(file_path)
        if os.path.isdir(file_path):
            total_size = 0
            for dirpath, _dirnames, filenames in os.walk(file_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except OSError:
                        pass
            return total_size
    except OSError:
        pass
    return 0


def get_folder_size_in_bytes(folder_path, timeout=_DEFAULT_FOLDER_SIZE_TIMEOUT_SEC):
    """Calculate the total size of a folder in bytes.
    
    Args:
        folder_path (str): Path to the folder
        timeout (int): Maximum time in seconds to spend calculating size
    
    Returns:
        int: Total size in bytes, or 0 if there was an error
    """
    try:
        # Validate folder path security (only if we're in an application context)
        try:
            if current_app:
                allowed_bases = get_allowed_base_directories(current_app)
                if not allowed_bases:
                    print(f"Security error: No allowed base directories configured for path: {folder_path}")
                    return 0

                is_safe, error_message = is_safe_path(folder_path, allowed_bases)
                if not is_safe:
                    print(f"Security error: Path validation failed for {folder_path}: {error_message}")
                    return 0
        except RuntimeError:
            # Working outside of application context - skip validation for now
            # This is expected during unit tests
            pass
        # Check if path exists and is accessible
        if not os.path.exists(folder_path):
            print(f"Error: Path does not exist: {folder_path}")
            return 0
            
        # Handle single file case first
        if os.path.isfile(folder_path):
            return os.path.getsize(folder_path)
            
        if not os.access(folder_path, os.R_OK):
            print(f"Error: No read permission for path: {folder_path}")
            return 0

        timeout_sec = max(1, int(timeout or _DEFAULT_FOLDER_SIZE_TIMEOUT_SEC))
        deadline = time.monotonic() + timeout_sec
        total_size = 0
        timed_out = False
        for dirpath, dirnames, filenames in os.walk(folder_path):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                # Skip if we can't access the directory
                if not os.access(dirpath, os.R_OK):
                    print(f"Warning: Skipping inaccessible directory: {dirpath}")
                    dirnames[:] = []
                    continue

                for f in filenames:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    try:
                        fp = os.path.join(dirpath, f)
                        # Skip symlinks unless they point to regular files
                        if os.path.islink(fp):
                            continue
                        total_size += os.path.getsize(fp)
                    except (OSError, IOError) as e:
                        print(f"Error processing file {f}: {e}")
                        continue
            except (OSError, IOError) as e:
                print(f"Error accessing directory {dirpath}: {e}")
                continue
            if timed_out:
                break

        if timed_out:
            print(
                f"Folder size timed out after {timeout_sec}s for {folder_path} "
                f"(partial={total_size} bytes)"
            )

        return max(total_size, 1)

    except Exception as e:
        print(f"Unexpected error calculating folder size: {e}")
        return 0


def get_folder_size_in_bytes_updates(folder_path, timeout=_DEFAULT_FOLDER_SIZE_TIMEOUT_SEC):
    """Calculate folder size excluding update and extras folders."""
    try:
        # Validate folder path security (only if we're in an application context)
        try:
            if current_app:
                allowed_bases = get_allowed_base_directories(current_app)
                if not allowed_bases:
                    print(f"Security error: No allowed base directories configured for path: {folder_path}")
                    return 0

                is_safe, error_message = is_safe_path(folder_path, allowed_bases)
                if not is_safe:
                    print(f"Security error: Path validation failed for {folder_path}: {error_message}")
                    return 0
        except RuntimeError:
            # Working outside of application context - skip validation for now  
            # This is expected during unit tests
            pass
        # Handle single file case first
        if os.path.isfile(folder_path):
            return os.path.getsize(folder_path)
            
        if not os.path.exists(folder_path):
            print(f"Error: Path does not exist: {folder_path}")
            return 0
            
        if not os.access(folder_path, os.R_OK):
            print(f"Error: No read permission for path: {folder_path}")
            return 0

        settings = global_settings_row()
        excluded = _excluded_size_folder_names(settings)
        timeout_sec = max(1, int(timeout or _DEFAULT_FOLDER_SIZE_TIMEOUT_SEC))
        deadline = time.monotonic() + timeout_sec
        total_size = 0
        timed_out = False
        
        for dirpath, dirnames, filenames in os.walk(folder_path):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                # Prune update/extras children so we do not walk those trees.
                if excluded:
                    dirnames[:] = [d for d in dirnames if d.lower() not in excluded]

                # Skip if we can't access the directory
                if not os.access(dirpath, os.R_OK):
                    print(f"Warning: Skipping inaccessible directory: {dirpath}")
                    dirnames[:] = []
                    continue

                if _path_has_excluded_component(dirpath, folder_path, excluded):
                    dirnames[:] = []
                    continue

                for f in filenames:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    try:
                        fp = os.path.join(dirpath, f)
                        if os.path.islink(fp):
                            continue
                        total_size += os.path.getsize(fp)
                    except (OSError, IOError) as e:
                        print(f"Error processing file {f}: {e}")
                        continue

            except (OSError, IOError) as e:
                print(f"Error accessing directory {dirpath}: {e}")
                continue
            if timed_out:
                break

        if timed_out:
            print(
                f"Folder size (excl. updates/extras) timed out after {timeout_sec}s "
                f"for {folder_path} (partial={total_size} bytes)"
            )

        return max(total_size, 1)

    except Exception as e:
        print(f"Unexpected error calculating folder size: {e}")
        return 0


def read_first_nfo_content(full_disk_path):
    """Read the content of the first NFO file found in the given path."""
    
    # Validate folder path security (only if we're in an application context)
    try:
        if current_app:
            allowed_bases = get_allowed_base_directories(current_app)
            if not allowed_bases:
                print(f"Security error: No allowed base directories configured for path: {full_disk_path}")
                return None

            is_safe, error_message = is_safe_path(full_disk_path, allowed_bases)
            if not is_safe:
                print(f"Security error: Path validation failed for {full_disk_path}: {error_message}")
                return None
    except RuntimeError:
        # Working outside of application context - skip validation for now  
        # This is expected during unit tests
        pass
    
    if os.path.isfile(full_disk_path):
        print("Path is a file, not a directory. Skipping NFO scan.")
        return None
        
    try:
        for file in os.listdir(full_disk_path):
            if file.lower().endswith('.nfo'):
                nfo_path = os.path.join(full_disk_path, file)

                try:
                    # The text lands in Game.nfo_content and is shown to every
                    # member, so a ``info.nfo -> /app/.env`` link inside a game
                    # folder must not be followed. The check runs on the opened
                    # descriptor (see open_plain_file_within); a link, a FIFO or
                    # anything outside the folder is skipped, not read.
                    with open_plain_file_within(full_disk_path, nfo_path) as nfo_file:
                        raw = nfo_file.read(_NFO_MAX_BYTES)
                    content = raw.decode('utf-8', errors='ignore')
                    sanitized_content = content.replace('\x00', '')
                    return sanitized_content
                except Exception as e:
                    print(f"Skipping NFO file {nfo_path}: {str(e)}")
                    continue

    except Exception as e:
        print(f"Error accessing directory {full_disk_path}: {str(e)}")
    
    print("No NFO file found")
    return None
