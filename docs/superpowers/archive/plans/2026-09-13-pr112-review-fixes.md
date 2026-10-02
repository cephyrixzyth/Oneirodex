# PR #112 Review Fixes Implementation Plan

> **Doc status:** Archive

> **For agentic workers:** Implement phase-by-phase. After each phase: run targeted tests, do a focused bug/code scan of that phase's diff, only proceed when green. After Phase 5 green: commit, push, ship (mark PR ready).

**Goal:** Close all P0/P1 findings from the PR #112 code review (and P2 polish that is cheap), then ship.

**Architecture:** Keep Alembic as the only forward schema path; fail closed on bad schedules; resolve Auto scan mode on every Manual path; make Unmatched `rom_region` filter consistent for list + export.

**Tech Stack:** Flask/SQLAlchemy, Alembic, pytest, Jinja/admin JS

**Source review:** PR #112 findings (#1–#12)

## Global Constraints

- Do not add DDL to `oneirodex/updateschema.py` (frozen).
- Conventional commits (`fix:` / `test:`).
- Branch: `cursor/cloud-agent-1789260126921-eu1t3` (base `main`).
- After each phase: targeted pytest green before starting the next.
- ASCII-only plan/prompt text.

---

## Phase 1 — P0: Boot schema + Manual Auto (findings #1, #2)

**Files:**
- `oneirodex/init_manager.py` — stamp baseline `b9ab856b09ff` (not `head`); always `alembic upgrade head`; repair if stamped ahead but columns missing
- `alembic/versions/a1c2e3f4b5d6_add_scan_job_schedule_fields.py` — idempotent add_column (skip if present) so create_all + upgrade coexists
- `oneirodex/utils/services/scan_orchestration.py` — idle Manual path calls `resolve_scan_mode_for_path` before folders/files branch
- `tests/test_scan_schedule_helpers.py` — Manual Auto resolution coverage via `resolve_scan_mode_for_path` already; add idle-path regression if easy
- `docs/runbooks/release-checklist.md` / `docs/dev/alembic-baseline-notes.md` — note boot runs upgrade head

**Done when:**
- [x] Fresh DB: upgrade head + check clean
- [x] Baseline-stamped DB without schedule_* receives columns on boot/upgrade
- [x] Idle Manual with `scan_mode=auto` resolves to folders or files (never raw `auto`)
- [x] Targeted tests pass

---

## Phase 2 — P1: Schedule integrity (findings #5, #6, #8, #9)

**Files:**
- `oneirodex/utils/cron_schedule.py` — `validate_cron_expression` probes `next_cron_fire` (bounded) and rejects impossible exprs
- `oneirodex/utils/scan_queue.py` — `normalize_schedule_fields` returns `error` for bad cron / interval < 1 (no silent once); coalesce path `apply_schedule_to_job` on existing Queued row
- `oneirodex/utils/services/scan_orchestration.py` — `handle_auto_scan` flashes and redirects on `schedule_fields.get('error')`
- `oneirodex/routes_admin_ext/scan_jobs.py` — `clear_all_scan_jobs` deletes only terminal statuses (`Completed`, `Failed`, `Cancelled`) by default
- `tests/test_scan_schedule_helpers.py` — invalid cron/interval, coalesce schedule apply, validate impossible cron

**Done when:**
- [x] Bad cron/interval does not start a once job
- [x] Coalesce preserves/updates schedule on Queued row
- [x] Clear-all keeps Scheduled/Queued
- [x] Tests green

---

## Phase 3 — P1: Unmatched region filter (findings #3, #4)

**Files:**
- `oneirodex/routes_apis/scan.py` — when `rom_region` set: load without limit/offset (or filter then slice); `total = len(filtered)`; export applies same filter
- Tests: API or unit coverage for paginate+region total and export parity

**Done when:**
- [x] `paginate=1&rom_region=USA` returns correct page membership and total
- [x] Export with `rom_region` matches list filter
- [x] Tests green

---

## Phase 4 — P1 heuristic + P2 polish (findings #7, #10–#12)

**Files:**
- `oneirodex/utils/services/scan_orchestration.py` — Auto heuristic: `if ext in archive_ext:` only (drop `or ext`)
- `oneirodex/utils/services/scan_identify.py` — `joinedload(Game.library)` on collision selects (if still missing)
- `oneirodex/templates/admin/partials/admin_scan_jobs_panel.html` + JS — When column parity if still divergent
- `tests/test_scan_schedule_helpers.py` — non-ROM extensions do not force files mode

**Done when:**
- [x] Dir + `.jpg` stays folders under Auto
- [x] Targeted tests green

---

## Phase 5 — Verify + ship

**Done when:**
- [x] `pytest` for touched tests + sortable/admin shell
- [x] `alembic upgrade head` + `alembic check` on fresh DB
- [x] Commit + push
- [x] PR #112 updated / ready for review
- [x] Remind Unraid: rebuild + Reset Themes (generator 36) if not already

---

## Out of scope (residual)

- Classic crontab DOM+DOW OR semantics
- WORLD vs USA duplicate policy product change
- Large JS module split (maintainability debt)
