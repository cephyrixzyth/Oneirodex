# Which pytest failures are real

> **Doc status:** Archive

**Re-baselined:** 2026-08-12 · Original classification: 2026-08-07

> **Superseded as a status report (2026-09-16).** The "0 failed" below was true
> on 2026-08-12 and is not true now — the current run is **42 failed / 4,450
> passed**, named one by one in
> [test-suite-failures-2026-09-16.md](test-suite-failures-2026-09-16.md). Read this
> file for its *method* (run a file alone against a freshly truncated database) and
> for what the 2026-08 failures turned out to be; do not read its counts as current.

Method unchanged: every candidate file re-run **alone** against a **freshly
truncated** database, so a result never depends on rows some earlier file left
behind. Truncating between files is what makes the numbers mean anything.

## Where it ended up

| | 2026-08-07 | 2026-08-12 |
|---|---:|---:|
| Failures reproducing from a clean DB | 92 | **0** |
| Files affected | 32 | **0** |
| Full run | 113 failed, 3071 passed | **0 failed, 3193 passed** |

The 2026-08-07 per-file table is not reproduced here: it was stale as a work
list within days. Four files that it recorded as failing once or twice failed
*more* on re-measurement, because their counts had only ever been relative to
another file's leftovers — the same bug the table itself warned about, wearing
the opposite sign.

## What the failures actually were

| Cluster | Count | Cause |
|---|---:|---|
| Setup wizard vs login | 10 | `is_setup_required()` means "no users exist", so on a clean DB every anonymous request redirects to `/setup`, not `/login`. Each `..._requires_login` test passed only because an earlier file left a user row behind |
| Page moved to React | 5 | Downloads, play, extensions and the settings hub asserting Jinja output that SPA shells no longer render |
| Mock inventing attributes | 3 | `Mock()` standing in for rows whose serialized surface grew — `full_disk_path` reaching `os.path.abspath`, ORM rows reaching `jsonify` |
| Stale expectation | 8 | Reworded errors, `scaffold` → `enabled`, a placeholder flash that no longer exists, `/tmp` hardcoded on Windows, `os.name` unpinned |
| Product defects | 7 | Below |

The shared precondition now lives in `conftest.py` as `configured_install`.
Tests that drive the wizard itself must not request it — they need the
un-configured state it removes.

## The 2026-08-07 conclusion no longer holds

That pass ended with "the product moved and the tests did not, **in every case
examined so far**". That was true of the first 24 and is no longer true of the
whole set. Seven failures were the product's:

* **`scan_and_add_games` never rolled back a failed `ScanJob` insert.** A
  `library_uuid` with no library trips `scan_jobs_library_uuid_fkey`; the error
  was caught and logged, but the session was left needing a rollback, so every
  later statement — the rest of the request included — raised
  `PendingRollbackError` instead of anything describing the real problem. The
  missing-library handling further down could never run, because the job it
  wants to mark `Failed` could not be inserted at all.
* **`propose_leaf_libraries` stopped proposing nested `ROMs` dumps.** `'ROMs'`
  was added to `DEFAULT_SKIP_DIR_GLOBS` as scan-time scaffolding, and this
  module reuses that list for a different question. Proposing a dump directory
  as its own library is the opposite job from refusing to treat it as a game
  folder, and the skip entry silently vetoed it — including making the
  dump-leaf branch unreachable for the most common dump name there is, against
  the function's own docstring.
* **The settings hub lost its module on/off badges.** The Wave 7 migration
  emptied the Jinja block and nothing replaced them, while the route kept
  computing `settings_hub_module_status()` for a template that ignored it.
  Restored via `GET /api/settings/module-status` and the React `SettingsPage`.
* **`/game_edit` had no scan-job guard**, though image upload/delete and game
  delete all refuse during a scan. Added, so an edit can no longer be silently
  overwritten by a scan writing the same rows.

## The 23 that only failed inside a full run

These were the group set aside on 2026-08-07 as "real order-dependence, worth
fixing but a different job", and the job was expected to be transactional
isolation. It was not. Every one had a specific cause, and an empty database per
test would have concealed all of them rather than fixing any:

* **15 — `get_games` read the settings singleton with an unfiltered
  `select(GlobalSettings)).scalar_one_or_none()`, inside the per-game loop.**
  Two rows in that table and every call raises `MultipleResultsFound`. Every
  other settings read in the codebase already takes the first row by id. Now
  hoisted out of the loop and tolerant, which also removes one full-table query
  per game rendered.
* **6 — `select(GlobalSettings).limit(1)` with no `order_by` in tests.**
  Postgres guarantees no ordering, so with more than one row a test could write
  its configuration to one row while the code under test read another.
  `test_indexer_registry`'s helper wipes hub URLs so tests "do not inherit prior
  Prowlarr/Jackett keys" — it was writing that wipe to a row nobody read.
* **2 — assertions over every row in the database.** `browse_path_status`
  fetched `/browse_games` unscoped, so games from other files pushed its titles
  off the first page; `test_unmatched_wave17` asserted an exact id set across all
  unmatched folders. Both are scoped to their own library now — which is what
  the neighbouring query in that same test was already doing.

`test_login_rate_limit.py` was also leaking: it set `ENABLE_LOGIN_RATE_LIMIT`
and a 3-attempt window process-wide in `setup_function`, and the teardown reset
only the limiter's own state, so every file after it ran with login rate
limiting on. Saved and restored now. It was not causing any of the 23, which is
worth saying — it was found while looking for a shared cause that did not exist.

## Two traps worth not re-deriving

**`Mock(name='X')` does not set `.name`.** The constructor consumes `name` for
the mock's repr, so `game.name` was a child Mock throughout the discover tests
— which is how a Mock reached the cover-placeholder path builder. Namespaces are
used there now: they can only supply what a test actually declares, which is the
property that made the `full_disk_path` gap visible instead of silent.

**Patching `<module>.os.path.join` patches it globally.** `oneirodex.routes.os`
*is* the `os` module, so `@patch('oneirodex.routes.os.path.join')` replaces
`os.path.join` everywhere — and `pathlib` joins through it, so building a path
with `tmp_path / name` inside such a patch returns the mock's own value.

## Reproducing

```bash
python -m pytest -q --tb=no
```

To re-measure a single file honestly, truncate first — otherwise "fails alone"
and "fails against residue" are the same result.

## 2026-09-10: per-test isolation landed, so residue is no longer the variable

`db_session` now wraps each test in a rolled-back SAVEPOINT (see
[test-harness-2026-09-10.md](../test-harness-2026-09-10.md)). "Fails alone" and
"fails in a full run" converge, because no file leaves rows for the next one.
The classes above did not come back; what the empty-per-test database exposed
instead was a set of `..._requires_login` and `..._database_error` tests that
had been inheriting a user row or a `GlobalSettings` row from an earlier file —
the same "Setup wizard vs login" shape as the 2026-08-07 cluster, fixed the
same way (`configured_install` / `global_settings` as an explicit precondition).
