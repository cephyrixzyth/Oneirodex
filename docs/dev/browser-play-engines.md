# Browser play engines — research & direction (2026-08-28)

> **Doc status:** Active

**Decision (operator):** dual engines + modernize WebRetro + optional webЯcade sidecar.

| Choice | Meaning |
|---|---|
| **A** | Keep libretro path; modernize launch via **Nostalgist.js** and/or **koin.js**; add **EmulatorJS** as a second browser engine; admin default + member preference |
| **C** | Spike **webЯcade** as optional Docker sidecar / feed export (not the default shell) |
| **Also** | Modernize the current WebRetro packaging (newer RA/emscripten builds, workerized path when ready) |

Product locks still apply: self-hosted, ROMs stay on the NAS, BIOS upload-only, honest Browser / Companion / Catalog badges. No SaaS that requires uploading household dumps to a third party.

---

## Landscape (reviewed)

| Source | What it is | Self-host / embed | Fit for Oneirodex |
|---|---|---|---|
| **WebRetro** (current) | BinBashBanana packaging of RetroArch Emscripten + cores | Already vendored under `oneirodex/static/vendor/webretro/` | **Keep as engine A baseline**; modernize, do not throw away BIOS/saves/rooms work |
| **RetroArch Web** (official) | Upstream Emscripten / workerized WASMFS work | Build/host yourself; same core family | **Upstream for core upgrades**, not a second UX |
| **Nostalgist.js** | MIT JS API over RetroArch WASM (`launch({ core, rom, bios })`) | npm; resolve cores/ROMs/BIOS to our URLs | **Best modernize path** for the libretro engine — programmatic launch, saveState/loadState hooks |
| **koin.js** | React `GamePlayer` on Nostalgist (+ touch, RA hooks, cloud-save callbacks) | npm; SharedArrayBuffer headers | **Best SPA chrome** for member-app if we want a React player shell on top of Nostalgist |
| **EmulatorJS** | Mature browser frontend (GPL-3); used by RomM, JoeTemulator, Retbro | Self-host / CDN cores | **Engine B** — real second stack (different UI/core packaging, strong touch/Xbox Edge story) |
| **webЯcade** | Feed-driven full frontend (Apache-2.0); active 0.2.x in 2026; Docker image | Private Docker; feed JSON | **Sidecar C** — generate a feed from library leaves or deep-link; do not replace our shell |
| **Afterplay.io** | Hosted “Steam of retro”; cloud sync; storefront | **Not self-hosted** — ROMs go to their cloud | **Out** for in-app play (violates household/NAS lock) |
| **JoeTemulator** | Next.js library UI over EmulatorJS | Peer app, not an embed API | **Out as product**; learn from EmulatorJS only |
| **Retbro** | EmulatorJS demo / ROM-list streamer | Peer app | **Out as product**; same as JoeTemulator |

RomM is a peer *library manager* that plays via EmulatorJS — useful competitive reference, not an engine to vendor.

---

## Target architecture

```
browse / details Play
        │
        ▼
  play_url / play matrix  (honesty: browser | companion | catalog)
        │
        ▼
  browser_player resolver
   · admin default: webretro | emulatorjs
   · member override when admin allows
   · webrcade: optional "Open in webЯcade" when sidecar enabled
        │
        ├─► Engine A: libretro (WebRetro shell → Nostalgist/koin launch)
        ├─► Engine B: EmulatorJS shell (same ROM/BIOS URLs, own UI)
        └─► Sidecar C: webЯcade feed item / Docker app (separate origin)
```

### Settings

| Setting | Scope | Values |
|---|---|---|
| `browser_player_default` | Admin (GlobalSettings) | `webretro` · `emulatorjs` — the second is accepted only when an EmulatorJS release is in the data bind ([runbook](../runbooks/emulatorjs.md), **landed 2026-09-17**) |
| `browser_player_allow_member_choice` | Admin | bool (stored; no member UI yet — two engines exist now, the preference surface is the next slice) |
| `nostalgist_nes_pilot` | Admin | bool — **landed**, default **off**. NES `play_url` → `/static/vendor/nostalgist/play.html` |
| `browser_player_preference` | Member prefs | planned: `webretro` · `emulatorjs` · `default` |
| `webrcade_sidecar_url` | Admin | empty = off; else base URL of private webЯcade |
| `webrcade_feed_export` | Admin | bool — expose generated feed for that instance |

Honesty badges stay per-platform × **capability**, not per-engine marketing. If only one engine can run a system, Play uses that engine; if neither can, Companion/Catalog as today.

### Modernize WebRetro (engine A)

1. Keep serving ROM/BIOS/saves from Oneirodex (no CDN ROMs).
2. Introduce Nostalgist (then optionally koin) as the launch layer; WebRetro HTML becomes a thin host or is replaced by a React play route.
3. Pull newer libretro/emscripten cores when workerized/WASMFS builds are stable enough for SharedArrayBuffer + our CSP.
4. Preserve play rooms, Picture modes, cheat bridge, cloud-save bridge contracts.

### EmulatorJS (engine B)

1. Vendor or release-pin EmulatorJS + cores (license pass: GPL-3 + core licences — same class of problem as WebRetro).
2. Map `LibraryPlatform` → EmulatorJS system/core ids (parallel to `webretro_cores`).
3. Wire save/load and BIOS paths through the same admin BIOS tree where filenames match.
4. Per-platform matrix row: Browser (WebRetro) / Browser (EmulatorJS) / either.

### webЯcade sidecar (C)

1. Optional Compose profile or external URL.
2. Export a feed JSON for selected libraries (paths must be reachable by the sidecar — usually a shared volume or signed URLs).
3. Member action: **Open in webЯcade** when configured — never required for Play.
4. Feed Editor (`play.webrcade.com/app/editor/`) is an authoring tool for operators, not something we embed as the library UI.

---

## Explicit non-goals

- Hosting household ROMs on Afterplay or any third-party cloud.
- Replacing Oneirodex browse/library with JoeTemulator / Retbro / webЯcade frontends.
- Fake Browser badges for engines we have not wired and tested.

---

## Implementation waves (suggested)

| Wave | Deliverable |
|---|---|
| **BP-0** | **Landed 2026-08-28.** This note + `GET`/`PUT /api/browser-player-settings` + `browser_player` / `browser_players_available` on every play payload. Default and available list are `webretro` only — EmulatorJS is a recognized name but rejected as default until that shell ships. |
| **BP-1** | **Landed 2026-08-28 (scaffold).** Vendored `nostalgist@0.21.1` + `play.html`. Flag `nostalgist_nes_pilot` (default **off**) under `settings.browser_player` swaps NES `play_url` to `/static/vendor/nostalgist/play.html` using WebRetro `nestopia` WASM + `/api/downloadrom`. Save-bridge / rooms / EmulatorJS still WebRetro-only. |
| **BP-2** | EmulatorJS shell for the same pilot; admin default + member choice |
| **BP-3** | Expand matrix; koin.js optional React chrome |
| **BP-4** | webЯcade feed export + sidecar runbook |

---

## References

- Current launch: `oneirodex/utils/play_url.py`, `oneirodex/static/vendor/webretro/`
- Matrix: [docs/user/browser-play.md](../user/browser-play.md)
- Cores: [docs/runbooks/webretro-cores.md](../runbooks/webretro-cores.md)
- Nostalgist: https://nostalgist.js.org/
- koin.js: https://koin.js.org/
- EmulatorJS: https://emulatorjs.org/
- webЯcade: https://docs.webrcade.com/ · Docker: https://docs.webrcade.com/advanced/docker/
- RetroArch web: https://docs.libretro.com/guides/web-player/
