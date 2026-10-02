# ADR 0008: npm workspaces with a single root lockfile

> **Doc status:** Active

**Date:** 2026-09-16 (records wave B1.1, 2026-09-09)
**Status:** Accepted
**Owners:** `agent-uiux` · `agent-ops` · `agent-desktop`

## Context

Six JavaScript packages live in one repository (`frontend/{member-app,
admin-app, ops-glance, api-client, shared}` and `clients/desktop`). Before
wave B1.1 each carried its own `package-lock.json`, `clients/desktop` consumed
`@oneirodex/api-client` through a `file:` link, and the shared toolchain
(eslint, prettier, typescript) was pinned in a root `package.json` that no app
declared — so a SPA's `npm run typecheck` only worked if someone had run a
root `npm ci` first. CI encoded that ordering by hand in every job.

## Decision

**The repo root is the one install point.** `package.json` declares the six
workspaces; `package-lock.json` at the root is the **only** lockfile.

- `npm ci` at the root reifies the whole graph; `@oneirodex/ui` and
  `@oneirodex/api-client` resolve as workspace links, and `clients/desktop`'s
  dependency is `"*"` rather than `file:`.
- CI jobs cache on the root lock and run one `Install workspace (repo-root
  npm ci)` step; per-app steps keep `working-directory: frontend/<app>` and
  run unchanged (`ci-tests.yml`, `desktop-build.yml`).
- The Dockerfile's `frontend-build` stage runs one root `npm ci` (it also
  installs the desktop toolchain — a throwaway cost in a discarded stage;
  scope with `--workspace` if it ever matters).
- Dependabot groups npm updates per workspace, **minor/patch only** —
  vite/vitest/typescript majors are manual (`.github/dependabot.yml`).

**Hazard recorded, not solved:** npm links workspace packages with
**junctions on Windows**, which an SMB mount refuses (`EPERM`). On this
project's NAS checkout (`Z:`) a root `npm ci` half-succeeds — `node_modules/`
fills but `node_modules/@oneirodex/` stays empty, so anything importing a
workspace package (vitest, `tsc`, eslint's config imports) fails. **All
frontend work happens in a worktree on local NTFS (`C:\od-modz\…`)**; backend
and docs work is fine on the share. CI (Linux) and Docker (alpine) are unaffected.

## Consequences

| Pros | Cons |
| --- | --- |
| One `npm ci`, one lock, one place to bump a shared dep | The root lock is large and every workspace's change touches it |
| Workspace packages are first-class imports, not `file:` copies | Windows + SMB cannot install it; the C:-worktree rule is a documented workaround, not a fix |
| CI and Docker install identically | A per-app `npm ci` is now wrong and will drift — the old habit has to be unlearned |

## Related

- ADR 0007 — the packages
- `docs/dev/ci-wishlist.md` — the B1.1 reconciliation notes (retired once folded here)
