"""Small JSON documents on the library volume, written without torn or lost updates.

Several features keep a per-member or per-game JSON file there. Rewriting such a
file in place loses it when the process dies mid-write, and a lock that lives
inside one process does not stop a second worker from overwriting the first.

``write_json_atomic`` replaces the document in one step, so a reader sees either
the old file or the new one. ``locked`` is a process-shared lock for a
read-modify-write; hold it around the read as well as the write.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import stat
import tempfile
import threading
import time
from typing import Any, Iterator

_LOCK_FILENAME = '.json-store.lock'
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
# A filesystem without advisory locks still gets the atomic replace.
_LOCK_UNSUPPORTED = {errno.ENOLCK, errno.ENOSYS, getattr(errno, 'EOPNOTSUPP', errno.ENOSYS)}


def _thread_lock(lock_path: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(lock_path, threading.Lock())


def _try_lock(fd: int) -> bool:
    if os.name == 'nt':
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.write(fd, b'\0')
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock(fd: int) -> None:
    if os.name == 'nt':
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(path: str, *, timeout: float = 15.0) -> Iterator[None]:
    """Hold the process-shared lock for the folder that contains ``path``.

    One lock file per folder: the documents are small and updates are brief, so
    a coarse lock costs nothing and leaves no per-document lock files behind.
    The lock file stays in place; unlinking it while another process has it
    open would split the lock across two inodes.
    """
    folder = os.path.dirname(os.path.abspath(path))
    lock_path = os.path.join(folder, _LOCK_FILENAME)
    with _thread_lock(lock_path):
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        held = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError('JSON store lock is not a regular file')
            deadline = time.monotonic() + max(0.0, timeout)
            try:
                while not _try_lock(fd):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Timed out waiting for the JSON store lock')
                    time.sleep(0.01)
                held = True
            except OSError as exc:
                if isinstance(exc, TimeoutError) or exc.errno not in _LOCK_UNSUPPORTED:
                    raise
            yield
        finally:
            try:
                if held:
                    _unlock(fd)
            finally:
                os.close(fd)


def write_json_atomic(
    path: str,
    payload: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = True,
    trailing_newline: bool = False,
) -> None:
    """Replace ``path`` with ``payload`` in one step, or leave it untouched."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mode = 0o644
    fd, staged = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=indent, ensure_ascii=ensure_ascii)
            if trailing_newline:
                handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != 'nt':
            os.chmod(staged, mode)
        os.replace(staged, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(staged)
        raise
