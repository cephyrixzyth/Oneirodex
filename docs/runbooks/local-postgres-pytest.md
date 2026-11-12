# Local Postgres for pytest

> **Doc status:** Active

The R2038 fixture follow-up preserves client disposal for every real app, including exceptional teardown and retained tracebacks. Configuration-only database-guard probes inject `db=None` and have no clients to dispose. Those stubs skip resource cleanup; URL validation and real database teardown stay enforced. The previous full/CI baselines each exposed three stub-close failures; 29 focused guard/resource checks now pass. The subsequent fixed `01d3f463` baseline finished **8,513 passed, 101 skipped**, with source and owned-database absence verified; its CI core finished **7,876 passed, 14 skipped, 548 deselected**. Overall CI failed the separate member TypeScript step. [R2040 evidence](../dev/parity-evidence/bootstrap-full-types-r2040.json) preserves these exact-source results and the focused type correction. The full Python baseline does not qualify later migration edits.

Native Windows, with Docker Desktop running.

The per-test app fixture removes its session and disposes every app-owned engine
on both success and failure. Removing a session alone leaves idle pooled clients
alive while pytest retains app objects or tracebacks; do not rely on garbage
collection or raise PostgreSQL connection limits to hide that leak. The retained-app
backend-PID regressions in `tests/test_test_harness_resources.py` cover this boundary.

Authentication-sensitive fixtures must issue persisted native login identities and use a fresh
Flask app context when consecutive bearer requests change identity or scope. A test-wide database
context otherwise retains Flask-Login's first loaded user. Store-link assertions must inspect
ciphertext and use the production decryptor with a temporary test key ring; plaintext columns are
no longer the credential source. Auth-shell validation notices are escaped bootstrap data that
React renders as alerts, rather than server-rendered alert elements.
Busy scan fixtures must use UTC timestamps so stale-job recovery does not reclaim a newly seeded
job. Worker fault tests must configure a temporary allowed scan root before testing folder I/O or
database errors; paths outside configured roots are rejected before those later operations.
Scan helper assertions must include the forwarded application, allowed-root and database-scope
arguments. Enrichment diagnostics use Python logging (`caplog`), rather than stdout. Legacy SMTP
send tests patch the function-local `flask.flash` import and transport constructors, leaving real
message construction and TLS upgrade behavior under test.
`tests/fixtures/faults.py` also provides an event-controlled delayed provider and a `commit_ack`
save seam. The latter performs the real commit before raising a synthetic acknowledgement error.
Cross-request checks use `no_savepoint_db` so another PostgreSQL session can observe the commit;
release delayed providers in `finally` before joining their worker. These fixtures simulate timing
and acknowledgement loss; they do not physically drop database connections or contact providers.

**CI:** `.github/workflows/ci-tests.yml` spins up Postgres with
`POSTGRES_DB=oneirodextest` and runs a *core* pytest subset only. The full suite
stays local/release — see release-checklist.md.

The API-envelope, print and JSON-reader ratchets run before the long CI pytest
selection. Runtime diagnostics use configured logging. Explicitly named operator
CLI reports keep their stdout/stderr interface through the print scanner's
existing exception policy; this changes scanner scope, not baseline counts.
Repaired checkout, enrichment-log and unmatched-redirect cases are included in
CI again. Other named exclusions and the integration split still limit CI.

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

Before testing against a new or reused database, run the guarded schema upgrade:

```bash
python scripts/upgrade_test_schema.py
```

It reads `TEST_DATABASE_URL`, requires a loopback PostgreSQL host and a database
name containing `test`, uses that URL for Alembic only inside its own process,
then verifies the save revision column and history table. It withholds connection
details. If the database claims Alembic head but its tables do not match, the
command stops; create a fresh test-named database rather than trying to use the
stale schema. For example, create `oneirodexschema_test` in the review container,
then set `TEST_DATABASE_URL` in the current shell to that loopback database before
running the upgrade and pytest. This leaves the root `.env` untouched. Never point
this command at a live application database.

```bash
docker exec oneirodex-review-db createdb -U postgres oneirodexschema_test
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oneirodexschema_test
python scripts/upgrade_test_schema.py
python -m pytest tests/test_whatever.py
unset TEST_DATABASE_URL
```

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

## Independent-review baseline and authentication fixtures

Use Python 3.12 and Node 22 for the independent-review baseline. Select a fresh
loopback test database and upgrade it with the guarded command above. For a
run that must not inherit operator configuration, set
`PYTHON_DOTENV_DISABLED=1` before starting Python and supply synthetic test
settings in that process. This disables dotenv loading; it does not block
outbound connections by itself. Block external delivery separately when running
broad tests, and retain failures, skips and incomplete runs in the result log.
Do not treat collecting tests as executing them or an early-stopped core run
as a passing CI suite.

The download-auth adapter checks can run without the shared PostgreSQL fixture:

```bash
python -m pytest --noconftest -o addopts= tests/test_asgi_download_auth.py -q
```

They use a disposable SQLite store and production persistent-session issuance,
validation and revocation. They verify retired-cookie rejection, active-user and
client binding, bearer precedence, and revocation without weakening production
authentication. SQLite does not qualify PostgreSQL foreign keys, locking or
migrations; use `tests/test_persistent_sessions.py` with the isolated PostgreSQL
database for that integration boundary. Current baseline outcomes and remaining
limits are recorded in the [maintained review](../dev/behavior-parity-review.md).


## Shared review fixtures

`tests/fixtures/household_safety.py` provides an opt-in seed for active/disabled
members, children with no/some library grants, librarian/admin accounts, each API
scope, persistent identities and synthetic legacy save collisions. Call
`seed_household(app, db_session, tmp_path, monkeypatch)` with the normal rolled-back
PostgreSQL fixture; it rejects non-loopback/non-test targets before inserting rows.
It owns only a child of the supplied pytest temporary directory and never drops a
schema or broadly deletes files. The runner owns disposable database removal.

The fixture blocks socket connect/connect_ex and DNS except the loopback database
port, including local SMTP ports. It does not constrain separately launched tools;
the runner must guard them. For asynchronous in-process ASGI tests on Windows,
create the event loop before installing this boundary: asyncio uses a private
socket pair. Do not permit arbitrary loopback connections to accommodate it.

After applying the database safeguards above, run:

```bash
python -m pytest -o addopts= tests/test_safety_fixture_guards.py tests/test_household_safety_fixture.py tests/test_test_database_guard.py -q
```

The guard-only module can also run with `--noconftest`. The seeded checks use real
native ACL/auth/save adapters and PostgreSQL/file persistence; they cover selected
child save and denial paths, not concurrent locking, provider failures or browser
service-worker behavior. See [R2010](../dev/parity-evidence/shared-review-fixtures-r2010.json).


`tests/fixtures/native_auth.py` is the smaller opt-in dispatch fixture: importing
its autouse `persistent_login_store` creates a disposable SQLite session table.
Dispatch/download checks use the production identity issuer and shaped synthetic
fingerprints rather than bypassing persistent-session policy. Keep household,
foreign-key, concurrency and transaction assertions on the PostgreSQL fixture;
this serial SQLite fixture does not establish those properties.


For native save failure checks, import `household` and `household_loop` from the
shared household helper. `tests/fixtures/faults.py::fail_next_save_io` scopes its
write/fsync/rename/directory-sync overrides to the save module and restores them
on exit. The commit seam selects pending save changes so the real bearer-token
last-used commit still runs. `tests/test_native_save_fault_fixtures.py` verifies
sanitized failures, preserved committed bytes, report-only orphan detection and
successful retries against PostgreSQL. These seams do not establish actual disk
exhaustion, crash recovery or loss after a real server commit.


## Encryption and native library-adapter fixture prerequisites

Tests that write indexer or other reusable credentials must request the
`reusable_secret_keyring` fixture. It generates a temporary keyring and sets the
process-local test keyring variable; POSIX fixtures use mode `0600`. Standalone
SMTP tests that run without conftest create their own equally protected test
keyring. Keep missing-key and recovery cases explicit: do not supply a global
production fallback or load operator keys to make tests pass.

An encrypted-save roundtrip must initialize its own temporary save keyring,
independently of the reusable-credential keyring. The roundtrip checks persisted
`GTENC3` bytes and the recovered save; the indexer check verifies a stored
`odrc:v1` envelope and the original synthetic key at mocked provider transport.

Library-admin adapter tests import the shared `persistent_login_store` fixture
from `tests/fixtures/native_auth.py` and issue identities through
`issue_login_identity`. A two-field historical identity must still be rejected
before reaching a mutation adapter; a valid member identity reaches the role
check and is denied there. Those SQLite checks cover the authentication/adapter
boundary, not real filesystem deletion, PostgreSQL concurrency or full-app
acceptance. The [fixture qualification record](../dev/parity-evidence/encryption-library-fixture-qualification-20261109.json)
keeps the focused outcomes separate from the incomplete broader baseline.

Native admin fake-adapter modules can use `login_identity_for(user_id)` from the same fixture module when their synthetic user exposes its matching 16-character fingerprint. This helper issues a real persisted random-secret identity. In mixed modules, tests that request `db_session` retain that real transaction; the login fixture uses its small SQLite store only for fake-only checks. [R2015](../dev/parity-evidence/native-admin-auth-fixtures-r2015.json) qualifies 117 native-admin cases, including real PostgreSQL account creation, plus 103 existing direct fixture consumers. These counts remain separate from full-suite and installed-runtime acceptance.

A fixture that already owns a native SQLite engine must create the persistent-login table and issue its logins inside that engine scope; do not replace its Flask extension with the minimal login-store facade. CSRF variants should reuse an issued identity. Database-failure tests must issue logins before installing failure hooks and assert that the intended adapter was reached. [R2016](../dev/parity-evidence/native-member-auth-fixtures-r2016.json) records the 324-case qualification and cleanup.

Framework-blocked startup probes need their own complete preconditions: an owned native engine with the synthetic user, setup singleton and persistent-login rows. OIDC fixtures should let the normal callback issue a stored identity for a mapped test user; independent logins share the user/fingerprint, not the random session secret. Intercept caller-owned HTTP sessions when testing redirect policy; keep safe-request validator wiring explicit in retry-only unit tests. [R2017](../dev/parity-evidence/native-runtime-boundary-r2017.json) records the 120-case native/compatibility qualification and remaining limits.

Test keyrings must use mode 0600 on POSIX. Patch the consuming module database dependency in DB-free tests rather than assigning the native facade session property. Snapshot tests using create_all need explicit session-local migration metadata. Release licence files use canonical LF bytes and exact digest pins across platforms.

Scan Jobs page tests should pair actual scan-status API fields with React rendering checks, since the server serves a SPA shell. Mock function-local worker imports at their defining modules, and configure temporary allowed roots for successful scan/recurrence tests.
