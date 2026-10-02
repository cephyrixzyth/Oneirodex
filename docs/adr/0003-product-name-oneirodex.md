# ADR: Product name Oneirodex

> **Doc status:** Active

**Date:** 2026-08-26  
**Status:** Accepted — **Phase 1 (public string) landed 2026-08-26**. **Phase 2 (ops identifiers) started 2026-08-27**. **Phase 3a landed 2026-08-27.** **Phase 3b landed 2026-08-31.** **Clean break (env): `ONEIRODEX_*` is the only prefix; `GT_*` is not read; `RESET GAMETHECA` is not accepted.** Git history is not rewritten.  
**Owners:** `maintainer` · `agent-docs`

## Context

The public product string used to be **GameTheca**. The Python package, Docker image, GitHub repo, Compose/Unraid names, env prefix `GT_*`, and CSS `--gt-*` / `.gt-*` followed that root until the phased cutover. A rename was requested; twenty cosmic-horror-register options were checked against game libraries, launchers, ROM managers, *arr / Unraid-adjacent tools, Steam/itch, and exact GitHub / PyPI / npm slugs. **Oneirodex** was selected.

## Decision

**Public product name is Oneirodex.**

| | |
|---|---|
| Spelling | Oneirodex — one word, capital O. Not OneiroDex, not ONEIRODEX in UI |
| Say it | oh-NY-roh-dex |
| Slug | `oneirodex` |
| Sense | Catalog of dreams / household catalog against the vast. Coined from *oneiros* + dex. No Cthulhu / Arkham / Carcosa proper nouns |

Phase 1 (this wave):

- User-facing copy, Help, README, user/admin docs, and CHANGELOG going forward say **Oneirodex**.
- Package path stays `oneirodex/`. Docker / Compose / Unraid container **names** stay `oneirodex-*` by default so existing installs keep working.
- GitHub is `chrisjrovira/oneirodex` (the old `chrisjrovira/gametheca` URL redirects).
- Env: `ONEIRODEX_*` is the only prefix. The former `GT_*` fallback is gone (`product_env.PREFIX`). Do not invent `OD_*` env aliases.
- Danger-zone confirm is `"RESET ONEIRODEX"`. `"RESET GAMETHECA"` is not accepted.

Do not mix **OneiroDex** or **ONEIRODEX** into UI. Historical CHANGELOG entries and git history keep the old public string.

## Snapshot (2026-08-26, not counsel)

Related-space: no current product named Oneirodex in game libraries, launchers, ROM managers, or self-hosted media.

| Surface | Result |
|---|---|
| PyPI `oneirodex` | 404 |
| npm `oneirodex` | 404 |
| crates.io `oneirodex` | 404 |
| GitHub user `oneirodex` | 404 |
| Docker Hub user / library `oneirodex` | 404 |
| `oneirodex.com` / `.dev` / `.app` / `.net` / `.org` | RDAP 404 (treat as unregistered) |
| `oneirodex.io` | RDAP inconclusive (nic.io DNS fail; Identity Digital 404 may be the wrong TLD server) |

Adjacent, not the same mark:

- **Oneiro** — Steam indie title; C++ engine (`OneiroGames/Oneiro`); Oneiro N.A. Inc. / oneiro.io (unrelated industry).
- A blog used **ONEIRODEX™** as a fictional drug name. Not a shipped software product. Flag for trademark counsel later.

Web search found no USPTO / EUIPO hit for Oneirodex as a live software mark. That is **not** a clearance opinion.

## Cutover

1. **Public string** — UI, Help, README, user/admin docs, CHANGELOG going forward. Package and Docker unchanged. **Done 2026-08-26.**
2. **Ops identifiers** — image `chrisjrovira/oneirodex`, containers, Unraid template, GitHub repo. Keep redirects / dual names for existing installs. **GitHub rename done.** Compose `APP_IMAGE` / `APP_CONTAINER_NAME` defaults are **`oneirodex:1.0.0-beta` / `oneirodex-app`** (P3b). Live Unraid may pin `APP_CONTAINER_NAME=oneirodex-app` until the scan FIFO is idle. OCI title label **Oneirodex**; `SUPPORT_GITHUB_REPO` defaults to `chrisjrovira/oneirodex`. Hub image still operator-publish. Do not rename running Unraid containers mid-scan.
3. **Code identifiers** — Python package, remaining `GT_*` / `.gt-*` classes. **Phase 3a started 2026-08-27:** dual env + `--od-*` token aliases. **Phase 3b landed 2026-08-31:** package `oneirodex/`, `.od-*` / `--od-*`, live `oneirodex-*` containers, Postgres `oneirodex`. **Clean break after that:** `ONEIRODEX_*` only; `RESET GAMETHECA` retired. Do not rewrite git history.

Existing installs must keep working through (2) and (3). Do not rewrite git history for the old name.

## Consequences

| Pros | Cons |
|---|---|
| Unique in the related space; sayable; already means catalog | Full mechanical rename is a dedicated wave, not a drive-by |
| Avoids crowded Game* / Play* / *arr collisions | Adjacent *Oneiro* root exists; fictional ONEIRODEX™ exists in prose |
| Slug still free on GitHub / PyPI / npm / most domains (26 Aug 2026) | Unclaimed names go fast; `.io` not confirmed |

## Related

- [agent-locks.md](../dev/agent-locks.md) (cutover lock)
- Living progress board (local strategy notes)
- [docs/README.md](../README.md) naming table
