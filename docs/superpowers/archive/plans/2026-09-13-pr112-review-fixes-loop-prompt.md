# Loop prompt — PR #112 review-fix phases

> **Doc status:** Archive

Copy-paste this into a new agent turn (or re-invoke yourself) to drive the plan to completion.

---

```text
Continue the PR #112 review-fix plan at docs/superpowers/plans/2026-09-13-pr112-review-fixes.md on branch cursor/cloud-agent-1789260126921-eu1t3.

Rules:
1. Work ONE phase at a time in order (1 → 5). Do not start the next phase until the current phase is green.
2. For the current phase:
   a. Implement the phase checklist items (code + tests).
   b. Run the phase's targeted pytest (and alembic upgrade head + check when Phase 1 or 5).
   c. Bug/code scan the phase DIFF only: look for regressions, missed call sites, silent fail-open, and test gaps for what you just changed.
   d. If the scan finds issues, fix them and re-run tests. Repeat until clean.
   e. Commit with a conventional message for that phase (fix:/test:/docs:). Push.
   f. Mark the phase Done in the plan checkboxes.
3. After Phase 5 is green: push, ensure PR #112 is ready for review (not draft), summarize remaining residual risks, and remind: Unraid rebuild + Reset Themes (generator 36) if theme assets changed.
4. Do not edit updateschema.py (frozen). Do not force-push. Do not expand scope beyond the plan.
5. If blocked (missing DB, flaky CI unrelated to this PR), document the blocker, fix what you can locally, and continue.

Start by reading the plan, git status, and which phase checkboxes are still open — then execute the first incomplete phase.
```

---

## Phase quick map

| Phase | Theme | Gate |
|-------|--------|------|
| 1 | Alembic boot upgrade + Manual idle Auto resolve | pytest schedule helpers + alembic check |
| 2 | Cron/interval fail-closed, coalesce schedule, clear-all terminal-only, cron probe | pytest schedule helpers |
| 3 | Unmatched rom_region pagination + export parity | API/unit tests for region |
| 4 | Auto ext heuristic + P2 polish | pytest heuristic cases |
| 5 | Full verify + ship | CI green / PR ready |
