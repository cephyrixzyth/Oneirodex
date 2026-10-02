# CI gates — what runs, and what is owed

> **Doc status:** Active

Replaces `ci-wishlist.md`, which was an append-only request queue between the
modernization tracks (a track appended a line, the CI owner applied it). The
tracks are gone; every applied item is now either in the workflow or in an ADR.
What remains is this: the gates as they stand, and the two that are still owed.

## Jobs in `.github/workflows/ci-tests.yml`

| Job | What it gates |
|---|---|
| `pytest-core` | **`tests/ -m "not integration"` minus a named `--deselect` list** (flipped 2026-09-17) + `--cov=oneirodex --cov-fail-under=65`, then three ratchets: `api_envelope_lint`, `print_lint`, `get_json_lint`. A new test file is gated by default |
| `alembic-check` | Fresh Postgres → `alembic upgrade head` → `alembic check`. Fails hard on any model/migration drift |
| `lint` | Repo-root `npm ci`, then `npm run lint` **and** `npm run format:check` (Prettier has failed a PR on its own — do not skip it) |
| `member-app-vitest` · `admin-app-vitest` · `ops-glance-vitest` | Per-SPA vitest + `npm run typecheck`. `ops-glance` also builds. `admin-app-vitest` carries `css-token-lint`, `any_lint`, `od_btn_lint` and `component_size_lint` |
| `api-client-vitest` · `shared-vitest` | Workspace package tests + typecheck |

`desktop-build.yml` adds `rust-checks` (fmt + clippy + test) and a 6-way
installer matrix (windows/macos/linux × full/thin), both behind path filters.

Every JS job caches on the root `package-lock.json` and installs once at the
repo root — see [ADR 0008](../adr/0008-npm-workspaces-single-lockfile.md).

## Owed

### 1. ~~The `pytest-core` hand list should become `-m "not integration"`~~ — done 2026-09-17

**Measured:** the marker set is **3,792 tests in 11m24s** on `ubuntu-latest` (PR #118's timing job), 474 deselected by the marker. Flipped in the PR after it; `timeout-minutes` 20 → 30 for coverage overhead.

**The discipline that replaces the hand list:** the `--deselect` lines in `ci-tests.yml` are the exception list — the known failures from [test-suite-failures-2026-09-16.md](archive/test-suite-failures-2026-09-16.md) as they reproduce on the runner (31; three are runner-only). Remove a line when its test is fixed. **Never add one to turn a red PR green** — that is the hand list growing back under another name.

**Why it mattered, concretely:** the 2026-09-16 full run found **42 failures**,
and **not one of their files is named in the hand list**. The list gates nothing
it does not name, so a PR can break a file it never runs. See
[test-suite-failures-2026-09-16.md](archive/test-suite-failures-2026-09-16.md).

**What is already done:** the `integration` marker is declared in `pytest.ini`
and applied to **32 modules** (the scan pipeline, external provider adapters —
IGDB / Steam / SteamGridDB / SMTP — and the worker/heartbeat/watch/LiveKit/
cover-render modules). None of them are in the hand list, so tagging them took
nothing out of the gate.

**What blocks the flip:** `-m "not integration"` currently selects ~3,699 of
~4,450 tests. The local full run takes **48 minutes**, though that is NAS I/O
and a per-test Flask fixture, not runner hardware. Before flipping, measure the
marker set on a runner (empty Postgres, no SMB) against the 20-minute budget,
and tag more modules from that timing data if it does not fit. Flip only when
the measured number is known — not on the assumption that CI is faster. **The `pytest-marker-timing` job now produces that number on every PR.**

### 2. ~~`--cov-fail-under` sits below the real number~~ — retuned 2026-09-17

The marker set reports **68%** line coverage (PR #121's run) against the hand
list's 38%. Floor set to **65** — the same 3-point slack for environment
variance. Raise it as coverage climbs; it only ever moves up.

## Conventions that outlived the wishlist

- A test file under `tests/` is gated **by default**. Mark a module
  `pytest.mark.integration` only when it genuinely needs live services or
  Unraid-shaped fixtures; deselect a single test only when it is a known,
  documented failure.
- Ratchets only ever move down. `--update` after a genuine reduction, never to
  make a red gate green.
- Prettier and ESLint are separate failures; run both before pushing.
