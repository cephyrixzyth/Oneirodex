# EmulatorJS — browser play engine B

> **Doc status:** Active

**Applies to:** 1.0.0-beta and later · **Status:** shipped 2026-09-17 (BP-2), off until installed

Oneirodex ships one browser player in the image: WebRetro (libretro cores in
WASM). EmulatorJS is a second, self-contained shell — its own UI, its own core
packaging, a stronger touch and gamepad story — that an operator can add
without rebuilding the image. It is GPL-3 ([EmulatorJS/EmulatorJS](https://github.com/EmulatorJS/EmulatorJS));
you are responsible for the licences of the libretro cores it bundles, same
as for WebRetro's.

Nothing about the household leaves the box: the play shell hands EmulatorJS
the same `/api/downloadrom/<guid>` URL WebRetro uses, and the loader, UI and
cores are served from this origin. There is no CDN fallback in the shell.

## Install

1. Pick the host directory Compose binds as `EMULATORJS_HOST_PATH`
   (default `/mnt/cache/appdata/oneirodex/emulatorjs`; set it in the live
   `.env` if you want it elsewhere).
2. Fetch a release into it:

   ```bash
   EMULATORJS_DATA_DIR=/mnt/cache/appdata/oneirodex/emulatorjs ./scripts/fetch-emulatorjs.sh
   # or pin: ./scripts/fetch-emulatorjs.sh --version 4.2.3
   ```

   The script downloads the GitHub release zip, finds its `data/` root
   (`loader.js` at the top), and copies it in. Cores under `data/cores/` are
   fetched lazily by EmulatorJS's own loader from that same directory, so the
   whole release is needed there.
3. `docker compose up -d` (a recreate is enough — the bind is declared in
   `docker-compose.yml`; no image rebuild).
4. **Admin → Emulators → Browser play engine**: EmulatorJS is now selectable.
   Until step 2 happens it shows disabled with *not installed on this server*.

## What it changes

- The app detects the install by `<data dir>/loader.js`. Empty or missing
  directory = engine not offered; the admin default cannot be set to it.
- With EmulatorJS as the default, Play on a **supported** system opens
  `/static/vendor/emulatorjs/play.html`. Supported systems are the ones with a
  row in `EJS_CORE_BY_PLATFORM` (`oneirodex/utils/emulatorjs.py`): NES, SNES,
  GB/GBC, GBA, DS, Virtual Boy, N64, Mega Drive, Master System, Game Gear,
  32X, Atari 2600/5200/7800, Lynx, Jaguar, PC Engine, Neo Geo Pocket, WonderSwan,
  ColecoVision. Anything else — and any system that needs operator-uploaded
  firmware — stays on WebRetro exactly as before. Honesty badges are per
  capability, not per engine.
- The NES Nostalgist pilot still takes precedence for NES when it is on.
- Plugins inventory reports `emu.emulatorjs` as `installed` or `available`
  (it was `eval`).

## Member choice

Admin → Emulators → **Let members choose their engine** stores
`browser_player_allow_member_choice`. With it on *and* both engines installed,
every member's Preferences modal gains a **Play in browser** section
(`Server default (…)` / WebRetro / EmulatorJS). The choice is stored on
`user_preferences.browser_player_engine` (NULL = server default) and is
honoured only while the admin allows it and the engine is installed — switch
either off and Play silently returns to the default, the stored value kept
for when it comes back. A system the chosen engine cannot run still opens in
WebRetro. `browse_play_fields()` reports the *resolved* engine per member in
`browser_player`, plus `browser_player_member_choice` and
`browser_player_preference`.

## Not in this slice

- Save states, cheats and the cabinet play bar inside the EmulatorJS shell —
  it has its own menu for states; the Oneirodex play bar is WebRetro-only.
- BIOS hand-off: systems that need firmware are not in the platform map.

## Remove

Empty the bind directory (or point `EMULATORJS_HOST_PATH` at an empty one) and
recreate the container. If the admin default was EmulatorJS, the app falls back
to WebRetro on read and says so in the settings panel.
