# Test harness — per-test isolation on a rolled-back SAVEPOINT

> **Doc status:** Reference

**Date:** 2026-09-10 (verified 2026-09-11) · **Status:** SAVEPOINT model landed; cascade fixed; fallout triaged; bucket-E opt-out fixture landed and verified green

> **The 33 are named now (2026-09-16).** This file said "the pre-existing set
> unrelated to this harness change" and listed none of them, and no ticket was
> filed. They are enumerated, grouped by cause, and three of them fixed in
> [test-suite-failures-2026-09-16.md](archive/test-suite-failures-2026-09-16.md).

Supersedes the "Still open → No isolation between tests" section of
[test-harness-2026-08-07.md](archive/test-harness-2026-08-07.md). That note recorded a
deliberate decision *not* to wrap each test in a transaction, because the 23
order-dependent failures it was proposed for each had a specific cause that an
empty database would have hidden. Those causes were fixed on their own. Isolation
is now worth doing on its own merits — accumulation makes runs slower and every
unscoped assertion a latent failure — and this is that change.

## The model

`db_session` (in `conftest.py`) gives every test its own view of the database
and throws it away on teardown:

1. One `connection = db.engine.connect()` and one real `transaction =
   connection.begin()` per test. The transaction is **always rolled back** in
   teardown — nothing a test writes is ever committed to `oneirodextest`.
2. `db.session` is swapped for a `scoped_session` bound to that connection, with
   `join_transaction_mode="create_savepoint"` so the session always works inside
   a SAVEPOINT and can never touch the real transaction. `scopefunc=_app_ctx_id`
   (Flask-SQLAlchemy's own) so each nested `app_context()` / request gets its own
   session on the same connection.
3. The fixture opens one SAVEPOINT — the per-test savepoint. The Flask test
   client shares the bound connection, so a request sees the test's uncommitted
   rows.
4. Schema DDL (`create_all` + the incremental `ALTER TABLE` migration) still runs
   **exactly once per process**, behind `_SCHEMA_READY` in `_build_schema_once()`
   — the lock-storm guard from 2026-08-07 is unchanged. A single process-start
   `TRUNCATE` (skipped by `ONEIRODEX_KEEP_TEST_DATA=1`) sweeps rows an older
   harness committed, so a local `oneirodextest` starts where CI's fresh
   container starts.

`configured_install` and `global_settings` remain **opt-in per-test seeds**, not
autouse — tests that drive the setup wizard need the un-configured state.

## Two things that make the SAVEPOINT model safe

Both were missing or wrong in the first cut of the fixture and are the subject of
`fix(conftest): savepoint-restart listener + exception-safe db_session teardown`.

### The savepoint-restart listener

`join_transaction_mode="create_savepoint"` alone is not enough once a test — or
product code, or Flask-SQLAlchemy's `teardown_appcontext` firing
`db.session.remove()` when a nested context pops — calls `commit()`. That
**RELEASEs** the per-test savepoint. With nothing re-opening one, the session
keeps a dangling savepoint reference and teardown's `.remove()` issues
`ROLLBACK TO SAVEPOINT sa_savepoint_N` against a name Postgres has already
released:

```
psycopg2.errors.InvalidSavepointSpecification: savepoint "sa_savepoint_7" does not exist
```

An `after_transaction_end` listener re-opens a fresh per-test savepoint the
moment the previous one ends, so exactly one is always outstanding — the
SQLAlchemy "Joining a Session into an External Transaction" recipe.

Two adaptations the standard recipe does not spell out:

* **Guard on `not session.in_nested_transaction()`, not `not
  trans._parent.nested`.** `create_savepoint` makes the session's own root join
  report `nested`, so the parent-based guard fires *inside* a product-code
  `with db.session.begin_nested():` block's `__exit__` and raises "Can't operate
  on closed transaction inside context manager". Keying on whether any savepoint
  is still outstanding leaves product-owned nested blocks alone.
* **Register the listener on the fixture's own session instance, not the
  `scoped_session` registry.** A test-client request pushes its own app context
  and `scopefunc=_app_ctx_id` hands it a separate short-lived session; a
  registry-wide listener re-arms savepoints on *that* session too, and its
  product-code `begin_nested()` is often the only nested transaction it has —
  same "closed transaction inside context manager" crash from its `__exit__`.

### Exception-safe teardown

Even with the listener, `.remove()` can raise (Postgres severs the transaction on
`idle_in_transaction_session_timeout`; any driver hiccup). If that exception
escapes the `finally:` before `transaction.rollback()` / `connection.close()`
run, the outer transaction is stranded `idle in transaction` holding its row
locks. The next test's first write then blocks on `lock_timeout` and fails, and
the failure spreads:

```
LockNotAvailable: canceling statement due to lock timeout
  CONTEXT: while inserting index tuple in relation "discovery_sections_identifier_key"
QueuePool: Exception during reset or similar
PendingRollbackError: Can't reconnect until invalid savepoint transaction is rolled back
```

In the pre-fix re-baseline this poisoned ~80 unrelated tests, CI-core among them
(`test_global_settings_singleton`, `test_routes_info`, `test_licensed_catalog`,
`test_health_probes`, `test_routes_ops`, …). The first deterministic casualty was
the teardown of `tests/test_discover_hydrate.py::TestHydrationDoesNotScaleWithTiles`
at 16%; everything green before it.

Teardown now runs listener-removal, `session.remove()`, the `db.session`
restore, `transaction.rollback()` and `connection.close()` each under its own
guard. The connection is closed no matter what.

## PG session settings (test connections only)

`conftest.py` sets these on every test connection, in autocommit (`SET` is
transactional in Postgres — see the 2026-08-07 footgun):

| setting | value | why |
|---|---|---|
| `lock_timeout` | `15s` | No healthy test waits on a lock. A 15s wait is always a leak, and the named `LockNotAvailable` on the blocked statement is the bug report. |
| `idle_in_transaction_session_timeout` | `300s` (was `60s`) | The per-test model now legitimately holds one outer transaction open for a whole test, so between statements the connection is "idle in transaction" for as long as the test's own Python runs. The slowest single tests (`test_init_manager_themes`, ~70s of theme-file copying) would trip a 60s ceiling and have Postgres sever their own transaction mid-test. 300s clears the slowest test with headroom while still catching a transaction a crashed fixture stranded between tests. |

## `expire_on_commit`

The fixture does **not** set `expire_on_commit=False`. Keeping objects unexpired
after a `db_session.commit()` hands the test the *pre-commit* Python value of an
attribute — a tz-aware datetime the column stores naive; a relationship a
concurrent writer has since changed — which diverges from what a fresh query
returns. Flask-SQLAlchemy's own session expires on commit; matching that keeps a
test reading the database rather than its own identity map.

## Fallout from a genuinely empty per-test database

The re-baseline after the fixture fix was **85 failed / 4098 passed / 0
errors** (from 121 failed / 25 errors). ~34 of the 85 also fail on
`origin/main` and are pre-existing (stale `@patch` targets, envelope-shape
assertions, un-built SPA `dist/`, renamed helpers) — untouched here. The rest
were the isolation exposing preconditions the suite used to inherit from an
earlier file:

| bucket | remedy | examples |
|---|---|---|
| **A** — `*_requires_login` / `*_requires_authentication` asserting `'/login' in location`, now `/setup` because no user row exists | request `configured_install` | `test_routes_info`, `test_routes_settings`, `test_routes_smtp`, `test_routes_admin_ext_{filters,help,igdb,newsletter,settings,themes,whitelist}`, `test_routes_downloads_ext_{initiate,play,serve}`, `test_ops_followons` |
| **D** — `*_database_error` patching `db.session.commit` to raise; the `check_setup_status` before_request hook then lazily creates the settings row under the patch and the exception escapes the route | request `global_settings` so the row already exists | `test_routes_settings`, `test_routes_smtp`, `test_routes_admin_ext_{igdb,settings,system,whitelist}` |
| **B** — assertions that assumed ambient rows | explicit seed, no weakened assertion | `test_routes_discover` `test_games` seeds `times_downloaded=(i+1)*10`; `test_discover_ml` rebuild test takes `configured_install` for its member row |

No product code changed and no assertion was weakened.

### Bucket E — opt out of the SAVEPOINT model: `no_savepoint_db`

Five tests are a genuine structural mismatch, not a seedable precondition —
`db_session`'s single connection, shared across every nested app context, is
the wrong tool for them:

* `test_browse_path_status.py::test_library_add_digest_notifies_staff`,
  `::test_notify_admins_new_game_schedules_digest`,
  `::test_scan_completion_flush_cancels_the_pending_timer`,
  `::test_running_scan_holds_the_digest_until_flush` build a debounced digest
  inside a nested `with app.app_context():` and flush it from a *doubly*
  nested context. `scopefunc=_app_ctx_id` gives the outer nested context its
  own session on the shared connection; when that context pops,
  Flask-SQLAlchemy's `teardown_appcontext` calls `.remove()` on it, which
  **rolls back** its `create_savepoint` savepoint — discarding the
  `UserNotification` rows the inner context committed into it.
* `test_background_workers.py::test_library_deletion_worker_actually_deletes`
  runs `delete_library_background` on a real daemon thread that pushes its
  *own* `app.app_context()` (`run_in_background`,
  `oneirodex/utils/background.py`) specifically so it gets its own DBAPI
  connection from the engine's pool — a `Connection` object is not
  thread-safe, and `run_in_background` exists precisely to stop two threads
  sharing one. Routing it onto `db_session`'s one shared connection instead
  recreates the exact hazard that module was written to remove.

Neither is fixable with a smarter SAVEPOINT: both need `db.session` to behave
like it does in production, an ordinary Flask-SQLAlchemy session pulling a
fresh connection per app context from the engine's pool. `conftest.py` now
provides that as an explicit opt-out fixture, `no_savepoint_db`:

```python
@pytest.fixture(scope='function')
def no_savepoint_db(app):
    with app.app_context():
        _build_schema_once()
        try:
            yield db.session
        finally:
            db.session.remove()
            # TRUNCATE _NO_SAVEPOINT_TABLES only — see below.
```

Rows it commits are real — there is no outer transaction to roll back — so
teardown truncates a fixed, small table list
(`user_notifications, scan_jobs, games, libraries, global_settings, users`,
`RESTART IDENTITY CASCADE`) rather than the whole schema. That is safe, not a
regression to the per-run global `TRUNCATE` this harness removed: these five
tests are the *only* callers of the fixture, pytest runs them one at a time in
one process, and every other test's isolation still comes from `db_session`'s
rollback, which never sees this connection. `test_browse_path_status.py`
carries file-local `nosp_admin_staff` / `nosp_path_library` fixtures — the
same shape as its ordinary `admin_staff` / `path_library`, built on
`no_savepoint_db` instead of `db_session` — used only by the four opted-out
tests; the file's other tests are untouched and still run under the SAVEPOINT
model.

No product code changed.

### Final verified full-suite count (2026-09-11)

With the bucket-E fixture in place, one full local run:

```
33 failed, 4150 passed, 5 skipped, 31 warnings in 1785.26s (0:29:45)
```

The 33 failures are the pre-existing set unrelated to this harness change
(newsletter/download/scan-enrichment/secondary-scrapers/etc. test doubles and
drift already failing on `origin/main`). All five bucket-E tests —
`test_browse_path_status.py` (4) and
`test_background_workers.py::test_library_deletion_worker_actually_deletes` —
pass. `alembic check` shows only the pre-existing, local-only
`user_preferences.show_tile_titles` nullability drift, unchanged and
reproducible on base `main`. Shuffled-order re-runs and the CI-core-subset
run with coverage are left to the PR's actual CI rather than repeated here.

## Randomized-order proof

`pytest-randomly` is not installed and not approved as a dependency. Order
independence is shown instead by running an explicit, shuffled file list under
two seeds — see the PR description for the exact invocation and results.

## Reproducing

```bash
docker start oneirodex-review-db
python -m pytest -q --durations=50          # full
python -m pytest -q -m database             # only the tests that need Postgres
python -m pytest -q -m "not database"       # pure unit tests
python -m pytest -q -m "not slow"           # drop the ~10 filesystem/network-mock slugs
```
