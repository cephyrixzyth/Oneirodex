"""
Zipstream integration module for streaming ZIP file generation.
Provides memory-efficient streaming ZIP creation for multi-file games.
"""

import os
import asyncio
import time
import zipfile
from typing import AsyncGenerator, Iterator, Tuple, Optional, Dict, Any
import zipstream
from oneirodex.utils.security import is_plain_file_within, is_safe_path, open_plain_file_within
from oneirodex.utils.event_logging import log_system_event


def _iter_folder_files(source_path: str, excluded_folders, real_root: Optional[str] = None) -> Iterator[str]:
    """Yield the regular files of a game folder that may be downloaded.

    A game folder is scanned content, so it can hold ``game.bin -> /etc/x``.
    ``zs.write`` would follow that link and stream the target into the zip for
    whoever asked for the download. Symlinks (to files or folders) are skipped,
    and so is anything whose realpath is not under the folder itself.

    *real_root* is the folder's resolved path, taken as given. When the caller
    has already resolved and vetted the folder it passes that here, so a folder
    swapped for a link afterwards fails the per-file checks instead of moving
    the boundary to the link's target; without it the folder is resolved once.
    """
    excluded = {name.lower() for name in excluded_folders}
    if real_root is None:
        real_root = os.path.realpath(source_path)
    for root, dirs, files in os.walk(source_path):
        # Excluded folders are pruned, and so are linked folders: os.walk does
        # not descend into them, but they should not look like content either.
        dirs[:] = [
            d for d in dirs
            if d.lower() not in excluded and not os.path.islink(os.path.join(root, d))
        ]
        for file in files:
            if file.lower() in ('oneirodex.json', 'oneirodex.json'):
                continue
            file_path = os.path.join(root, file)
            if not is_plain_file_within(real_root, file_path, base_is_resolved=True):
                continue
            yield file_path


#: What ``zipfile`` clamps to when ``strict_timestamps=False``: the DOS date
#: field cannot say anything before 1980 or after 2107.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_ZIP_LAST = (2107, 12, 31, 23, 59, 59)


def zip_date_time(mtime: float) -> Tuple[int, int, int, int, int, int]:
    """The ZIP ``date_time`` for a file mtime, clamped to what the format can hold.

    ``ZipInfo`` raises ``ValueError`` for anything before 1980, and extracted
    dumps often carry an mtime of 0, which would fail a whole folder download.
    Clamps the way ``zipfile`` does with ``strict_timestamps=False``.
    """
    try:
        stamp = time.localtime(mtime)[0:6]
    except (OverflowError, OSError, ValueError):
        # Windows refuses negative times outright, and a huge one overflows.
        return _ZIP_EPOCH if mtime < 0 else _ZIP_LAST
    if stamp < _ZIP_EPOCH:
        return _ZIP_EPOCH
    if stamp > _ZIP_LAST:
        return _ZIP_LAST
    return stamp


class _ModePreservingZipFile(zipstream.ZipFile):
    """``zipstream.ZipFile`` that keeps each file's Unix mode when members are
    streamed from our own iterator.

    ``write_iter`` stamps every member ``rw-------``; ``write`` (which stats the
    path itself) records the real mode, so a downloaded Linux game keeps its
    executable bits. ``_writecheck`` runs once per member just after its
    ``ZipInfo`` is built and before the header goes out, which is the one place
    to correct the attributes without touching the library's private methods.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._modes: Dict[str, int] = {}

    def write_vetted(self, arcname: str, size: int, mtime: float, mode: int, chunks) -> None:
        """Queue *chunks* as member *arcname*, carrying the file's size, mtime and mode."""
        # Same normalisation ``zipstream`` applies before it builds the ZipInfo.
        member = os.path.normpath(os.path.splitdrive(arcname)[1])
        while member[:1] in (os.sep, os.altsep):
            member = member[1:]
        self._modes[zipfile.ZipInfo(member).filename] = mode
        self.write_iter(arcname, chunks, buffer_size=size, date_time=zip_date_time(mtime))

    def _writecheck(self, zinfo):
        super()._writecheck(zinfo)
        mode = self._modes.get(zinfo.filename)
        if mode is not None:
            zinfo.external_attr = (mode & 0xFFFF) << 16


def _stream_vetted_file(real_root: str, path: str, chunk_size: int = 65536) -> Iterator[bytes]:
    """Yield a game file's bytes, vetting it when the download reaches it.

    ``_iter_folder_files`` vets every file during the walk, but zipstream only
    queues the path; the file is opened chunks later, minutes later for a big
    game. Someone with write access to the share could flip ``big.bin`` to a
    link at ``/app/.env`` in that window. So the open happens here, through
    ``open_plain_file_within``, which checks the descriptor it got rather than
    the path it was given. A file that stopped being a plain file under the
    folder fails the download instead of streaming whatever it points to now.

    *real_root* is compared as given, never resolved again: the folder is vetted
    once, when the download starts, so a folder swapped for a link later reads
    as "outside" instead of redefining what "inside" means.
    """
    with open_plain_file_within(real_root, path, base_is_resolved=True) as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                return
            yield block


async def async_generate_zipstream_chunks(
    source_path: str, 
    chunk_size: int = 65536,
    compression_level: int = 0,
    enable_zip64: bool = True,
    excluded_folders: Optional[list] = None,
    *,
    source_is_resolved: bool = False
) -> AsyncGenerator[bytes, None]:
    """
    Async generator that creates ZIP chunks using zipstream-new for memory-efficient streaming.
    
    Args:
        source_path: Path to the source file or directory to compress
        chunk_size: Size of each chunk in bytes (default 64KB)
        compression_level: ZIP compression level (0=stored, 9=maximum)
        enable_zip64: Enable ZIP64 extensions for large files
        excluded_folders: List of folder names to exclude (e.g., ['updates', 'extras'])
        source_is_resolved: *source_path* is already ``realpath``-resolved and
            vetted by the caller; it is then the boundary every file is compared
            against, instead of being resolved again here (see ``_iter_folder_files``)
        
    Yields:
        bytes: ZIP file chunks
        
    Raises:
        FileNotFoundError: If source path doesn't exist
        PermissionError: If source path cannot be read
        IOError: If other I/O errors occur during processing
    """
    
    if excluded_folders is None:
        excluded_folders = ['updates', 'extras']
    
    try:
        # Verify source path exists
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        
        # Initialize zipstream with proper API and ZIP64 support
        from zipfile import ZIP_STORED, ZIP_DEFLATED
        compression_method = ZIP_DEFLATED if compression_level > 0 else ZIP_STORED
        zs = _ModePreservingZipFile(mode='w', compression=compression_method, allowZip64=enable_zip64)
        
        # Resolved once, here or by the caller: every file is compared against
        # this string, so nothing renamed after this point can move the boundary.
        real_root = source_path if source_is_resolved else os.path.realpath(source_path)

        # Add files to ZIP stream
        if os.path.isfile(source_path):
            # Single file: pinned to where it resolves now, so a link swapped in
            # afterwards is refused when the file is opened, not followed.
            info = os.lstat(real_root)
            zs.write_vetted(
                os.path.basename(source_path),
                info.st_size,
                info.st_mtime,
                info.st_mode,
                _stream_vetted_file(os.path.dirname(real_root), real_root),
            )
        else:
            # Directory - walk and add files while excluding certain folders
            for file_path in _iter_folder_files(source_path, excluded_folders, real_root=real_root):
                # Create relative path for archive
                rel_path = os.path.relpath(file_path, source_path)
                try:
                    info = os.lstat(file_path)
                except OSError:
                    continue  # gone since the walk
                zs.write_vetted(
                    rel_path,
                    info.st_size,
                    info.st_mtime,
                    info.st_mode,
                    _stream_vetted_file(real_root, file_path),
                )
        
        # Generate chunks asynchronously
        for chunk in zs:
            if chunk:
                yield chunk
                # Allow other coroutines to run
                await asyncio.sleep(0)
                
    except Exception as e:
        log_system_event(f"Error in zipstream generation for {source_path}: {str(e)}")
        raise


def should_use_zipstream(source_path: str) -> bool:
    """
    Determine if zipstream should be used for the given source path.
    
    Args:
        source_path: Path to check
        
    Returns:
        bool: True if zipstream should be used, False for direct download
    """
    
    if not os.path.exists(source_path):
        return False
    
    # Use direct download for single files
    if os.path.isfile(source_path):
        return False
    
    # Use zipstream for directories (multi-file games)
    if os.path.isdir(source_path):
        return True
    
    return False


def get_zipstream_info(source_path: str, download_filename: str) -> Dict[str, Any]:
    """
    Generate metadata for zipstream downloads.
    
    Args:
        source_path: Path to the source files
        download_filename: Desired filename for the download
        
    Returns:
        dict: Metadata dictionary for the streaming download
    """
    
    return {
        'source_path': source_path,
        'download_filename': download_filename,
        'content_type': 'application/zip',
        'streaming': True,
        'estimated_size': estimate_zip_size(source_path)
    }


def estimate_zip_size(source_path: str) -> Optional[int]:
    """
    Estimate the final ZIP file size based on source content.
    This is a rough estimation for progress indicators.
    
    Args:
        source_path: Path to calculate size for
        
    Returns:
        int: Estimated size in bytes, or None if cannot estimate
    """
    
    try:
        if os.path.isfile(source_path):
            # For single files, ZIP overhead is minimal
            return int(os.path.getsize(source_path) * 1.05)  # 5% overhead estimate
        
        elif os.path.isdir(source_path):
            total_size = 0
            file_count = 0
            
            for file_path in _iter_folder_files(source_path, ['updates', 'extras']):
                try:
                    total_size += os.path.getsize(file_path)
                    file_count += 1
                except (OSError, IOError):
                    # Skip files we can't read
                    continue
            
            if file_count == 0:
                return None
            
            # Estimate ZIP overhead based on file count and directory structure
            # Stored compression (level 0) adds minimal overhead
            overhead = file_count * 100  # ~100 bytes per file for headers
            return total_size + overhead
    
    except Exception as e:
        log_system_event(f"Error estimating ZIP size for {source_path}: {str(e)}")
        return None


async def validate_zipstream_path(source_path: str, allowed_bases: list) -> Tuple[bool, str]:
    """
    Validate that the source path is safe for zipstream processing.
    
    Args:
        source_path: Path to validate
        allowed_bases: List of allowed base directories
        
    Returns:
        tuple: (is_valid, error_message)
    """
    
    try:
        # Use existing security validation
        is_safe, error_message = is_safe_path(source_path, allowed_bases)
        if not is_safe:
            return False, error_message
        
        # Additional checks for zipstream
        if not os.path.exists(source_path):
            return False, "Source path does not exist"
        
        # Check if we have read permissions
        if not os.access(source_path, os.R_OK):
            return False, "Insufficient permissions to read source path"
        
        return True, ""
        
    except Exception as e:
        return False, f"Path validation error: {str(e)}"


def is_streaming_download(download_info: dict) -> bool:
    """
    Check if a download uses streaming based on its metadata.
    
    Args:
        download_info: Download metadata dictionary
        
    Returns:
        bool: True if this is a streaming download
    """
    
    return download_info.get('streaming', False)