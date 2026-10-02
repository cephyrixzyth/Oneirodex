import pytest
import os
from dotenv import load_dotenv
from database_test_guard import validate_test_database_url as _validate_test_database_url

# Load .env file to ensure TEST_DATABASE_URL is available
load_dotenv()

# CRITICAL: Override DATABASE_URL with TEST_DATABASE_URL for all tests
# This prevents any accidental production database access
test_db_url = _validate_test_database_url(os.getenv('TEST_DATABASE_URL'))
os.environ['DATABASE_URL'] = test_db_url

from oneirodex import create_app, db


def _install_lock_timeout():
    """Make a blocked test connection fail fast and say so.

    Postgres waits for a lock forever by default. Combined with the schema
    setup below, that turned one leaked transaction into a silent, permanent
    stall: no failing test, no timeout, no output — just a pytest process at
    0% CPU that looked "slow" for hours.

    A short `lock_timeout` converts that into an immediate, named error on the
    statement that could not get its lock, which is a bug report instead of a
    mystery. Applied only to test connections; production waits as before,
    where blocking on a real lock is usually the correct behaviour.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, 'connect')
    def _set_timeouts(dbapi_connection, _record):  # noqa: ANN001
        # In autocommit, because `SET` in Postgres is transactional: run inside
        # the implicit transaction and SQLAlchemy's first rollback (which
        # happens whenever a connection returns to the pool) quietly undoes it,
        # leaving exactly the silent hang this is meant to prevent.
        try:
            previous = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            try:
                with dbapi_connection.cursor() as cur:
                    # `lock_timeout` stays short: no healthy test waits on a
                    # lock, so a 15s wait is always a leak somewhere and the
                    # named `LockNotAvailable` on the blocked statement is the
                    # bug report we want.
                    cur.execute("SET SESSION lock_timeout = '15s'")
                    # `idle_in_transaction_session_timeout` is deliberately
                    # generous. `db_session` now holds one outer transaction
                    # open for the whole test (per-test SAVEPOINT isolation),
                    # so between statements the connection is legitimately
                    # "idle in transaction" for as long as the test's own
                    # Python runs — and the slowest single tests
                    # (`test_init_manager_themes`, ~75s of theme-file copying)
                    # would trip a 60s ceiling and have Postgres sever their
                    # own transaction mid-test. 300s clears the slowest test
                    # with headroom while still killing a transaction a
                    # crashed fixture stranded between tests (teardown always
                    # rolls the outer transaction back, so a leak cannot
                    # outlive one test otherwise).
                    cur.execute("SET SESSION idle_in_transaction_session_timeout = '300s'")
            finally:
                dbapi_connection.autocommit = previous
        except Exception:  # noqa: BLE001
            # Non-Postgres or a driver without autocommit — nothing to set.
            pass


_install_lock_timeout()


@pytest.fixture(scope='function')
def app():
    """Create and configure a test app using the test database."""
    # Ensure we have TEST_DATABASE_URL environment variable
    test_db_url = _validate_test_database_url(os.getenv('TEST_DATABASE_URL'))
    
    # Additional check: ensure DATABASE_URL was properly overridden
    current_db_url = os.getenv('DATABASE_URL')
    if current_db_url != test_db_url:
        pytest.fail(
            f"CRITICAL: DATABASE_URL override failed. "
            "This could result in tests running against production database."
        )
    
    # Create app. Under pytest, create_app() auto-selects config.TestConfig,
    # which carries TESTING, WTF_CSRF_ENABLED=False, SERVER_NAME='localhost',
    # APPLICATION_ROOT, PREFERRED_URL_SCHEME, a stable SECRET_KEY, and the
    # TEST_DATABASE_URL URI — the post-construction instance mutations that
    # used to live here (wave A2.6).
    app = create_app()

    # Double-check that the app is using test database
    actual_db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if actual_db_uri != test_db_url:
        pytest.fail(
            f"CRITICAL: App database URI mismatch. "
            "Tests cannot proceed with wrong database configuration."
        )
    
    yield app

# ---------------------------------------------------------------------------
# Per-test database isolation (spec §3.2)
# ---------------------------------------------------------------------------
#
# The schema (DDL) is still built exactly once per process, behind the
# `_SCHEMA_READY` latch. `add_column_if_not_exists` issues a long series of
# `ALTER TABLE`s, each wanting an ACCESS EXCLUSIVE lock; doing that once and
# only once is what keeps the suite from the lock-storm deadlock recorded in
# `docs/dev/archive/test-harness-2026-08-07.md`.
#
# What changed: `db_session` no longer hands out `db.session` directly with no
# teardown. Each test now runs inside a SAVEPOINT nested in an outer
# transaction that is *always rolled back* on teardown — the SQLAlchemy 2.0
# "joining a session into an external transaction" pattern, with
# `join_transaction_mode="create_savepoint"` so a `db.session.commit()` inside
# a test (or a product-code `begin_nested()`, e.g.
# `global_settings_row_or_create`, `metadata_enrichment`, `game_enrich`)
# releases and re-opens a savepoint instead of touching the real transaction.
#
# Net: every test starts from an empty database and leaves nothing behind. The
# old per-run `TRUNCATE` is gone as an isolation mechanism; a single
# process-start `TRUNCATE` remains only to sweep rows an *older* harness
# committed before this fixture existed, so a local `oneirodextest` that still
# carries months of residue starts where CI (fresh container) starts.
_SCHEMA_READY = False


def _build_schema_once():
    """DDL + one residue sweep, on a dedicated connection, exactly once."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    from sqlalchemy import text

    connection = db.engine.connect()
    try:
        with connection.begin():
            db.metadata.create_all(bind=connection)
        # Incremental column adds for a test DB left over from an older schema.
        # Idempotent, and now paid for once per process rather than per test.
        from oneirodex.updateschema import DatabaseManager
        DatabaseManager().add_column_if_not_exists()

        # One-time floor sweep. Per-test isolation (below) keeps the database
        # clean going forward, but it cannot un-commit rows a previous harness
        # already persisted. `ONEIRODEX_KEEP_TEST_DATA=1` skips it for when the
        # leftover rows are the thing under investigation.
        if os.getenv('ONEIRODEX_KEEP_TEST_DATA') != '1':
            tables = [f'"{t.name}"' for t in db.metadata.sorted_tables]
            if tables:
                with connection.begin():
                    connection.execute(
                        text(
                            'TRUNCATE TABLE '
                            + ', '.join(tables)
                            + ' RESTART IDENTITY CASCADE'
                        )
                    )
    finally:
        connection.close()

    _SCHEMA_READY = True


@pytest.fixture(scope='function')
def db_session(app):
    """A database session scoped to one test by a rolled-back SAVEPOINT.

    Everything a test writes — directly or through the Flask test client, which
    shares this bound connection — is visible for the life of the test and
    discarded on teardown. `db.session` is swapped for a scoped session bound to
    the test's connection because Flask-SQLAlchemy's own `Session.get_bind`
    returns the app's default engine before it will honour a per-session
    `bind=`, so `db.session.configure(bind=...)` alone does not route here.

    Two things keep the SAVEPOINT model honest:

    * **The savepoint-restart listener** (SQLAlchemy's "Joining a Session into
      an External Transaction" recipe). A `db.session.commit()` inside a test —
      or Flask-SQLAlchemy's `teardown_appcontext` firing `db.session.remove()`
      when a nested `app_context()` / `test_request_context()` pops mid-test —
      RELEASEs the per-test SAVEPOINT. With nothing re-opening one, the session
      keeps a dangling savepoint reference and teardown's `.remove()` emits
      `ROLLBACK TO SAVEPOINT` against a name Postgres has already released
      (`InvalidSavepointSpecification`). `_restart_savepoint` re-arms a fresh
      nested transaction the moment the previous one ends, so exactly one
      per-test SAVEPOINT is always outstanding.

    * **Exception-safe teardown.** Even with the listener, a slow test that let
      Postgres hit `idle_in_transaction_session_timeout`, or any error inside
      `.remove()`, must not skip `transaction.rollback()` /
      `connection.close()`: an un-rolled-back outer transaction strands the
      connection `idle in transaction` holding row locks, and the next test's
      first write blocks on `lock_timeout` and fails — the cascade recorded in
      `docs/dev/test-harness-2026-09-10.md`. Every teardown step therefore runs
      under its own `try`, and the connection is closed no matter what.
    """
    from sqlalchemy import event
    from sqlalchemy import orm as sa_orm
    from flask_sqlalchemy.session import _app_ctx_id

    with app.app_context():
        _build_schema_once()

        connection = db.engine.connect()
        transaction = connection.begin()  # outer transaction — always rolled back

        original_session = db.session
        test_session = sa_orm.scoped_session(
            sa_orm.sessionmaker(
                bind=connection,
                join_transaction_mode='create_savepoint',
                future=True,
                # No `expire_on_commit=False`. Keeping objects unexpired after a
                # `db_session.commit()` hands the test the *pre-commit* Python
                # values — a tz-aware datetime the column stores naive, a
                # relationship a concurrent writer has since changed — instead
                # of what a fresh query returns. Flask-SQLAlchemy's own session
                # expires on commit; matching that keeps a test reading the
                # database, not its own stale identity map.
            ),
            scopefunc=_app_ctx_id,
        )
        db.session = test_session
        # The session for *this* (the fixture's) app context. The per-test
        # SAVEPOINT and the restart listener both belong to it alone. A Flask
        # test-client request pushes its own app context, so `scopefunc=
        # _app_ctx_id` hands it a *separate* short-lived session bound to the
        # same connection; that one manages its own savepoints, is `.remove()`d
        # when the request context pops, and must NOT get the restart listener
        # (its product-code `with db.session.begin_nested():` blocks are often
        # the only nested transaction it has, and re-arming inside their
        # `__exit__` raises "Can't operate on closed transaction inside context
        # manager").
        bound_session = test_session()
        bound_session.begin_nested()

        def _restart_savepoint(sess, trans):
            # Re-open the per-test SAVEPOINT once the previous one has fully
            # ended — a `db.session.commit()` in a test releases it and lands
            # here with `in_nested_transaction()` False. A product-code
            # `with bound_session.begin_nested():` in a fixture also fires this
            # event from its `__exit__`, but the per-test SAVEPOINT is still
            # outstanding under it, so `in_nested_transaction()` is True and it
            # is left alone. (`not trans._parent.nested` cannot be the guard:
            # `join_transaction_mode='create_savepoint'` makes the root join
            # itself report `nested`.)
            if trans.nested and not sess.in_nested_transaction():
                sess.begin_nested()

        event.listen(bound_session, 'after_transaction_end', _restart_savepoint)

        try:
            yield test_session
        finally:
            try:
                event.remove(
                    bound_session, 'after_transaction_end', _restart_savepoint
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                test_session.remove()
            except Exception:  # noqa: BLE001
                # Most likely `InvalidSavepointSpecification` if Postgres
                # already severed the transaction. The outer rollback below
                # still has to run.
                pass
            finally:
                db.session = original_session
                try:
                    transaction.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    connection.close()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Auto-markers (pytest.ini declares `database` and `slow`; --strict-markers is on)
# ---------------------------------------------------------------------------

# Conservative `slow` list: only tests whose *own* work — filesystem theme
# copies, redirect-chain walks, mocked-network retry loops — pushed them past
# ~20s of call time in the 2026-09-10 re-baseline (`--durations`). Not derived
# from timings at collection time (those move with the box); revisit from a
# fresh `--durations` when the set visibly drifts.
_SLOW_NODEIDS = (
    'test_init_manager_themes.py::TestSetupDefaultTheme',
    'test_init_manager_themes.py::test_install_preset_themes_uses_the_shipped_source',
    'test_ssrf_hardening.py::test_redirect_chain_is_bounded',
    'test_ssrf_hardening.py::test_post_body_is_not_replayed_on_a_303',
    'test_ssrf_hardening.py::test_relative_redirect_resolves_against_current_hop',
    'test_providers_steamgriddb.py::test_fetch_image_mocked',
    'test_gaming_news_feeds.py::TestFeedApi::test_response_lists_the_configured_sources',
    'test_indexer_registry.py::test_enable_presets_copies_without_mutating_pack',
)


def pytest_collection_modifyitems(config, items):
    """Tag every test that reaches Postgres `database`, and the known-slow ones `slow`.

    `database` is derived, not hand-maintained: a test gets it whenever
    `db_session` is in its resolved fixture graph — directly, or through
    `configured_install` / `global_settings` / `admin_user` / any fixture that
    itself requests `db_session`. `-m "not database"` then selects the pure
    unit tests, and `-m database` the ones that need `oneirodex-review-db` up.
    """
    for item in items:
        if 'db_session' in getattr(item, 'fixturenames', ()):  # noqa: SIM118
            item.add_marker('database')
        if any(frag in item.nodeid for frag in _SLOW_NODEIDS):
            item.add_marker('slow')


@pytest.fixture(scope='function')
def client(app):
    """Create a test client for the Flask application."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Bucket-E opt-out: no_savepoint_db (docs/dev/test-harness-2026-09-10.md)
# ---------------------------------------------------------------------------
#
# A handful of tests need `db.session` to behave exactly as it does in
# production — an ordinary Flask-SQLAlchemy scoped session pulling a fresh
# connection per app context from the engine's pool — because they exercise a
# second OS thread pushing its own `app.app_context()`
# (`run_in_background`, `oneirodex/utils/background.py`) or a debounced digest
# flushed from a context nested inside another. `db_session` binds every app
# context onto ONE shared `Connection` object so a test-client request can see
# a test's own uncommitted rows; a second thread touching that same
# `Connection` concurrently is exactly the hazard `run_in_background` exists
# to avoid (a DBAPI connection is not thread-safe), and a nested context's own
# `teardown_appcontext` -> `.remove()` rolls back its `create_savepoint`
# savepoint, discarding what an even-more-nested context just committed into
# it. Neither is fixable with a smarter SAVEPOINT — these tests need a real
# session against the real engine.
#
# Rows committed here are real, so there is no rollback to lean on. Cleanup is
# a TRUNCATE scoped to the fixed, small set of tables the bucket-E tests
# actually touch — never a global, cross-test TRUNCATE. That is safe because
# these are the only tests that request this fixture and pytest runs them one
# at a time in one process: nothing else can be relying on those tables'
# contents while one is mid-flight, so a TRUNCATE that also cascades into a
# handful of unlisted-but-referencing tables (games -> tags, etc.) removes
# only rows this test itself created.
_NO_SAVEPOINT_TABLES = (
    'user_notifications',
    'scan_jobs',
    'games',
    'libraries',
    'global_settings',
    'users',
)


@pytest.fixture(scope='function')
def no_savepoint_db(app):
    """Opt-out of the per-test SAVEPOINT model for bucket-E tests only.

    Use only for a test that pushes its own nested or cross-thread app
    context and needs `db.session` to be the app's ordinary engine-bound
    session, not `db_session`'s single shared connection — see the module
    comment above and docs/dev/test-harness-2026-09-10.md. Everything the test
    commits is real; teardown truncates `_NO_SAVEPOINT_TABLES` so the next
    (SAVEPOINT-isolated) test still starts from an empty database.
    """
    from sqlalchemy import text

    with app.app_context():
        _build_schema_once()
        try:
            yield db.session
        finally:
            try:
                db.session.remove()
            except Exception:  # noqa: BLE001
                pass
            cleanup = db.engine.connect()
            try:
                with cleanup.begin():
                    cleanup.execute(
                        text(
                            'TRUNCATE TABLE '
                            + ', '.join(f'"{t}"' for t in _NO_SAVEPOINT_TABLES)
                            + ' RESTART IDENTITY CASCADE'
                        )
                    )
            finally:
                cleanup.close()


@pytest.fixture(scope='function')
def configured_install(db_session):
    """An install that is past the setup wizard.

    `check_setup_status` is a `before_request` hook and `is_setup_required()`
    means "no users exist", so on the now-empty per-test database *any*
    anonymous request is redirected to `/setup` — not to the login page. Every
    `..._requires_login` test that asserts `'/login' in response.location`
    needs a user row to exist first; requesting this fixture states that
    precondition explicitly instead of relying on an earlier file to have left
    one behind. Tests that drive the wizard itself must *not* use it — they need
    the un-configured state this removes.

    The insert lives inside the test's SAVEPOINT and is rolled back on teardown.
    """
    from uuid import uuid4
    from oneirodex.models import User
    from oneirodex.utils.global_settings import global_settings_row_or_create

    anchor = User(
        user_id=str(uuid4()),
        name=f'SetupAnchor_{str(uuid4())[:8]}',
        email=f'anchor_{str(uuid4())[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    anchor.set_password('testpass123')
    db_session.add(anchor)

    settings = global_settings_row_or_create()
    settings.setup_in_progress = False
    settings.setup_completed = True
    db_session.commit()
    return settings


@pytest.fixture(scope='function')
def global_settings(db_session):
    """The `GlobalSettings` singleton for this test.

    Each test starts with an empty database, so this is an unconditional
    create — but routed through `global_settings_row_or_create()` (the same
    helper production code uses) so it composes with `configured_install` and
    with any product code that also lazily creates the row, without tripping the
    `global_settings_singleton` unique index. Mutate the returned object and
    commit for tests that need particular values on it.
    """
    from oneirodex.utils.global_settings import global_settings_row_or_create

    row = global_settings_row_or_create()
    db_session.commit()
    return row
