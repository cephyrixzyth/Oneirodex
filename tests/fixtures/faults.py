"""Test-only deterministic seams around real save I/O and transactions."""
from contextlib import contextmanager
from dataclasses import dataclass
import errno

from sqlalchemy.exc import OperationalError


@dataclass
class Fault:
    hits: int = 0

    def call(self, original, error, *args, **kwargs):
        if self.hits == 0:
            self.hits += 1
            raise error
        return original(*args, **kwargs)


class _Override:
    def __init__(self, target, **overrides):
        self._target = target
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._target, name)


@contextmanager
def fail_next_save_io(monkeypatch, operation, *, session=None):
    """Fail one selected operation; leave all other real adapters in place.

    Restore every replacement on exit. OS replacements are local to the save
    module, so unrelated application code and the test runner keep real I/O.
    The commit seam targets pending save changes, leaving the real bearer
    last-used commit intact. This is not physical disk/connection exhaustion.
    """
    from oneirodex.utils import emulator_saves
    from oneirodex.models import EmulatorSave

    if operation not in {'write', 'file_fsync', 'replace', 'directory_fsync', 'commit'}:
        raise ValueError('Unknown save fault operation')
    fault = Fault()
    error = OSError(errno.ENOSPC, 'synthetic-private-canary')
    real_os = emulator_saves.os
    with monkeypatch.context() as scope:
        if operation == 'write':
            @contextmanager
            def fdopen(*args, **kwargs):
                with real_os.fdopen(*args, **kwargs) as handle:
                    yield _Override(
                        handle,
                        write=lambda *a, **kw: fault.call(handle.write, error, *a, **kw),
                    )

            scope.setattr(emulator_saves, 'os', _Override(real_os, fdopen=fdopen))
        elif operation in {'file_fsync', 'replace'}:
            attribute = 'fsync' if operation == 'file_fsync' else 'replace'
            original = getattr(real_os, attribute)
            scope.setattr(emulator_saves, 'os', _Override(
                real_os,
                **{attribute: lambda *a, **kw: fault.call(original, error, *a, **kw)},
            ))
        elif operation == 'directory_fsync':
            original = emulator_saves._fsync_directory
            scope.setattr(
                emulator_saves, '_fsync_directory',
                lambda *a, **kw: fault.call(original, error, *a, **kw),
            )
        else:
            if session is None:
                raise ValueError('Commit faults require the real test session')
            original = session.commit
            error = OperationalError('synthetic-save-commit', {}, error)

            def commit(*args, **kwargs):
                save_pending = any(
                    isinstance(row, EmulatorSave) for row in (*session.new, *session.dirty)
                )
                if save_pending:
                    return fault.call(original, error, *args, **kwargs)
                return original(*args, **kwargs)

            scope.setattr(session, 'commit', commit)
        yield fault
