# Local Postgres for pytest

Native Windows, with Docker Desktop running.

**CI:** `.github/workflows/ci-tests.yml` spins up Postgres with
`POSTGRES_DB=oneirodextest` and runs a *core* pytest subset only. The full suite
stays local/release — see release-checklist.md.

## Install the test dependencies

`requirements.txt` is the **runtime** set — it has no test runner in it. Use
`requirements-dev.txt`, which includes it and pins pytest:

```bash
pip install -r requirements-dev.txt
```

## Start the database

The container that serves the test database is **`oneirodex-review-db`**
(`docker-compose.review.yml`, postgres:17.6). It publishes 5432 precisely so
local pytest keeps working while that stack is up.

```bash
docker start oneirodex-review-db
```

First time, or after the container has been removed:

```bash
docker compose -f docker-compose.review.yml up -d db
```

```bash
docker exec oneirodex-review-db psql -U postgres -c "CREATE DATABASE oneirodextest;"
```

Required in `.env`:

```text
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oneirodextest
```

That `postgres:postgres` pair is deliberate and specific to this throwaway
review database: it holds test data only and `docker-compose.review.yml` publishes it
on `127.0.0.1` only. Never copy it to the main stack or any database that holds a real
library; the main Compose `db` takes `POSTGRES_PASSWORD` from `.env` and is also
published on loopback only by default ([docker-compose-deploy.md](docker-compose-deploy.md#postgres-exposure-and-password)).

`conftest.py` validates the parsed PostgreSQL URL before importing the app and
again before creating a test app. It requires a host and a database name containing
`test` (case-insensitive); markers in the username, password or hostname do not
count. Control characters (including NUL), percent-encoded database/host names,
missing/malformed URLs and query options are rejected; driver options could
otherwise override the validated target. Diagnostics withhold connection values.
Confirm the host is your isolated test instance before running DB-backed tests.
The name guard cannot establish that a server is safe by itself. Application creation
also validates the configured test URI before initializing extensions or probing
PostgreSQL, and connection diagnostics no longer include a URI.

Run the guard regressions without loading the app, `.env`, or a database:

```bash
python -m pytest --noconftest -o addopts= tests/test_test_database_guard.py -q
```

## Every test starts from an empty database

Since 2026-09-10 the `db_session` fixture wraps each test in a **rolled-back
SAVEPOINT** on a single bound connection: whatever a test writes — directly or
through the Flask test client — is visible for that test and discarded on
teardown. Nothing is ever committed to `oneirodextest`. Schema DDL still runs
once per process, and a single process-start `TRUNCATE` sweeps rows an older
harness left behind.

The model, why it needs a savepoint-restart listener and exception-safe
teardown, and the per-clean-database fallout are in
[../dev/test-harness-2026-09-10.md](../dev/test-harness-2026-09-10.md).

**Fixtures declare their preconditions.** A test that needs setup to be past the
wizard requests `configured_install`; one that needs the settings singleton
requests `global_settings`. Do not assume an earlier file left a user or a
`GlobalSettings` row — it didn't.

**Scoping assertions still matters** for anything a *previous process* committed
before the sweep, and for tests that opt out with `ONEIRODEX_KEEP_TEST_DATA=1`
(which skips the process-start `TRUNCATE` — for when the leftover rows are what
you are investigating):

```bash
ONEIRODEX_KEEP_TEST_DATA=1 python -m pytest tests/test_whatever.py
```

## Markers

`conftest.py` tags tests at collection:

```bash
python -m pytest -m database          # only tests that reach Postgres (need the container up)
python -m pytest -m "not database"    # pure unit tests, no database
python -m pytest -m "not slow"        # drop the ~10 filesystem / mocked-network slugs
```

`database` is derived from the fixture graph (anything that pulls in
`db_session`); `slow` is a short hand-kept list from `--durations`.

## Running

```bash
python -m pytest tests/test_routes_info.py
```

Scope to one file where you can; the full tree is slow on a network-mounted
checkout.
