"""Test-only deterministic provider-return, save-I/O and transaction seams."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
from threading import Event

from sqlalchemy.exc import OperationalError


@dataclass
class Fault:
    hits: int = 0

    def call(self, original, error, *args, **kwargs):
        if self.hits == 0:
            self.hits += 1
            raise error
        return original(*args, **kwargs)


@dataclass
class DelayedProvider:
    """Hold one synthetic provider result until the test permits its return.

    No real request or sleep; the test can commit another request while this
    boundary is held. Release in a finally block before joining its worker.
    """

    result: object = field(repr=False)
    timeout: float = 10
    entered: Event = field(default_factory=Event, repr=False)
    release: Event = field(default_factory=Event, repr=False)

    def __call__(self):
        self.entered.set()
        if not self.release.wait(timeout=self.timeout):
            raise TimeoutError('Controlled provider return was not released')
        return self.result


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
    last-used commit intact. ``commit_ack`` commits for real, then raises to
    simulate a lost success acknowledgement. This does not physically sever
    a database connection or exhaust the disk.
    """
    from oneirodex.utils import emulator_saves
    from oneirodex.models import EmulatorSave

    if operation not in {'write', 'file_fsync', 'replace', 'directory_fsync', 'commit', 'commit_ack'}:
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
                    if operation == 'commit_ack' and fault.hits == 0:
                        original(*args, **kwargs)
                        fault.hits += 1
                        raise error
                    return fault.call(original, error, *args, **kwargs)
                return original(*args, **kwargs)

            scope.setattr(session, 'commit', commit)
        yield fault
