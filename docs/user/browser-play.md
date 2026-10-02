# Browser & companion play — platform matrix

> **Doc status:** Active

Oneirodex play modes for systems **below PS5 / Xbox Series**. Those two stay **catalog + download only**.

**Browser engines (direction):** Play today uses **WebRetro** (RetroArch WASM). Browse payloads include `browser_player` / `browser_players_available` (always `webretro` until a second engine is wired). Admin stub: `GET`/`PUT /api/browser-player-settings`. Optional **NES Nostalgist pilot** (`nostalgist_nes_pilot`, default off) swaps only NES Play links to a vendored Nostalgist host that still loads household cores/ROMs from this box — see [browser-play-engines.md](../dev/browser-play-engines.md). That host has **no save/load/rewind bar yet**; leave the flag off for cabinet chrome. Planned next: EmulatorJS as engine B, optional **webЯcade** sidecar. SaaS hosts that require uploading household ROMs (e.g. Afterplay) are out of scope.

| Platform | Browser (WebRetro) | Companion | Notes |
|---|---|---|---|
| NES · SNES · N64 | Yes | Yes | N64: try alternate core if a title fails |
| GB · GBC · GBA · NDS · VB | Yes | Yes | |
| PS1 | Yes | Yes | Needs SCPH BIOS files |
| Genesis / MS / CD / 32X / GG / SG-1000 | Yes | Yes | CD needs region BIOS. SG-1000 uses the same `genesis_plus_gx` WASM as Genesis. |
| Saturn | Yes | Yes | Needs `saturn_bios.bin` |
| Atari · Lynx · Jaguar · WS · NGP / NGPC · Coleco · Vectrex · 3DO · Neo Geo CD · INTV · CHAF · O2 | Yes | Yes | BIOS where listed in Admin → emulator BIOS. NGPC uses the same `mednafen_ngp` WASM as NGP. |
| PC Engine · Commodore | Companion now (browser when WASM vendored) | Yes (RetroArch cores) | Drop cores via [webretro-cores.md](../runbooks/webretro-cores.md) (`fetch-webretro-cores --from-dir`); auto-unlocks from disk |
| PC DOS | When flag + WASM | Preferred | Companion default; `ENABLE_PCDOS_BROWSER` (default on) still needs vendored `dosbox_pure` WASM — see runbook |
| GameCube · Wii | No (WASM) | Preferred | Dolphin mapped; companion_hint on browse; no browser Play |
| Dreamcast · 3DS · PS Vita · PS2 | No | Preferred | flycast / citra / vita3k / pcsx2 companion cores + hints |
| Xbox · 360 · One · PS3 · PS4 | Catalog | Optional BYO | `play_mode=companion` + hints; no fake Play |
| Wii U · Switch | Catalog | — | Enums shipped; no Dolphin / no browser Play |
| Pokémon Mini · CD-i · Sega Pico · Jaguar CD · Game & Watch | No | Preferred | Companion; Jaguar CD never shares cart `virtualjaguar`. Game & Watch `gw` is not in WebRetro WASM. |
| Amiga · Amiga CD32 | No | Preferred | PUAE companion; CD32 is distinct from Amiga |
| MSX · ZX Spectrum · Amstrad CPC · Atari ST · Apple II · Atari 8-bit · X68000 · PC-98 · BBC Micro | No | Preferred | `bluemsx` / Fuse / cap32 / Hatari / AppleWin BYO / atari800 / PX68K / np2kai / BeebEm BYO. GX4000 stays the Amstrad *console* (Retro family). No WebRetro WASM. |
| PS5 · Xbox Series | Catalog only | — | `play_mode=catalog` |

Admin: upload BIOS via Admin → Emulators, **Scan collection** on a folder of dumps you already own, or on household Unraid optionally mount a private appdata BIOS folder — see [BIOS / firmware](#bios--firmware-filenames-only). Browse API returns `bios` + `n64_note` on playable titles. Systems hub badges show **Browser** / **Companion** / **Catalog** per platform. **More → Ways to Play** and Game Catalog `play_mode=` filter the catalog by that same honesty. Operator core drops: [webretro-cores.md](../runbooks/webretro-cores.md) · health: `GET /api/emulator/health` (`deferred_cores`) · JS allowlist: `GET /api/emulator/installed-cores.js`.

## BIOS / firmware (filenames only)

Oneirodex **does not ship** copyrighted BIOS binaries in git, CI artifacts, or the public Docker image. Operators supply legally obtained firmware they already own.

| How | When | Notes |
|---|---|---|
| **Admin upload** (public / default) | Always available | `POST /api/emulator-bios` → container `…/static/library/bios/` (WebRetro `biosCdn`) |
| **Scan a collection** | Admin → Emulators | Point at a folder of dumps you already own (subfolders included). Scan, pick versions when names collide, install matching firmware. Missing names open as copyable markdown. Same path can be `BIOS_IMPORT_SOURCE` for boot import. |
| **Local private mount** (household Unraid) | Optional | Bind host `/mnt/user/appdata/oneirodex/bios` → `/app/oneirodex/static/library/bios` — [unraid-deploy.md](../runbooks/unraid-deploy.md#local-private-bios-mount-vs-public-upload). Not the games share. |

**Expected filenames** (checklist — no download links):

| Core / family | Filenames |
|---|---|
| PS1 (`mednafen_psx_hw`) | `scph5500.bin` · `scph5501.bin` · `scph5502.bin` |
| Sega CD (`genesis_plus_gx`) | `bios_CD_U.bin` · `bios_CD_E.bin` · `bios_CD_J.bin` |
| Saturn (`yabause`) | `saturn_bios.bin` |
| 3DO (`opera`) | `panafz1.bin` · `panafz10.bin` |
| Neo Geo CD (`neocd`) | `neocd_f.rom` · `neocd_sf.rom` · `neocd_st.rom` · `neocd_z.rom` · `front-sp1.bin` |

Admin → emulator BIOS shows which required names are present. Missing BIOS surfaces on browse play hints.

## Play shell (WebRetro room)

**Scanlines (2026-08-06) and picture modes (2026-08-26).** Each room carries a scanline treatment matched
to the hardware it evokes: strongest on a 1980s wood-den CRT, present on an arcade
monitor, faint on a late-90s carpet den, and **absent on handhelds** by default — an LCD panel
never had scanlines. The **Picture** control on the play bar cycles three treatments: **CRT** (room scanlines + a light tube vignette), **Sharp** (nearest-neighbour, scanlines off), and **Soft** (RetroArch `video_smooth`). This is CSS plus one RetroArch flag, not a shader pack: no `.slangp` presets are vendored, so there is no GPU shader cost and nothing extra to install. Handheld and desk rooms default to Sharp.

Browser play opens `webretro.html` with a per-system **artistic room** — multi-layer wallpaper, floor plane, ambient lamp, bezel material sheen, bar typography hierarchy (brand eyebrow + system label), and light motion (wall drift · lamp breathe · bezel specular) — not just an accent color. Pass `platform=` (or rely on `core=` mapping) so the skin applies immediately; the bar shows the system name as the hero label.

- **← Game Catalog** and **Power** always leave to `/library`. They clear the emulator’s leave-site guard first (WebRetro installs `onbeforeunload` after the ROM starts; Cancel on that dialog looked like the buttons did nothing). They never use `history.back()` — the iframe can add its own history entries and strand you on the play shell.
- **Pause · Reset · Mute · volume · Save · Load · Rewind · FF · Picture** sit on the play bar and talk to the WebRetro iframe over the save-bridge (`od-pause` / `od-reset` / `od-audio` / `od-save-state` / `od-load-state` / `od-cabinet-key` / `od-picture`). Mute and volume write RetroArch `audio_mute` / `audio_volume` and reload config. **Save / Load** click the iframe's own state commands (also **F2** / **F3** with the game focused). **Rewind** is a hold (Right Shift, or hold the bar button). **FF** toggles with **F5** (hold **Tab** in the game to burst). **Picture** cycles CRT (room scanlines + tube vignette) · Sharp (nearest-neighbour, scanlines off) · Soft (RetroArch `video_smooth`). This is CSS plus one RetroArch flag — **no shader presets are vendored**, and run-ahead is not enabled (single-thread WASM cannot afford it). Rewind stays **off** on heavy cores (N64, PS1, Saturn, Dreamcast, PSP). An in-game overlay repeats Pause/Reset/Mute/Save/Load/Rewind/FF/Power; it stays visible on touch, and on a pointer it fades in when you move over the play stage. The overlay gradient itself is click-through so WebRetro’s **Start** and core list stay reachable — only the overlay buttons take the pointer. Press **?** for the shortcut list.
- Distinct rooms include **1980s wood den**, **1990s teen bedroom**, **late-90s carpet den**, **2000s media centre**, **arcade floor**, and **computer desk** — the same setting language as the UI theme picker. Bezel chrome stays per-platform; the room is the decade you sit in. Distinguishable at a glance without reading docs.
- The emulator screen is **aspect-locked to the core's native shape** (SNES/NES/Genesis ~4:3, GBA 3:2, GB/GBC ~10:9, NDS portrait dual-screen, PSP/Vita ~16:9, etc.) instead of stretching to fill the bezel, so you no longer get big empty black bars around the picture.
- Motion respects `prefers-reduced-motion`.
- After deploy, hard-refresh the play tab (Ctrl+F5) so cached `play-skins.css` / `.js` drop. Smoke: `node oneirodex/static/vendor/webretro/play-skins.assert.mjs`.

## Two engines

WebRetro is the player that ships with Oneirodex. Your admin can add **EmulatorJS** as a second engine (a different shell with its own menu, save-state screen and touch controls) and make it the default; when they do, Play on the systems it supports opens in that shell and everything else stays on WebRetro. Either way your ROMs never leave the server. If a game opens in a plain page saying EmulatorJS is not installed, tell your admin — that shell needs a one-time install on the server.

## Audio/video tuning + WASM limits (SNES and friends)

Browser Play runs RetroArch compiled to WebAssembly inside the tab — there's no native audio thread or GPU passthrough, so a few defaults are tuned to reduce common WASM artifacts:

- **Audio is clocked to the emulated system, not the browser's refresh.** `audio_sync` and `audio_rate_control` are on, with a small `audio_rate_control_delta` (0.005) that nudges the resampler by fractions of a percent, and `audio_max_timing_skew` at **`0.15`** (wider than desktop RetroArch's 0.05). WASM on the browser main thread stalls longer than a native frame loop; the extra headroom absorbs GC/layout hiccups so the buffer does not underrun. A larger buffer (`audio_latency = 128`, raised from 96 on 2026-09-17) does the same for brief stalls — 96 left about two buffers at 48 kHz, so one long frame was audible as crackle and rate control then chased the gap as speed drift. Do not "correct" skew back to 0.05 without measuring on a real browser first.
  - *If audio runs fast and glitchy on a 120/144/165Hz monitor:* that is the refresh-rate clock below, not this skew. Hard-refresh the play tab so the cached player reloads.
- **`video_vsync`** is explicit so WASM frame delivery paces to the browser's `requestAnimationFrame` instead of free-running.
- **The player now measures your display's refresh rate.** RetroArch assumes a 60Hz screen unless told otherwise, and with vsync on it paces frames to the browser. On a 120Hz, 144Hz or 165Hz monitor that meant the core advanced **two to nearly three times too fast**, with audio rate-control permanently chasing a gap it could not close — fast, pitch-shifted, crackling sound. The player samples the real refresh rate over ~32 frames on load and writes it to `video_refresh_rate`.
  - *If you played before this changed:* speed and audio were wrong on any monitor above 60Hz, and the earlier audio tuning could not fix it — resampling headroom cannot correct a clock that is a whole multiple out. Hard-refresh the play tab so the cached player reloads.
  - **Two lines tell you what the player actually measured.** Open the game, then the browser console (or the in-page console with **?**): `Display refresh measured: NN.NNHz` and `Audio device: NNNNNHz`. If the first reads `waiting for a visible tab`, the player booted while the tab was hidden and will sample as soon as it is shown — `requestAnimationFrame` does not tick in a background tab, which is why an early version could log nothing at all. Both values are also on the page as `data-od-refresh-hz` / `data-od-audio-hz` on `<html>`.
  - The player's audio runs at your device's own sample rate (the web audio driver opens the context at 44.1 or 48 kHz as the device is set and RetroArch resamples to it), so you never need to change your interface's rate for it.
  - High-refresh monitors are the common case for gaming, so this affected most desktop players even though 60Hz laptops looked fine.

- **SNES "Reduce Slowdown (Overclock)"** — a pre-start core option (gear icon before you press Start) enables `snes9x_overclock_cycles = balanced`, which fixes the slowdown-driven audio pitch/crackle some demanding SNES titles (Star Fox, Kirby's Dream Land 3, some Konami games) hit under WASM CPU pressure.
- **Browser autoplay policy**: audio stays muted/suspended until you interact with the page (the **Start** click/keypress inside the emulator). If you don't hear anything, click into the play screen once before pressing Start.

Residual limits that tuning can't fully fix in-browser: WASM is single-threaded on the main thread, so heavy cores (N64, PS1 HW renderer, Saturn) can still stutter under load on lower-end hardware, and audio scheduling jitter can't reach native-app smoothness. If a title is still choppy after the overclock option, prefer the **desktop companion** (native RetroArch) for that system.

## Compressed ROMs (extract-on-play)

Browser Play streams via `GET /api/downloadrom/<uuid>` (ASGI). Server extracts a playable member into `static/library/rom_cache/<uuid>/` for:

| Format | Notes |
|---|---|
| `.zip` | Nested folders + zip-in-zip (depth ≤ 3). Multi-ROM: prefers platform extension, then larger files; `.cue` (+ sibling `.bin`) for disc sets |
| `.7z` | Requires `py7zr` |
| `.rar` | Requires `rarfile` + a host `unrar`/`bsdtar`/`7z` binary — the Docker image ships `libarchive-tools` (`bsdtar`) + `p7zip-full` (`7z`) so this works out of the box in Compose/Unraid |
| `.gz` | Single ROM wrappers only (`Adventure.nes.gz`). `.tar.gz` is **not** browser-playable (`play_blocker=unsupported_archive`) |

Failures return JSON: `{"error": "…", "code": "…", "hint": "…"}` (`error` always present). The play shell (`webretro.html`) surfaces non-2xx `/api/downloadrom/` responses in an accessible `#od-play-alert` region (`error` plus optional `hint`) instead of a silent `.catch` — including `missing_extractor` (prefer `.zip` / host tools). Browse may set `play_blocker=unsupported_archive`; GameCard / Game Details show a disabled Play control with tooltip when that blocker is present.

When `firmware_missing` is true, browse/details also return `bios_required`, `bios.message`, and `bios.hint`. Member SPA blocks Play (quiet honesty + Help / Admin → Emulators for librarians) — **never** a Download BIOS CTA. Optional accuracy files do **not** set `firmware_missing`: NES carts play without `disksys.rom`, SNES without DSP/CX4 ROMs, N64 without 64DD IPL, Genesis carts without Sega CD BIOS. Sega CD and other hard-required systems still grey Play until a matching dump is on the firmware volume. Version Download uses `POST /api/downloads/games/<uuid>` and toasts Backend `hint` on **410** `path_missing`.

### PS1 (and other disc/`.cue`) downloads are bundled as a zip

`.cue` sheets need their sibling `.bin`/`.img`/`.iso`/`.raw`/`.wav` track files to boot — a plain HTTP GET can only stream one file. `GET /api/downloadrom/<uuid>` detects this and streams a single **stored (uncompressed) `play.zip`** containing the `.cue` (with `FILE` lines rewritten to plain basenames) plus every disc-track companion sitting next to it. WebRetro's own client-side unzip (`unzipFileMulti`) splits the bundle back into files for disc cores (PS1, Saturn, Sega CD, etc.) — no server round-trip changes were needed on the WebRetro side beyond reading the real filename off the response.

Single-file discs (`.iso`, `.chd`, a lone `.bin`) stream unchanged — no zip wrapping. The play shell reads the actual filename from the response's `Content-Disposition` header (not the request URL, which is just `/api/downloadrom/<uuid>`) and uses a long fetch timeout for ROM downloads, since PS1-sized discs can take well past the old 8-second default.

## Save states (WebRetro)

Your place is kept for you. States live on the server, per member and per game, and the room never loads one without asking.

- **Resume.** A tile whose game has a state reads **Resume** instead of Play (the details page lists every state under **Saved states**, each with its own Resume). Opening the room shows a bar — *Where you left off · 5 min ago — resume?* — with **Resume** and **Start fresh**. Nothing is loaded until you choose. Battery saves (the game's own SRAM) are put back silently, as they would be on a real cartridge.
- **Leaving.** **← Game Catalog** and **Power** take a state and push it before the page goes (a few seconds at most; a slow server never keeps you on the screen). Hiding the tab does the same, throttled. That state is the one Resume offers.
- **Saves panel.** The **Saves** button on the play bar opens a panel: name a save (**Save as**), **Load** or **Delete** any state, and **Sync now** for an explicit push. Up to 10 slots per game, 2 MiB each.
- Under the hood this is `od-bridge.js` postMessage (`od-export-saves` / `od-import-saves`, the latter with `autoLoad:false` on boot). Export retries briefly so slow cores can flush `.state` / SRAM; the SRAM pick prefers `.srm`, then `.mcr`, then `.sav`. CSRF for upload comes from the `csrf_token` cookie.
- If a deferred core is still warming, status may say to open **Saves** again after **Start**.

EmulatorJS (engine B) has its own save-state screen inside its menu; this layer is WebRetro's.

## Achievements (RetroAchievements)

When your admin has connected RetroAchievements, a title whose ROM matches a community achievement set gets an **Achievements** section on its details page: how many the set has, a link to it, and — once you enter your own RetroAchievements username — which ones you have earned.

**Playing here does not unlock anything.** The browser player has no achievement runtime, hardcore or softcore, so the list is what exists to earn plus whatever you earned elsewhere (a real console, RetroArch, the desktop companion). No title claims a set it does not have: a ROM that matches nothing, or matches a set with no achievements yet, simply has no section.

Your username is a public handle, never a password or key, and it is only used to read your progress. Clear the field to remove it.

Only cartridge systems are matched — RetroAchievements hashes those by rules Oneirodex can reproduce (NES, SNES, N64, Game Boy/Color/Advance, Mega Drive, Master System, Game Gear, 32X, PC Engine, Lynx, Neo Geo Pocket, WonderSwan, Virtual Boy, SG-1000, ColecoVision, Intellivision, Vectrex, Odyssey², Channel F, Jaguar, Atari 2600/5200/7800). Disc-based systems are left unmatched rather than matched wrongly.

## Cheats (`.cht`)

Browse/details payloads include **`cheat_surface`**: `retroarch` | `pc_wand` | `none`. Only `retroarch` exposes the `.cht` library (`GET/POST/DELETE /api/games/{uuid}/cheats`); create/upload/download/delete return **403** otherwise. Create with name + code rows + dialect hint (Raw / GG-style / AR-style / GS-style — capability labels only), or upload a prebuilt `.cht`. The WebRetro play bar loads the same list for **Apply cheat**; companion stages files under `app_data/cheats/{uuid}/` before RetroArch. Quick Menu may still be required to enable codes. PC / native (`PCWIN` / `PCDOS` / `MAC` / `OTHER`) report `pc_wand` — RetroArch `.cht` tooling stays hidden there; no memory injection.

**PC cheat notes.** Rather than a trainer, PC titles get **notes**: what to change and how. Each entry records a `method` — `console` (an in-game console command), `config` (an ini/cfg edit), `save` (a save-editor field), `launch_flag` (a startup argument), or a plain `note` — plus the value and any caveat. Oneirodex never writes to a game binary and never injects into a running process, which keeps this on the right side of the anti-cheat line and matches the operator-owned patch-catalog stance (nothing scraped from trainer sites). Librarians and admins author entries; members read them. API: `GET`/`POST /api/games/<uuid>/pc_cheats` · `DELETE /api/games/<uuid>/pc_cheats/<id>`.

Companion: [desktop-companion.md](desktop-companion.md).

## Sample free ROMs (legal only)

For smoke-testing browser/companion play without commercial dumps, operators can fetch author-licensed homebrew and test ROMs via `python scripts/fetch-free-roms.py` (manifest + notes in [samples/free-roms/](../../samples/free-roms/README.md)). Binaries are gitignored; never commit pirated ROMs.
