"""Process-shared admission lock for ROM expansion on one library volume."""

from __future__ import annotations

import os
import stat
from pathlib import Path


_LOCK_FILENAME = ".rom-expansion.lock"


def try_acquire_rom_expansion_lock(cache_root: str | os.PathLike[str]) -> int | None:
    """Acquire the shared-volume ROM slot without waiting.

    The descriptor is the lock handle and must be released with
    :func:`release_rom_expansion_lock`. Keep the lock file in place: unlinking
    it while another process has it open can split the lock across inodes.
    """
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(Path(cache_root) / _LOCK_FILENAME, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("ROM expansion lock is not a regular file")

        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(fd)
                return None
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return None

        return fd
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def release_rom_expansion_lock(fd: int) -> None:
    """Release a descriptor returned by :func:`try_acquire_rom_expansion_lock`."""
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
