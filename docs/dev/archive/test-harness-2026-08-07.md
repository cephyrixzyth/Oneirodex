# Test harness — why the suite never finished

> **Doc status:** Archive

**Date:** 2026-08-07 · **Status:** deadlock fixed, failures classified

## The symptom

A full `pytest` run stopped at 33% and stayed there. The process used **zero
CPU**, nothing had failed, nothing had timed out, and the log had simply
stopped mid-line. It had been running for hours and looked slow.

It was not slow. It was deadlocked.

## What was actually happening

`py-spy dump` on the stuck process pointed at the `db_session` fixture, inside
`add_column_if_not_exists`, blocked in SQLAlchemy's `do_execute`. Postgres
showed a three-way block:

| pid | state | statement |
|---|---|---|
| A | `idle in transaction` | `DELETE FROM game_developer_association …` |
| B | `Lock/relation`, blocked by A | `ALTER TABLE games ADD COLUMN …` |
| C | `Lock/relation`, blocked by B | `SELECT games …` |

Two independent defects combined:

**1. The schema was rebuilt on every test.** `db_session` is function-scoped
and called `db.create_all()` *and* the whole incremental migration for each
one. The schema cannot change mid-run, so this was pure repetition — but not
harmless repetition, because `add_column_if_not_exists` issues a long series of
`ALTER TABLE`s and each wants an ACCESS EXCLUSIVE lock. One connection left
idle in a transaction anywhere is then enough to stop the entire suite.

**2. Nothing set a lock timeout.** Postgres waits forever by default, so the
failure mode was silence rather than an error.

## The fixes

* Schema setup runs **once per run**, behind a module-level guard.
  `tests/test_routes_library.py` went from 102s to 25s, still 27/27.
* Test connections set `lock_timeout` and
  `idle_in_transaction_session_timeout`, turning a wedge into a named error on
  the statement that could not get its lock. Production is untouched, where
  blocking on a real lock is usually correct.
* `tests/test_harness_locking.py` pins both, and checks the timeout on a
  **pooled connection after real rollbacks** rather than trusting conftest's
  source text — see the footgun below.

### Footgun: `SET` is transactional

The first version of the timeout listener ran `SET lock_timeout` on the raw
DBAPI connection inside its implicit transaction. Postgres treats `SET` as
transactional, so SQLAlchemy's first pool rollback silently reverted it —
restoring the exact silent hang the setting exists to prevent, while conftest
still *read* as though it were configured. It runs in autocommit now.

## Results

The suite now finishes: **113 failed, 3071 passed in 25:31**.

The 113 is not new. It matches the figure that had been carried in notes as
"cross-file state leakage"; what was new is that the run could reach the end
and report it.

**2026-08-12: 3193 passed, 0 failed in 23:35.** See
[test-harness-failures.md](test-harness-failures.md) for what the 113 turned out
to be — the short version is 92 stale-or-defective from a clean database and 23
that needed the rest of the suite, and that the second group did *not* need the
transactional isolation this document proposed for it.

## Two wrong theories, recorded so they are not re-derived

**"Rows accumulate in the test database."** They do — a run left 98 users, 89
filters, 63 libraries and 43 games behind, and nothing ever resets it. But that
is *not* what causes the failures: `test_routes_library.py` fails 15 times in
the suite and passes 27/27 alone **even against the polluted database**. Row
accumulation is real and worth fixing; it is not this.

**"It is all one shared-state problem."** It is not. Running every affected
file alone against a **freshly truncated** database splits the 113 into 92 that
reproduce from clean and 22 that need the rest of the suite. Those need
different fixes and should not be discussed as one number.

A third correction, on my own method: the first classification pass ran each
file against whatever the previous run had left in the database, so "fails
alone too" could have meant "fails against residue". `test_indexer_registry.py`
looked genuine under that method and is not. Truncating between files is what
makes the column mean anything.

## Classification

See [test-harness-failures.md](test-harness-failures.md) for the per-file split
and for what the fixed clusters turned out to be — the short version is that
the product moved and the tests did not, in every case examined so far.

## Test runs mutate the dev install — found, 2026-08-12

The suspected mechanism was app boot. It was not: `create_app()` never runs
`InitManager`, so the `DEV_MODE` branch in `_setup_default_theme` that does
`shutil.rmtree(themes/default)` is only reached by a real server start.

It was a test. `/admin/themes/reset` resolves its target from
`current_app.root_path` and really calls `shutil.rmtree` on it, and four tests
in `test_routes_admin_ext_themes.py` drove that route against the installed
package. `test_reset_default_themes_copy_failure` mocked `shutil.copytree` but
**not** `shutil.rmtree`, so the removal happened for real and the mocked copy
then failed before anything put the tree back.

Three of the four never tested what they claimed. They patch `os.path.exists`;
the route was moved to `pathlib`, so nothing was intercepted — `missing_source`
and `unexpected_error` both sailed past the guard they meant to trip, ran a
full real reset, and passed by matching the *success* log, because the
assertion was only `mock_log.assert_called()`. Same shape as every other
cluster in this campaign: the product moved and the tests did not.

The fix is a `theme_sandbox` fixture that repoints `app.root_path` at
`tmp_path`, so the reset runs for real against a throwaway tree. Assertions now
match on the logged message rather than on the call count, which is what let a
success masquerade as an error. The three `apply_theme` tests that wrote real
directories into `static/library/themes` use the same sandbox.

`themes/default` was still missing from this working copy when the cause was
found — the nine presets were intact, `default` was not — and has been restored
from `oneirodex/setup/default_theme` (the tree is generated and gitignored, so
a boot or Admin → Reset Default Themes rebuilds it).

## Still open

* **No isolation between tests.** Rows still accumulate: nothing resets the test
  database between files, and a run still ends with users, libraries and games
  from every file that made them.

  This was going to be fixed by wrapping each test in a rolled-back transaction,
  binding every session to one connection so the Flask test client could see
  uncommitted data. **That turned out to be the wrong tool for the 23 failures
  it was proposed for**, and the change was not made. Each of the 23 had a
  specific cause — an unfiltered `scalar_one_or_none()` on a singleton table,
  `limit(1)` without `order_by`, and two assertions written against every row in
  the database instead of the test's own. Transactions would have hidden all
  four behind an empty database rather than fixing any of them, at the cost of a
  change touching all 3,193 tests.

  Accumulation is still worth removing on its own merits — it makes runs slower
  and every unscoped assertion a latent failure. It is no longer blocking a
  green suite, so it should be done deliberately rather than under pressure.

  **Done, 2026-09-10.** `db_session` now wraps each test in a rolled-back
  SAVEPOINT bound to one connection. This is the change this note said not to
  make *for the 23 failures* — those causes were fixed on their own — done
  later on its own merits. See
  [test-harness-2026-09-10.md](../test-harness-2026-09-10.md) for the SAVEPOINT
  model, the savepoint-restart listener and exception-safe teardown it needs,
  and the per-clean-database fallout (`configured_install` / `global_settings`
  preconditions the suite used to inherit from an earlier file).
