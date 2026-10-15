"""Daemon threads that own their database session.

Why this exists
---------------
Six request handlers used to spawn work like this::

    @copy_current_request_context
    def worker():
        ...  # touches db.session

    Thread(target=worker, daemon=True).start()

`copy_current_request_context` hands the thread the *request's* context, and
Flask-SQLAlchemy scopes `db.session` to the application context — so the worker
and the request that spawned it shared one `Session`. A SQLAlchemy `Session` is
not thread-safe, and these workers outlive the request by design: a library
deletion walks every game in the library, an image refresh calls out to IGDB.

The result is two threads issuing statements on one connection, plus the
request's own teardown calling `session.remove()` underneath a worker still
using it. It fails the way concurrency bugs do — rarely, somewhere else, and
looking like anything but the cause. It surfaced first in the test suite, where
a leaked deletion worker was deleting another test's fixtures mid-run; the same
race is reachable in production from any of the six routes.

Giving the worker its own application context gives it its own session, which
is the actual fix. That is the shape `scan_queue._start_job_thread` and the
pollers already use; this just puts it in one place so a seventh call site
cannot get it wrong.

Using it
--------
Pass plain values, never ORM instances. An object loaded in the request belongs
to the request's session; touching it from the worker either re-attaches it to
the wrong session or raises `DetachedInstanceError`. Snapshot the ids you need
and re-fetch inside the worker::

    job_id = job.id
    run_in_background(current_app._get_current_object(), _do_work, job_id)

There is deliberately no request context in the worker. Nothing that runs here
needs one — `refresh_images_in_background` already guards its `flash` calls with
`has_request_context()` — and a worker that thinks it is inside a request will
happily try to write to a session that was sent to the browser long ago.
"""

from __future__ import annotations

import logging
from threading import Thread
from typing import Any, Callable

logger = logging.getLogger(__name__)


def run_in_background(
    app,
    func: Callable[..., Any],
    *args: Any,
    name: str | None = None,
    database_scope=None,
    **kwargs: Any,
) -> Thread:
    """Run a daemon task with an isolated native DB scope or legacy app context.

    :param app: the real application object — ``current_app._get_current_object()``
        from inside a request. The proxy itself is bound to the calling
        thread's context and is useless in the worker.
    :param name: thread name, for logs and stack dumps. Worth setting: an
        unnamed daemon thread in a traceback tells you nothing about which
        route started it.
    :returns: the started thread, so callers (and tests) can join it.
    """

    def _worker() -> None:
        def invoke(*, legacy_database=None):
            try:
                func(*args, **kwargs)
            except Exception:
                # A daemon thread that dies takes its work with it and prints a
                # bare traceback to stderr with no clue which request started
                # it. Log it against a named task instead.
                logger.exception(
                    'Background task %s failed',
                    name or getattr(func, '__name__', repr(func)),
                )
            finally:
                if legacy_database is not None:
                    # Flask's app context teardown also removes this scoped
                    # session; doing it here makes worker ownership explicit.
                    legacy_database.session.remove()

        if database_scope is None:
            # Imported here rather than at module scope so the native worker
            # path does not load Flask or Jinja.
            from oneirodex.runtime_native.db_session import native_db as db

            with app.app_context():
                invoke(legacy_database=db)
        else:
            with database_scope(app):
                invoke()

    thread = Thread(target=_worker, daemon=True, name=name)
    thread.start()
    return thread
