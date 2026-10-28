"""Background workers must not share the spawning request's session.

Six route handlers used to start daemon threads with
`@copy_current_request_context`. That hands the thread the request's context,
and Flask-SQLAlchemy scopes `db.session` to the application context — so the
worker and the request shared one `Session`, which is not thread-safe, while
the worker outlived the request by design (a library deletion walks every game
in the library).

The failure is the kind that shows up somewhere else entirely. It was first
caught in this suite: a leaked library-deletion worker was still deleting one
test's fixtures while later test files ran, producing ObjectDeletedError on
unrelated rows in unrelated files.

These tests pin the property that fixes it — a worker gets its own session —
rather than the mechanism, so a future refactor is free to change how as long
as the isolation holds.
"""

import threading

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Library
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.background import run_in_background

# Spins real OS threads and joins them with multi-second timeouts; historically
# a source of cross-file pollution when a leaked worker outlived its test. Kept
# out of the fast marker-based CI core (`-m "not integration"`).
pytestmark = pytest.mark.integration


def test_worker_gets_its_own_session(app, db_session):
    """The property the whole change exists for."""
    seen = {}

    def _work():
        # `db.session` is a scoped_session proxy; calling it returns the real
        # Session for the current scope. Comparing the proxies would compare
        # one shared object and prove nothing.
        seen['worker_session'] = db.session()
        seen['thread'] = threading.current_thread().name

    with app.app_context():
        caller_session = db.session()
        thread = run_in_background(app, _work, name='od-test-worker')
        thread.join(timeout=10)

    assert not thread.is_alive(), 'worker did not finish'
    assert seen['worker_session'] is not caller_session
    assert seen['thread'] == 'od-test-worker'


def test_worker_has_an_app_context(app):
    """Without one, every `current_app` and `db.session` use raises."""
    from flask import current_app, has_app_context

    seen = {}

    def _work():
        seen['has_context'] = has_app_context()
        seen['app_name'] = current_app.name

    thread = run_in_background(app, _work, name='od-test-context')
    thread.join(timeout=10)

    assert seen['has_context'] is True
    assert seen['app_name'] == app.name


def test_worker_can_commit_without_the_caller(app, db_session):
    """A worker's write lands, and on its own session.

    This is what the six converted call sites all do — the deletion worker
    commits repeatedly while walking a library — so it is worth asserting
    directly rather than inferring it from session identity alone.
    """
    with app.app_context():
        library = Library(name='Worker Commit Library', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.commit()
        library_uuid = library.uuid

    def _work():
        row = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()
        row.name = 'Renamed By Worker'
        db.session.commit()

    thread = run_in_background(app, _work, name='od-test-commit')
    thread.join(timeout=10)

    with app.app_context():
        row = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()
        assert row.name == 'Renamed By Worker'
        db.session.delete(row)
        db.session.commit()


def test_worker_failure_is_logged_not_silent(app, caplog):
    """A daemon thread that dies prints a bare traceback and no context.

    Naming the task in a log record is the difference between "something threw
    in a thread" and knowing which route started it.
    """
    def _work():
        raise RuntimeError('worker exploded')

    with caplog.at_level('ERROR', logger='oneirodex.utils.background'):
        thread = run_in_background(app, _work, name='od-test-boom')
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert any('od-test-boom' in record.getMessage() for record in caplog.records)


def test_worker_failure_does_not_escape_to_the_caller(app):
    """The caller has already returned a response; it cannot handle this."""
    def _work():
        raise RuntimeError('worker exploded')

    # No pytest.raises: a throw here would mean the exception crossed back.
    thread = run_in_background(app, _work, name='od-test-contained')
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_library_deletion_worker_deletes_metadata_but_preserves_rom(app, no_savepoint_db, tmp_path):
    """End-to-end through the real worker, on its own session.

    Nothing covered this before: the route test asserts only that the job is
    accepted, and its own comment conceded "the actual deletion would be tested
    in integration tests". That was survivable while the worker shared the
    request's session — running it in a test would have been the very hazard
    being fixed — and is worth having now that it does not.

    Bucket E (docs/dev/test-harness-2026-09-10.md): `delete_library_background`
    runs on a real daemon thread that pushes its own `app.app_context()`
    (`run_in_background`), so it needs its own DBAPI connection from the
    engine's pool — exactly what `run_in_background` exists to guarantee.
    `db_session`'s single shared connection can't serve two threads at once,
    so this test opts out with `no_savepoint_db` instead.
    """
    from oneirodex.models import Game
    from oneirodex.routes_admin_ext.library_delete import (
        delete_library_background,
        deletion_progress,
    )

    with app.app_context():
        library = Library(name='Doomed Library', platform=LibraryPlatform.PCWIN)
        db.session.add(library)
        db.session.commit()
        library_uuid = library.uuid

        rom_path = tmp_path / 'synthetic-game.nes'
        rom_path.write_bytes(b'oneirodex test rom')
        game = Game(
            name='Doomed Game',
            library_uuid=library_uuid,
            full_disk_path=str(rom_path),
        )
        db.session.add(game)
        db.session.commit()
        game_uuid = game.uuid

        # The route seeds this before handing off; the worker only updates it.
        job_id = 'test-delete-job'
        deletion_progress[job_id] = {
            'status': 'initializing',
            'message': '',
            'current': 0,
            'total': 0,
        }

        thread = delete_library_background(library_uuid, job_id)

    thread.join(timeout=30)
    assert not thread.is_alive(), 'deletion worker did not finish'

    assert deletion_progress[job_id]['status'] == 'completed', deletion_progress[job_id]

    with app.app_context():
        assert db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first() is None
        assert db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first() is None
        assert rom_path.read_bytes() == b'oneirodex test rom'

    deletion_progress.pop(job_id, None)


@pytest.mark.parametrize(
    'module_name',
    [
        'oneirodex.routes_admin_ext.scan_management',
        'oneirodex.routes_apis.game',
        'oneirodex.routes_games_ext.add',
        'oneirodex.routes_games_ext.edit',
    ],
)
def test_route_modules_no_longer_copy_the_request_context(module_name):
    """Guards the regression at its source.

    `copy_current_request_context` is the one construct that reintroduces the
    shared session, and it reads as harmless. Asserting on the source is blunt,
    but it is the only check that fails when someone adds a seventh worker the
    old way — the race itself is timing-dependent and will not fail a test run
    reliably.
    """
    import importlib
    import inspect

    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    assert '@copy_current_request_context' not in source, (
        f'{module_name} spawns work with the request context again — '
        'use utils.background.run_in_background so the worker owns its session'
    )
