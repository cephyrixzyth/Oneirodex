# Oneirodex documentation

**Product version:** 1.1.6 — see root [CHANGELOG.md](../CHANGELOG.md) and [VERSION](../VERSION).

Hub for product, ops, and developer docs. Public name **Oneirodex**. Runtime env is `ONEIRODEX_*` only ([ADR 0003](adr/0003-product-name-oneirodex.md)). Package `oneirodex/`, Compose defaults `oneirodex-*`, preferred Hub image `cephyrixzyth/oneirodex` once published.

Root [README.md](../README.md) includes badges, feature tour, screenshots (`docs/assets/readme/`), quick start, and troubleshooting.

## Start here

| Audience | Go to |
|---|---|
| End users | [user/getting-started.md](user/getting-started.md) · [faq.md](user/faq.md) · [troubleshooting.md](user/troubleshooting.md) · [browser-play.md](user/browser-play.md) · [desktop-companion.md](user/desktop-companion.md) · [controllers-and-vr.md](user/controllers-and-vr.md) · [translation-patches.md](user/translation-patches.md) · [free-games.md](user/free-games.md) · [social-and-voice.md](user/social-and-voice.md) · [library-and-systems.md](user/library-and-systems.md) · [preferences-themes.md](user/preferences-themes.md) · [downloads.md](user/downloads.md) |
| Operators / native install | [runbooks/install-native.md](runbooks/install-native.md) — Linux · macOS · Windows installers, service units, upgrade; standalone preview with a bundled PostgreSQL ([ADR 0011](adr/0011-standalone-bundled-postgres.md)) |
| Operators / standalone to server | [runbooks/standalone-move.md](runbooks/standalone-move.md) — move a standalone install onto a Docker/Unraid server: export, import into an empty database, verified row for row, saves re-encrypted |
| Operators / scan locations | [runbooks/remote-scan-locations.md](runbooks/remote-scan-locations.md) — `ONEIRODEX_LIBRARY_ROOTS`: NAS shares and extra disks, not just the server's own disk |
| Operators / single container, Unraid Community Apps, Docker Hub | [runbooks/unraid-community-apps.md](runbooks/unraid-community-apps.md) — one image with an embedded database, the CA template, release workflow, sidecar boundaries and submission checklist; [challenge-solver-unraid.md](runbooks/challenge-solver-unraid.md) — private TRAWL sidecar setup |
| Docker Hub listing | [dockerhub-overview.md](dockerhub-overview.md) — release-stamped public overview synchronized after image publication |
| Operators / Unraid | [runbooks/unraid-deploy.md](runbooks/unraid-deploy.md) · [NAS-DEPLOY.md](../NAS-DEPLOY.md) (portable checkout examples) |
| Operators / Docker Compose | [runbooks/docker-compose-deploy.md](runbooks/docker-compose-deploy.md) — optional `--profile livekit` · `--profile clamav` · GPU art on a workstation: [artwork-gpu-workstation.md](runbooks/artwork-gpu-workstation.md) |
| Operators / observability (optional) | [runbooks/observability-profile.md](runbooks/observability-profile.md) — Prometheus stub; Admin Ops is default |
| Operators / LiveKit voice | [runbooks/livekit-unraid.md](runbooks/livekit-unraid.md) |
| Households / VR runtime | [runbooks/vr-byo-runtime.md](runbooks/vr-byo-runtime.md) — OpenXR runtime · OpenVR adapter · streamers · the wired USB-NCM link (0.7 ms / ~756 Mbps on a Quest 2) · tweaks as documentation, never distributed |
| Operators / achievements | [runbooks/retroachievements.md](runbooks/retroachievements.md) — match ROMs to community achievement sets (opt-in key); nothing played in the browser unlocks |
| Maintainers / theme art | [dev/theme-art-direction.md](dev/theme-art-direction.md) — what a theme is beyond a hue: room art, the accent sentinel, and how a generated backdrop lands |
| Operators / WebRetro cores | [runbooks/webretro-cores.md](runbooks/webretro-cores.md) · [admin/webretro-core-clauses.md](admin/webretro-core-clauses.md) (non-commercial clauses — not counsel) |
| Operators / emulator BIOS | [runbooks/emulator-bios.md](runbooks/emulator-bios.md) — operator-supplied firmware; Admin scan/install, filenames only |
| Operators / ROM reference sets | [runbooks/reference-sets.md](runbooks/reference-sets.md) |
| Operators / login rate limit (proxy) | [runbooks/login-rate-limit-proxy.md](runbooks/login-rate-limit-proxy.md) |
| Operators / break-glass | [runbooks/container-wont-start.md](runbooks/container-wont-start.md) |
| Operators / security posture | [Docker Compose deploy](runbooks/docker-compose-deploy.md) — Secure cookie defaults and chat storage limits · [OIDC / SSO](runbooks/oidc-sso.md) · Public ops: [container-wont-start.md](runbooks/container-wont-start.md) · [themes-reset.md](admin/themes-reset.md). Security audit notes are local-only. |
| Operators / release scrub (SCRUB-7) | [runbooks/scrub-shipped-bundles.md](runbooks/scrub-shipped-bundles.md) |
| Maintainers / disk hygiene | [runbooks/workspace-disk-hygiene.md](runbooks/workspace-disk-hygiene.md) — safe cache deletes vs WebRetro / `.git` |
| Maintainers / desktop installers | [runbooks/local-installers.md](runbooks/local-installers.md) — build Windows · macOS · Linux bundles without GitHub Actions; a `.dmg` still needs a Mac |
| Admins | [admin/libraries-and-scans.md](admin/libraries-and-scans.md) · [members-and-invites.md](admin/members-and-invites.md) (invites without email · local accounts) · [privacy-data-handling.md](admin/privacy-data-handling.md) (what the host stores · child ACL · optional outbound) · [webretro-core-clauses.md](admin/webretro-core-clauses.md) (snes9x / genesis_plus_gx quotes — **not counsel**) · [navigation.md](admin/navigation.md) (rail · top bar · Settings and Integrations sub-sections) · [settings-modules.md](admin/settings-modules.md) · [discover-sections.md](admin/discover-sections.md) (storefront shelves · layouts · timed events) · [theme-fonts-and-images.md](admin/theme-fonts-and-images.md) (fonts · batch artwork) · [ops-summary.md](admin/ops-summary.md) · [support-inbox.md](admin/support-inbox.md) · [troubleshooting.md](admin/troubleshooting.md) · [themes-reset.md](admin/themes-reset.md) |
| Maintainers / architecture | [dev/architecture.md](dev/architecture.md) · [adr/README.md](adr/README.md) — nine accepted decisions, two superseded, and one proposal · [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Maintainers / database evaluation | [adr/0012-evaluate-mariadb-before-engine-change.md](adr/0012-evaluate-mariadb-before-engine-change.md) — cost and compatibility gates; proposal only |
| CI gates (maintainers) | [dev/ci-gates.md](dev/ci-gates.md) — current marker selection, explicit exclusions and coverage gate. Replaces `ci-wishlist.md` |
| Support triage (maintainers) | [dev/ui-debt-log.md](dev/ui-debt-log.md) · [dev/api-envelope-keeps.md](dev/api-envelope-keeps.md) |
| Test harness (maintainers) | [dev/test-harness-2026-09-10.md](dev/test-harness-2026-09-10.md) — per-test SAVEPOINT isolation · savepoint-restart listener · `database` / `slow` markers. Older harness notes and the 2026-09-16 failure list are in [dev/archive/](dev/archive/README.md) |
| Admin Jinja → React (maintainers) | [dev/admin-jinja-inventory.md](dev/admin-jinja-inventory.md) — which admin pages still render server-side, their handlers and APIs, and the port order (H-D.5) |
| Writing an API route (maintainers) | [dev/pydantic-adoption.md](dev/pydantic-adoption.md) — `@validate_body` request models · which routes are migrated · adoption backlog |
| Maintainers / browser engines | [dev/browser-play-engines.md](dev/browser-play-engines.md) — WebRetro · Nostalgist/koin · EmulatorJS · webЯcade sidecar · [runbooks/emulatorjs.md](runbooks/emulatorjs.md) (bundled engine B) |
| OIDC / Authentik SSO | [runbooks/oidc-sso.md](runbooks/oidc-sso.md), [runbooks/oidc-authentik-unraid.md](runbooks/oidc-authentik-unraid.md) |
| API | [openapi/openapi.json](openapi/openapi.json) |
| How-to videos | [media/video/howto/](media/video/howto/README.md) — 20 narrated clips (AI voice, captions, WebVTT + transcripts), one worked example per feature, members + admins |
| README media | [assets/readme/](assets/readme/) · capture recipe [CAPTURE.md](assets/readme/CAPTURE.md) |

## Documentation boundaries and status

User/admin guides describe implemented behavior; proposals and dated reports are not release verification. Local staging evidence is separate from production acceptance. Household PostgreSQL remains the supported server configuration; a serverless desktop migration is still a design/proof phase.

Operator host details, credentials, research exports, human responses and internal execution records belong in ignored local storage. Public docs use example addresses and paths. Never paste full database connection URLs into logs or support reports. Historical Git commits are not scrubbed by a working-tree documentation update.

## Layout

```
docs/
  README.md                 ← you are here
  adr/                      ← architecture decision records
  user/                     ← end-user guides + FAQ
  admin/                    ← admin guides
  runbooks/                 ← deploy & incident procedures
  openapi/                  ← HTTP contract
  assets/readme/            ← root README icons & screenshots
  dev/                      ← engineering notes
  */archive/                ← Archive-status docs (see below)
```

## Doc status

Every doc carries `> **Doc status:** Active | Reference | Archive` under its title.

| Status | Meaning | Who reads it |
|---|---|---|
| **Active** | Maintained; matches current behavior | Agents and users, by default |
| **Reference** | Stable background (design notes, baselines) | When the topic comes up |
| **Archive** | Kept for provenance; superseded or finished | Nobody, unless directed. Agents skip `archive/` folders and the links below |

Archive docs live in the area's `archive/` folder, each with a `README.md` listing what is there and why. To archive a doc: `git mv` it into `archive/`, set its status line, add a row to `archive/README.md`, and fix inbound links.

Archives: [dev/archive](dev/archive/README.md) · [superpowers/archive](superpowers/archive/README.md)

Docker and cloud demo operations: [Docker Compose deploy](runbooks/docker-compose-deploy.md)

## Naming

| Surface | Value |
|---|---|
| Product (shipped today) | Oneirodex (public string) |
| Ops / code identifiers | Compose defaults `oneirodex-*`; npm `@oneirodex/api-client`; env `ONEIRODEX_*` only — [ADR 0003](adr/0003-product-name-oneirodex.md) |
| Version | 1.1.6 |
| GitHub | cephyrixzyth/oneirodex |
| Containers | oneirodex-app (single-container or app role) · oneirodex-db (optional separate Postgres) |
| Optional voice | oneirodex-livekit (`--profile livekit`) |
| Python package | oneirodex |
| Default accent | `#2fd67b` (Style B+C glass) |
