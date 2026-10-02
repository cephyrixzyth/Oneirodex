# ADR: Schema migrations before official 1.0

> **Doc status:** Active

**Date:** 2026-07-27  
**Status:** **Superseded 2026-09** by [ADR 0004 — Adopt Alembic](0004-adopt-alembic.md).
Originally: Accepted for 1.0 — defer Alembic; keep `updateschema.py` + `create_all`  
**Owners:** `agent-backend` · `agent-ops` · `maintainer`

> **Superseded (modernization wave A3.1).** Alembic was adopted post-1.0: a
> squashed baseline revision matches the current Postgres schema,
> `oneirodex/updateschema.py` is frozen (carries pre-Alembic installs to the
> baseline only), and `init_manager` stamps existing databases on first boot.
> The "Follow-ups" below are now done. See ADR 0004 and
> `docs/dev/alembic-baseline-notes.md`.

## Context

Oneirodex applies schema via `db.create_all()` plus incremental raw SQL in
`oneirodex/updateschema.py` (`ADD COLUMN IF NOT EXISTS`, etc.) during
`init_manager` Phase 2. There is no Alembic revision table or rollback path.

Official **1.0.0** needs a clear upgrade story for Unraid operators without a
risky mid-release migration rewrite.

## Decision

**Defer Alembic (or Flask-Migrate) until after 1.0.0.**

For 1.0:

1. Keep `updateschema.py` as the upgrade mechanism.
2. Document operator upgrade as: pull image → `compose up` → watch init logs for
   schema phase → `/readyz` green.
3. Treat a full Alembic cutover as **1.1** work with a freeze window and dual-run
   plan (generate baseline from current models, then stop editing `updateschema`).

## Consequences

| Pros | Cons |
|---|---|
| No blocker on 1.0 ship | No automated downgrade |
| Matches what all current installs already run | Drift still possible if someone edits models without updateschema |
| Lower risk than rewriting migrate mid-polish | CI does not yet assert schema drift |

## Follow-ups (post-1.0)

- Baseline Alembic revision matching current Postgres schema
- Stop appending to `updateschema.py`; new columns go through Alembic only
- Optional CI check: model metadata vs live test DB

## Related

- Local strategy notes (v1 readiness)
- `oneirodex/updateschema.py`, `oneirodex/init_manager.py`
