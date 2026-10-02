# Release checklist (Oneirodex)

> **Doc status:** Active

Use before tagging a release (example: **v0.1.0**).

## Version bump

- [ ] Root [`VERSION`](../../VERSION) matches intended semver
- [ ] [`CHANGELOG.md`](../../CHANGELOG.md) has a dated section for this release
- [ ] `clients/desktop/package.json`, `src-tauri/tauri.conf.json`, **`src-tauri/tauri.thin.conf.json`**, `Cargo.toml` **and `Cargo.lock`** (the lock records the crate's own version; a stale one breaks `--locked` builds)
- [ ] `frontend/member-app`, `frontend/admin-app`, `frontend/ops-glance`, `frontend/api-client`, `frontend/shared` package versions (npm workspaces — the single root [`package-lock.json`](../../package-lock.json) is the only lockfile; there are no per-app lockfiles to bump)
- [ ] Desktop `client_version` needs no edit — it is injected from `package.json` at build time (`__APP_VERSION__`)
- [ ] Leaving pre-release (`X.Y.Z-beta` → `X.Y.Z`)? Add `msi` and `rpm` back to `bundle.targets` in both Tauri configs — they are excluded only because pre-release versions break those two bundlers ([desktop-code-signing.md](desktop-code-signing.md))
- [ ] `docker-compose.yml` image tag (`APP_IMAGE`, preferred Hub `chrisjrovira/oneirodex:X.Y.Z`; local default `oneirodex:1.0.0-beta`)
- [ ] Root `README.md` and `docs/README.md` version references

## CI (PR gate)

GitHub Actions [`.github/workflows/ci-tests.yml`](../../.github/workflows/ci-tests.yml) runs on PRs and pushes to `main` / `master` / `feature/**` (and similar). Toolchain is pinned: Python **3.12** (`.python-version`) and Node **22** (`.nvmrc`, `engines: ">=22 <23"` in every `package.json`).

- **Pytest core** (Python 3.12 + Postgres service): health probes, ASGI static, ops summary/routes, security suite, RBAC unit — not the full `tests/` tree. Hand-listed subset (not the `-m "not integration"` marker — that set is currently the whole tree). Also runs `--cov=oneirodex --cov-report=term-missing --cov-fail-under=35` (the subset reports ~38% line coverage; the floor sits 3 points below for env variance slack — raise it as coverage climbs, see [`ci-gates.md`](../dev/ci-gates.md)), the API envelope lint, and the `print()` ratchet (`scripts/print_lint.py`).
- **Alembic (upgrade + check)** (Python 3.12 + Postgres service, independent of pytest-core): `pip install -r requirements-dev.txt`, then `python -m alembic upgrade head` and `python -m alembic check`. `check` fails hard on any diff — the baseline is kept clean by the `include_object` allow-list in `alembic/env.py` ([`alembic-baseline-notes.md`](../dev/alembic-baseline-notes.md)), so a new operation means a migration is missing.
- **Lint & format** (repo root, Node 22): root `npm ci`, then `npm run lint` (ESLint flat config `eslint.config.js`) + `npm run format:check` (Prettier over `frontend/**`).
- **Member-app vitest** (`frontend/member-app`): `npm test -- --run` + `npm run typecheck`.
- **Admin-app vitest** (`frontend/admin-app`): `npm test -- --run` + `npm run typecheck`, plus classic theme JS harnesses and CSS token lint.
- **Ops-glance vitest** (`frontend/ops-glance`): `npm test -- --run` + `npm run typecheck` **and `npm run build`** — the glance ships in the Docker image, so a broken bundle fails the gate.
- **API client vitest** (`frontend/api-client`): typecheck (`npm run build`) + `npm test`.
- **Shared vitest** (`frontend/shared`, `@oneirodex/ui`): `npm test` — the 11 `src/*.test.*` contract files (csrf, envelopeError, pageStatus, confirmDialog, toastStack, libraryScanNotify, loadingStatusText, useResource, Button, ViewerContext). Since Phase 3.3 the package ships TypeScript (`strict: true`) with a `typecheck` script (`tsc --noEmit -p tsconfig.json`); adding that step to the CI job is a pending workflow change.
- **Desktop vitest** (`clients/desktop`): fast slice — `keychain` / `config-store` / `connection-ux`.

The repo is an npm-workspaces monorepo: the single root [`package-lock.json`](../../package-lock.json) is the only lockfile. Every JS job (`Lint & format`, the five SPA/package vitest jobs, `Desktop vitest`) caches on that root lock and installs with one repo-root `npm ci` — for the jobs that set `defaults.run.working-directory` to an app dir, that step carries an explicit `working-directory: .`. That single install reifies the whole workspace graph (every `frontend/*` app, `@oneirodex/ui`, `clients/desktop`, and the shared `typescript` / `eslint` / `prettier` toolchain); the per-job test / typecheck / build steps then run from the app dir and npm resolves up to the workspace root.

Dependency bumps arrive weekly via Dependabot ([`.github/dependabot.yml`](../../.github/dependabot.yml)) — `pip`, `npm` per app, and `github-actions`. Grouped so each `directory` produces at most one PR per run: minor, patch **and major** bumps are bundled together (npm entries split only production vs development deps). A grouped PR can carry a breaking major, so review it carefully before merging.

Full pytest remains **local / release** (see [local-postgres-pytest.md](local-postgres-pytest.md)). Confirm the core CI job is green before tagging; still run a broader local slice below.

Before image publish: rebuild SPA `static/dist` and grep against the private banned list — [scrub-shipped-bundles.md](scrub-shipped-bundles.md) (SCRUB-7).

## Verify

```bash
pytest tests/test_ops_followons.py tests/test_hardlinks_ai_vr_layouts.py tests/test_q1_foundation_unit.py -q
```

- [ ] CI `ci-tests` workflow green on the release PR / commit
- [ ] CI `desktop-build` green — six unsigned artifacts (full + thin × Windows / macOS / Linux); the upload fails the job if bundling produced nothing
- [ ] Docker build: `docker compose build`
- [ ] Fresh `.env` from `.env.docker.example` starts (`SECRET_KEY` set)
- [ ] Schema: `python -m alembic upgrade head` runs clean on a fresh DB and `python -m alembic check` reports no new operations (allow-list in [`docs/dev/alembic-baseline-notes.md`](../dev/alembic-baseline-notes.md))

## Schema migrations (Alembic)

Since modernization wave A3.1 ([ADR 0004](../adr/0004-adopt-alembic.md)) the schema
is owned by Alembic. `oneirodex/updateschema.py` is **frozen** — new schema
change means `python -m alembic revision --autogenerate -m "..."`, reviewed by
hand, committed under `alembic/versions/`.

Operator upgrade path is unchanged in practice: pull image → `compose up` →
`init_manager` Phase 2 builds/updates the schema and, on the first boot after
Alembic adoption, stamps pre-Alembic databases at the **baseline** revision
(`b9ab856b09ff`, never `head`) then always runs `alembic upgrade head` so
post-baseline revisions (for example scan-job schedule columns) apply without a
manual operator step. Log lines: `Stamped existing schema at Alembic baseline`
and `Alembic upgrade head complete`. `/readyz` green as before.

## Publish

- [ ] Commit + push release branch / PR to `main`
- [ ] Git tag `vX.Y.Z` and GitHub Release notes from CHANGELOG
- [ ] Push Docker image tags `:X.Y.Z` and `:latest` (when publishing images)
- [ ] Unraid / docs note if env vars changed
