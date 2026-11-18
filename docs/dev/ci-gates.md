# CI gates — what runs, and what is owed

> **Doc status:** Active

Replaces `ci-wishlist.md`, which was an append-only request queue between the
modernization tracks (a track appended a line, the CI owner applied it). The
tracks are gone; every applied item is now either in the workflow or in an ADR.
What remains is this: the gates as they stand, and the two that are still owed.

## Jobs in `.github/workflows/ci-tests.yml`

| Job | What it gates |
|---|---|
| `pytest-core` | Builds the member, auth-pilot, and admin React shells, then runs **`tests/ -m "not integration"`** with no exclusions, coverage (65% floor), and the API-envelope, print, and get-json ratchets. A new test file is gated by default |
| `alembic-check` | Fresh Postgres → `alembic upgrade head` → `alembic check`. Fails hard on any model/migration drift |
| `lint` | Repo-root `npm ci`, then `npm run lint` **and** `npm run format:check` (Prettier has failed a PR on its own — do not skip it) |
| `member-app-vitest` · `admin-app-vitest` · `ops-glance-vitest` | Per-SPA vitest + `npm run typecheck`. `ops-glance` also builds. `admin-app-vitest` carries `css-token-lint`, `any_lint`, `od_btn_lint` and `component_size_lint` |
| `api-client-vitest` · `shared-vitest` | Workspace package tests + typecheck |

`desktop-build.yml` adds `rust-checks` (fmt + clippy + test) and a 6-way
installer matrix (windows/macos/linux × full/thin), both behind path filters.

Every JS job caches on the root `package-lock.json` and installs once at the
repo root — see [ADR 0008](../adr/0008-npm-workspaces-single-lockfile.md).

## Owed

### Marker-set gate status

The marker-based gate replaced the hand-enumerated test selection on
2026-09-17. The CI job builds the three React bundles consumed by Python route
tests before running pytest; without those artifacts, shell routes can fail
with 503 responses even though the Docker image includes the bundles.

The known-failure `--deselect` list was emptied on 2026-11-17, when the suite
moved onto the app production serves. Keep it empty: fix a failing test, or
remove it when the behaviour it checks is retired.
The core job has a 90-minute timeout: run 42534095194 was canceled at the
previous 35-minute deadline with pytest at 70%. This extends the observation
window without changing test selection or the 65% coverage floor.
Treat workflow evidence for the current commit as authoritative; older timing
and coverage measurements below this section are historical and must not be presented as current results.

The 65% coverage floor and three ratchets are enforced after pytest succeeds.
Thus a red pytest run provides no evidence that those later gates passed.

## Conventions that outlived the wishlist

- A test file under `tests/` is gated **by default**. Mark a module
  `pytest.mark.integration` only when it genuinely needs live services or
  Unraid-shaped fixtures. Do not deselect individual tests.
- Ratchets only ever move down. `--update` after a genuine reduction, never to
  make a red gate green.
- Prettier and ESLint are separate failures; run both before pushing.
