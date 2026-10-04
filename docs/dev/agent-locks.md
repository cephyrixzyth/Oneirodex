# Oneirodex agent locks

> **Doc status:** Active

Canonical product and engineering defaults. Current user instructions and previously accepted session decisions override historical defaults; never require the user to repeat them.

## Rebuild brief accepted 2026-09-26

Review and retain every researched feature regardless of build status or former stance. Research inclusion is not an implementation claim. New priorities are easy standalone Windows/macOS/Linux installation with a later household-server upgrade, Steam Deck usability, store connection/onboarding/repair, ownership deduplication and store/ownership filters, and launcher/runtime interoperability. Evaluate Lutris, ScummVM, Humble and additional major gaming services by actual capability and supported access method.

The ownership-only/DRM-install non-goals below describe the **existing** implementation boundary, not a prohibition on this newly requested feasibility review. Installation and launch support must be explicit per provider; never promise universal access or bypass DRM. Keep historical rejected ideas in private research with their original stance and provenance. Other unmodified defaults remain in effect.

This file replaces the old `.cursor/skills/prompt-brief/defaults.md` and the duplicate "Shared locks" list that used to live in `agent-team`. It is the single source; skills and agents link here rather than restating it.

## Product mission

**Oneirodex is the self-hosted household gaming sphere** — one Unraid-friendly service that turns a family's **already-owned** PC and console libraries into a shared, honest catalog: scan and match with real metadata, browse Systems and Discover, play where the platform allows (browser · companion · catalog), stay present with household social, and **BYO acquire** for content they choose to add.

It is **not** a DRM store client, a Discord clone, or a pirate marketplace.

**North-star surfaces:** library · systems · ownership/metadata · play · social · admin/ops · BYO acquire.

### Why this exists

| We are building… | We are not building… |
|---|---|
| A **multi-user home library** for DRM-free / dumped / owned games on NAS + Compose | A Steam/Epic/PSN download or install client |
| **Honest match + metadata** (IGDB + Class D stores; propose-only when unsure) | Fuzzy auto-import that invents wrong IDs |
| **Play honesty** — Browser / Companion / Catalog badges that match capability | Fake "Play in browser" for Switch / Arcade / Neo Geo AES |
| **Native household social** (chat · presence · optional LiveKit) | Discord bots, webhooks, or Discord-as-product |
| **Operator-owned acquire** (Torznab/Newznab · Prowlarr/Jackett · debrid hubs) | Bundled torrent/debrid marketplace or magnet scrapers past Torznab |
| **Ownership registers** for DRM stores (CSV / sync marks only) | Store download queues or DRM circumvention |
| Scrubbed public surface (no Class A / warez-adjacent brands) | Peer teardown catalogs in tracked docs |

### Attainment checklist

Prioritize against this — every backlog item should advance at least one row, or be explicitly hygiene/process.

1. **Library truth** — leaf libraries, scan depth, skip-dir, Unmatched triage → matched catalog over time
2. **Systems coverage** — correct platform enums + leaves (PC + consoles); tiles appear when Ops creates leaves
3. **Metadata quality** — Stage A–E / DAT / Identify chips; no poisoned App IDs
4. **Play paths** — WebRetro where real; companion/thin where needed; catalog-only when honest
5. **Household multi-user** — invites, ACL, social without Discord
6. **Ops reliability** — Unraid deploy, volumes, themes reset, readiness, ship gates
7. **Acquire BYO** — indexer registry + hubs; never DRM install queues

## Product name (Phase 1 landed 2026-08-26)

**Public name: Oneirodex** (oh-NY-roh-dex) · slug `oneirodex` · [ADR 0003](../adr/0003-product-name-oneirodex.md).

Write **Oneirodex** in UI, Help, README, and operator docs. **P3b landed 2026-08-31:** Python package `oneirodex/`, CSS `.od-*` / `--od-*`, Compose `oneirodex-*`, Postgres database `oneirodex` (pytest `oneirodextest`). **`ONEIRODEX_*` is the only env prefix** — `GT_*` is not read. Do not invent `OD_*` env aliases. Danger-zone confirm is `RESET ONEIRODEX` (no legacy alias). Preferred Hub image once published: `cephyrixzyth/oneirodex`. GitHub is `cephyrixzyth/oneirodex`. Origin URL is `https://github.com/cephyrixzyth/oneirodex.git`. API tokens keep the on-wire `gt_` prefix. Do not mix OneiroDex into copy. Do not rewrite git history for the old name.

| Default | Value |
|---|---|
| Spelling | Oneirodex — one word, capital O. Not OneiroDex, not ONEIRODEX in UI |
| Phase 1 | Oneirodex everywhere user-facing — **landed** |
| Phase 2 | Ops dual names — `APP_IMAGE` / `APP_CONTAINER_NAME`; Hub `cephyrixzyth/oneirodex` preferred; GitHub `cephyrixzyth/oneirodex`; existing `oneirodex-*` names still work as pins |
| Phase 3a | Dual env (superseded) |
| Identifiers left | Hub `cephyrixzyth/oneirodex` until published; API token `gt_` prefix. Git history is not rewritten |
| P3b landed | Package `oneirodex/`; `.od-*` / `--od-*`; Compose `oneirodex-*`; Postgres `oneirodex` / pytest `oneirodextest`; origin `oneirodex.git`; npm `@oneirodex/api-client` |
| Danger zone | `RESET ONEIRODEX` only |
| Env / CSS | `ONEIRODEX_*` only. CSS `--od-*` canonical. No `OD_*` env aliases. `GT_*` is not read |

## Product locks

| Default | Value |
|---|---|
| Social | Native chat/presence; optional LiveKit; BYO Stoat/Matrix link |
| Discord | **Never** — excised; no webhooks |
| Windows code signing | **Never** — unsigned desktop builds only; no cert purchase |
| Auth / OIDC | **Opt-in** — off by default |
| Dangerous apply | AI auto-apply + hardlink apply stay **off** |
| Scrape | No romhacking.net (or similar) scrape |
| Acquire | Native Torznab/Newznab registry (add one / bulk) + optional admin preset pack + BYO Prowlarr/Jackett/debrid hubs; no DRM store download queues; no magnet scrapers that bypass Torznab |
| DRM stores | Ownership register-only; live sync for Steam / GOG / Epic / Amazon; no download queues |
| Support | In-app Report → GitHub Issues + admin inbox |
| LLM | On-demand agent skills; no paid keys in Flask |
| Auto-merge | Never |

## Engineering locks

| Default | Value |
|---|---|
| Docs | Docs-sync on every code change; live README screenshots on every commit/ship pass that touched UI |
| Commit | Only when the user says commit / ship / push |
| Push | **Always** after ship/commit (`ship-ready` pushes to origin); PR only when asked |
| Tests | Smallest relevant pytest/vitest slice — never claim "all green" after a partial run |
| Admin UI | Hybrid React shell + Jinja forms OK until migrated |
| Branch | Stay on the current feature branch unless asked |
| Secrets | Never commit `.env` / tokens; never stage `docs/_private/` |
| Force-push | Never to `main`; no `--no-verify` unless the user demands it |
| Commit author | Set via `git -c` flags only, never `git config` — `YOUR_USER` / `YOUR_USER@users.noreply.github.com` |

## External-facing scrub (always)

Before committing or writing docs/UI copy:

1. **Never** commit `docs/_private/` or peer competitive catalogs to public remotes.
2. **Never** introduce Class A / warez-adjacent brand names in code, docs, Help, README, CHANGELOG, or CI artifacts.
3. **Never** add "steal from Product X" / peer teardown matrices in tracked files — use Oneirodex capability language for non-goals.
4. **Allowed (Class D):** real integrations — Playnite import, ES-DE/Pegasus export, Prowlarr/Jackett/qBit, LiveKit, OIDC/Authentik, store ownership register-only.

Policy: [scrub-shipped-bundles.md](../runbooks/scrub-shipped-bundles.md) (SCRUB-7). Private vault: `docs/_private/` (gitignored).

## Deploy assumptions

| Default | Value |
|---|---|
| Primary ops | Unraid + Docker Compose |
| DB | Postgres (`db` service or local Docker) |
| App port | 5006 |
| Support repo | `cephyrixzyth/oneirodex` (`SUPPORT_GITHUB_REPO`) |

## Environment discovery

Discover the active checkout, isolated test database and available ports on each host.
Local workstation and NAS checkouts are separate; edits do not automatically deploy.
Keep machine-specific paths, hardware inventories and credentials in local operator
notes outside tracked documentation. Use explicit staging configuration, read-only
game mounts and separate database/library volumes. Confirm image identity, capacity,
backup restoration and a rollback target before any release.

## Reply style

- Lead with the answer or status, not a restatement of the task.
- Prefer tables and bullets; at most 2 clarifying questions.
- End code tasks with a one-line **Docs touched:** list.
