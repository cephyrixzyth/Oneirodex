# Contributing

Public product name is **Oneirodex**. Defaults that are already decided live in [docs/dev/agent-locks.md](docs/dev/agent-locks.md) — do not re-ask them.

## Repo layout

| Path                  | What                    |
| --------------------- | ----------------------- |
| `oneirodex/`          | Flask app               |
| `frontend/member-app` | Household SPA           |
| `frontend/admin-app`  | Admin SPA               |
| `frontend/ops-glance` | Ops widgets             |
| `frontend/api-client` | `@oneirodex/api-client` |
| `frontend/shared`     | `@oneirodex/ui`         |
| `clients/desktop`     | Tauri companion         |
| `tests/`              | pytest                  |
| `docs/`               | [index](docs/README.md) |

## Running things

Servers start through `startweb.sh` / `startweb_windows.cmd` — never `python asgi.py` directly ([ADR 0006](docs/adr/0006-asgi-bridge-a2wsgi.md)).

```bash
# Frontend (from a SPA directory, or via the repo-root workspace)
npm test -- --run          # vitest, scoped to one file where you can
npm run typecheck
npm run lint && npm run format:check   # both — Prettier fails CI on its own

# Python — the database name MUST contain `test` (conftest hard-fails otherwise)
python -m pytest tests/test_whatever.py
```

The test database is the container **`oneirodex-review-db`**. `docker start oneirodex-review-db` if it is stopped; if it does not exist at all, `docker compose -f docker-compose.review.yml up -d db` and create `oneirodextest` — [local-postgres-pytest.md](docs/runbooks/local-postgres-pytest.md). A pytest run that produces no output for minutes is a refused connection, not a slow suite.

Full-tree pytest is **not** all-green today — **42 failed / 4,450 passed** on 2026-09-16, every one named in [test-suite-failures-2026-09-16.md](docs/dev/archive/test-suite-failures-2026-09-16.md). CI runs every test not marked `integration`, minus a named deselect list of known failures ([ci-gates.md](docs/dev/ci-gates.md)) — a new test file is gated by default. Passing CI is still not the full suite: the `integration` modules (live services, Unraid-shaped fixtures) run locally and at release.

## Ratchets — do not regress

```bash
python scripts/api_envelope_lint.py     # JSON sites off api_ok/api_error — 11 documented keeps
python scripts/print_lint.py            # print() calls — 591
python scripts/get_json_lint.py         # raw request.get_json() sites — 103, migrating to @validate_body
node scripts/css-token-lint.mjs         # raw colour/radius/type literals — 0
node scripts/any_lint.mjs               # explicit `any` in .ts/.tsx sources — 1,208 (test harness excluded)
node scripts/od_btn_lint.mjs            # raw <button className="od-btn…"> sites — 0; use <Button> from @oneirodex/ui
node scripts/component_size_lint.mjs    # non-test .tsx over 600 lines — 0; split by responsibility
```

Each records a per-file baseline. `--update` only after a genuine reduction — never to make a red gate green.

## API changes

- JSON replies: `api_ok` / `api_error` from `oneirodex/utils/api_response.py`; pick `error_code` from `ERROR_CODES`. **`detail` is passed to the browser as given** — no secrets, tokens, raw `.env` values, or filesystem paths. Do not shrink the envelope keep-list ([api-envelope-keeps.md](docs/dev/api-envelope-keeps.md)).
- New JSON POST/PUT/PATCH bodies: `@validate_body` on a model in `oneirodex/schemas/` — [pydantic-adoption.md](docs/dev/pydantic-adoption.md). Never batch a file. Partial-success batch routes use `@validate_batch_body` (keeps `updated`/`skipped`/`errors`/`limit` on the 422). Do not wrap those with the flat 422 helper.
- SPA `src/api/` wrappers go through `createBrowserRequester` (member `client.ts`, admin `adminApi.ts`). Do not hand-roll `fetch` + CSRF. Vitest mocks need `content-type: application/json` and `.text()`.
- Typed `create*Api` modules: rewire one resource group at a time. Member collections CRUD uses `createCollectionsApi` via `memberResource` + `withMemberError` so page exports stay the same. Leave `preferences.ts` HTML POST `/settings_panel` and EventSource off this path.

## Identifiers

`ONEIRODEX_*` env only. Do not restore `GT_*` fallbacks. Do not invent `OD_*` env aliases. Token prefix on the wire stays `gt_`. `LEGACY_NAME` is read-only for old theme files.

## Scrub

No Class A / warez-adjacent brand names in diffs, docs, UI copy, or commit messages. Capability language for non-goals. [scrub-shipped-bundles.md](docs/runbooks/scrub-shipped-bundles.md).

## Gotchas

- **`.env` at the repo root is live local config — never overwrite it.** Templates are `.env.example`, `.env.docker.example`, `.env.unraid.example`, `.env.nas.example`.
- The Unraid deploy serves theme CSS/JS from the library **volume**, not the image: a theme change needs `compose up -d --build` **and** Reset Themes before it is visible ([themes-reset.md](docs/admin/themes-reset.md)).
- npm workspaces cannot install on an SMB checkout (junctions are refused); frontend work needs local NTFS ([ADR 0008](docs/adr/0008-npm-workspaces-single-lockfile.md)).
- Windows code signing is out of scope ([desktop-code-signing.md](docs/runbooks/desktop-code-signing.md)).
- Agent-harness files (`CLAUDE.md`, `AGENTS.md`, `.claude/`, `.cursor/`) are deliberately untracked and `tests/test_repo_hygiene.py` fails CI if they become tracked. Put contributor-facing conventions here, not there.

