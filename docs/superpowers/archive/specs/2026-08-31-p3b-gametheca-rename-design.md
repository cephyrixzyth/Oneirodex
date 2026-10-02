# P3b — retire remaining `oneirodex` identifiers

> **Doc status:** Archive

**Date:** 2026-08-31  
**Status:** Landed 2026-08-31 — package `oneirodex/`, `.od-*` / `--od-*`, Unraid `oneirodex-*`, Postgres `oneirodex`.  
**Scope (user-approved):** Full P3b — package path, containers/images, docs, media

## Locked today vs requested

Agent locks historically kept `oneirodex/` package + `.gt-*` classes until an exclusive wave. Operator asked to remove **all** remaining `oneirodex` / `gamtheca` spellings from code, docs, screenshots, videos, and Unraid container names.

## Workstreams (separate ships)

1. **Compose / Unraid containers** — `oneirodex-app` / `oneirodex-db` / sidecars → `oneirodex-*`; update rebuild scripts (`_unraid_rebuild_and_reset.py` still `docker exec oneirodex-app`); migration runbook for live volumes.
2. **Python package** — `oneirodex/` → `oneirodex/` (or keep import alias one release); update every import, pytest paths, Dockerfile `COPY`.
3. **Docs + media** — scrub `docs/`, README, HelpPage, howto videos/screenshots; delete or re-capture assets that still say Oneirodex.
4. **CSS** — `.gt-*` / `--gt-*` stay unless a later token alias wave is scheduled (renaming every class is a separate UI ratchets epic). Prefer documenting `--od-*` aliases already present.

## Success

- `docker ps` shows no `oneirodex-*` on the household Unraid.
- Repo search for `oneirodex` / `Oneirodex` / `gamtheca` returns only intentional historical ADR notes (or zero).
- App boots; pytest/vitest core gates green.

## Note

Do **not** start mid-scan. Prefer a maintenance window after the current Libraries/member UI deploy is verified.
