# Workspace disk hygiene

> **Doc status:** Active

**Audience:** maintainers / agents cleaning a large local clone before Unraid or Docker work.  
**Not for:** operators on Unraid — image size ≠ workspace size; caches below never ship in the Hub image when `.dockerignore` is current.

## Why this exists

A full clone can balloon past **1 GB** from regenerable caches while the **shipped** surface stays small: Python app + vendored WebRetro cores (~72 MB) + SPA built inside Docker. Local `node_modules` and Tauri `target/` are **dev-only**.

**Unraid host disk is separate:** if the array/cache is ~99% full, free space on the **NAS** before `git pull` / `docker compose build` — wiping workspace caches here does not free array capacity. See [unraid-deploy.md § Deploy gates](unraid-deploy.md#deploy-gates-operator-checklist). The live stack is `/mnt/user/example-share/_projects/Oneirodex` (`Z:\_projects\Oneirodex` on Windows). Games are `/mnt/user/example-share/_software/_games`, not the repo. `/mnt/user/isos/oneirodex/` is retired.

## KEEP (never delete)

| Path | Why |
|---|---|
| `.git/` | History; optional `git gc` only (see below) |
| `oneirodex/static/vendor/webretro/` | Honesty matrix + browser play; image expects these cores |
| Source trees (`oneirodex/`, `frontend/`, `clients/desktop/src*`, `tests/`, `docs/`) | Product |
| `requirements.txt` / lockfiles / `.env*.example` | Reproducible installs |
| Tracked DAT/docs policy files | Operator guides — not regenerable caches |

## SAFE DELETE anytime (regenerable)

| Path | Approx | Rebuild |
|---|---|---|
| `clients/desktop/src-tauri/target/` | ~0.5–1 GB | `cd clients/desktop && npm ci && npm run tauri:dev` (or `tauri:build`) |
| `**/node_modules/` | hundreds of MB | one `npm ci` at the repo root — npm workspaces install every SPA + `clients/desktop` from the single root `package-lock.json` |
| `**/__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` | small | next pytest / import |
| Host `oneirodex/static/dist/` | if present | Docker build or local `npm run build` in each frontend app |
| Vitest/Vite caches under `node_modules/.vite/` | tiny | next `npm test` / `vite` |
| A literal `%TEMP%/` directory at the repo root | varies | nothing — it is scratch, see below |

**A folder literally named `%TEMP%`.** If you see one at the repo root, it is an artifact, not a
mistake anyone made twice: a script written for `cmd.exe` was run under bash or Git Bash, where
`%TEMP%` is not expanded and becomes a directory name. It is gitignored, so it never reaches a commit,
but it accumulates whatever the script meant to put in the system temp directory. Safe to delete
outright. One was removed on 2026-08-16 holding 188 files (~1.3 MB) of July scratch. When writing a
script that both shells may run, use `$TMPDIR`/`mktemp` or a path under the scratch directory rather
than a Windows environment-variable literal.

PowerShell one-shot (caches only — does **not** touch webretro or `.git`):

```powershell
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
  clients\desktop\src-tauri\target,
  frontend\member-app\node_modules,
  frontend\admin-app\node_modules,
  frontend\ops-glance\node_modules,
  clients\desktop\node_modules,
  .pytest_cache, .ruff_cache, .mypy_cache
Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
```

## Docker image vs workspace

| Concern | Fact |
|---|---|
| Build context | `.dockerignore` must exclude `node_modules/`, `clients/`, `**/src-tauri/target/`, host `static/dist/`, `.git/` |
| Image contents | Multi-stage `npm ci` + `pip install`; WebRetro cores **copied in** from `oneirodex/static/vendor/webretro/` |
| Unraid after local wipe | **No effect** on running container. Rebuild image from clean context: `docker compose build --no-cache` (or Hub pull). Do **not** bind-mount an empty cores dir over image cores — see [webretro-cores.md](webretro-cores.md) |

## OPTIONAL shrink (caveats)

| Action | Effect | Risk |
|---|---|---|
| `git gc --aggressive` | May reclaim tens–hundreds of MB inside `.git` | Slow; local only |
| Shallow clone (`--depth 1`) | Tiny `.git` | Loses history for blame/bisect/release archaeology — avoid for maintainers |

## After wipe — verify local-dev

```bash
# Python
pip install -r requirements.txt   # or use existing venv
pytest -q                         # or project’s usual subset

# SPAs (npm workspaces — one root install, then per-app scripts)
npm ci                                   # at the repo root; installs every workspace
npm run build --workspace=member-app && npm test --workspace=member-app -- --run
npm run build --workspace=admin-app  && npm test --workspace=admin-app  -- --run

# Desktop companion
npm test --workspace=oneirodex-desktop && cd clients/desktop && npm run tauri:dev
```

## Related

- [webretro-cores.md](webretro-cores.md) — cores must stay; optional host mount
- [scrub-shipped-bundles.md](scrub-shipped-bundles.md) — rebuild `static/dist` before publish
- [unraid-deploy.md](unraid-deploy.md) · [docker-compose-deploy.md](docker-compose-deploy.md)
