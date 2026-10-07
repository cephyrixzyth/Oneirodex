# ADR 0012: Evaluate MariaDB before changing database support

> **Doc status:** Reference

**Date:** 2026-10-06
**Status:** Proposed — evaluation plan only; no engine decision changed and no migration authorized or run.
**Owners:** Backend · Platform · Ops

## Context

The owner asked whether Oneirodex should move from PostgreSQL to MariaDB because
MariaDB appears cheaper at higher user counts, and requested a plan before
execution. The current repository does not specify a target hosting provider,
region, active/concurrent user count, workload, uptime target, or comparable
MariaDB offer. A price or users-per-dollar claim cannot be verified without
those inputs. In a self-hosted Unraid/Compose deployment, both are available
without a database license fee; hardware, backups, support and operating effort
drive the cost. Managed database pricing is provider- and tier-specific.

PostgreSQL is the current supported database across Compose, embedded and
bundled installs, migration history, tests, and operator tooling. The accepted
[ADR 0011](0011-standalone-bundled-postgres.md) specifically depends on
PostgreSQL behavior and verified PostgreSQL dump/restore for standalone moves.
Replacing PostgreSQL or adding MariaDB support therefore needs a follow-up
decision, not a URL change.

The application has live PostgreSQL-specific behavior that must be addressed:

| Area | Evidence | Required work |
|---|---|---|
| Browse and matching | `oneirodex/utils/browse_query.py` uses `DISTINCT ON`; `title_grouping.py` uses `regexp_replace`; browse filters use `ILIKE` | Preserve result, case/accent and ordering semantics; verify query plans |
| Concurrency | `utils/admin_invariant.py` uses `pg_advisory_xact_lock`; several paths use `with_for_update()` | Replace advisory lock behavior and prove row locks run inside transactions; test lost updates and duplicate work |
| Upserts | `utils/discover_ml/impressions.py` imports PostgreSQL `insert` for `ON CONFLICT` | Port upsert and affected-row behavior |
| Reset and indexes | `utils/system_reset.py` uses `TRUNCATE … RESTART IDENTITY CASCADE`; a model declares a partial index using `postgresql_where` | Preserve reset behavior and conditional uniqueness |
| Schema and data movement | Alembic history is exercised on PostgreSQL; frozen `updateschema.py` has PostgreSQL DDL; standalone move uses `pg_dump` / `pg_restore` | Establish fresh install, upgrade, and verified logical-copy paths |
| Packaging and operations | Requirements, Dockerfile, Compose, embedded launcher, installers and docs install/use PostgreSQL | Select driver and version; update readiness, diagnostics, backup/restore, packaging and operator procedures |

SQLAlchemy provides a MySQL-family dialect that detects MariaDB, while
documenting backend-specific differences. MariaDB InnoDB supports row locking;
its documentation says `FOR UPDATE` only takes effect within a transaction.
PostgreSQL advisory locks have no automatic equivalent in the current app.
Sources: [SQLAlchemy MariaDB/MySQL dialect](https://docs.sqlalchemy.org/en/21/dialects/mysql.html),
[MariaDB `FOR UPDATE`](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update),
[MariaDB InnoDB lock modes](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-lock-modes),
[PostgreSQL explicit locking](https://www.postgresql.org/docs/17/explicit-locking.html).

## Proposed decision

Do **not** replace PostgreSQL yet. Evaluate MariaDB as a candidate while
PostgreSQL remains the supported default. Recommend changing support only if:

1. A like-for-like total-cost comparison shows a meaningful saving for the
   intended deployment and workload.
2. MariaDB meets correctness, backup/restore and performance requirements on a
   production-shaped workload, including concurrent scans and ownership writes.

The execution plan is gated. A failed gate means retain PostgreSQL. Production
cutover requires a separate explicit authorization after the migration and
rollback procedures are reviewable.

## Evaluation and migration plan

| Phase | Work | Exit evidence |
|---|---|---|
| 0. Bound the business case | Record provider/host, region, concurrent users, catalog size, scan frequency, backup/RPO/RTO, availability target and current cost. Compare compute, storage, backups, HA, network/egress and support on equal requirements. | Reproducible cost sheet and a minimum-savings threshold. |
| 1. Inventory compatibility | Audit ORM expressions, raw SQL, all Alembic revisions, models/indexes, tests, DB utilities, installers, images, backup/restore and move commands. Define browse, ownership, job-fence, uniqueness and reset invariants. | Compatibility ledger and acceptance checks for every PostgreSQL-specific feature. |
| 2. Isolated spike | Add a disposable MariaDB test service/database, choose a supported version and maintained DBAPI driver, then prove bootstrap, migrations and focused invariants. Never connect to user data. | Fresh install and full migrations work; checks pass with no silent loss of constraints or locks. |
| 3. Workload comparison | Replay identical seeded data and request/scan traffic with equal CPU, RAM, storage, pools and concurrency. Measure read/write latency, lock waits, queue throughput, restart recovery and peak memory. | Repeatable realistic and growth-target benchmarks meet agreed correctness/latency thresholds and the cost gate. |
| 4. Copy tool and rehearsal | Build a one-shot logical PostgreSQL-to-MariaDB copier. Refuse a running app or non-empty target; snapshot source counts/checksums; copy in FK-safe batches; restore auto-increment state; include dry-run and never mutate source. | Two isolated rehearsals on representative copies match row/key/checksum totals; duration, disk needs and rollback are recorded. |
| 5. Dual-support release | If prior gates pass, add MariaDB as opt-in while PostgreSQL remains supported. Add both-engine CI, supported version/driver matrix, install/upgrade, backup/restore, readiness and operations docs. | CI and operator procedures cover both engines. |
| 6. Pilot and cutover proposal | Use a disposable or explicitly selected non-production copy. Rehearse stop-app, final copy, validation, config switch, restart and return path. Keep PostgreSQL data intact. | Owner reviews measured results and concrete cutover/rollback steps; separate authorization precedes production work. |

### Migration safety requirements

- Use a new MariaDB database and copy logical rows; never convert a data
  directory in place.
- Stop all app writers for the final copy. Do not dual-write.
- Preserve the source database and backups through the agreed observation
  window and successful target restore check.
- Verify schema revision, per-table counts, primary keys, unique invariants,
  game UUIDs, entitlements, match decisions, saves, ownership/sync state,
  timestamps and auto-increment state.
- Test restoration of both source and target. A successful copy alone is not a
  recovery plan.
- Bound rollback in time or define how post-cutover writes are reconciled before
  returning to the PostgreSQL source.

## Inputs needed to start Phase 0

The current provider/host, geography, expected user and peak-concurrency counts,
data size, backup retention, uptime target, and the MariaDB plan or quote that
prompted the request. Until those are known, retain PostgreSQL and compare costs
before changing the database.

## Related

- [ADR 0011](0011-standalone-bundled-postgres.md) — accepted standalone PostgreSQL decision; unchanged by this proposal.
- [Database engine and cache proposal](../strategy/db-engine-and-cache-2026-09.md) — local Reference document; earlier portability statements are superseded where they conflict with ADR 0011.
