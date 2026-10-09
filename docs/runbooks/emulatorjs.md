# EmulatorJS — browser play engine B

> **Doc status:** Active

**Applies to:** 1.0.0-beta and later · **Status:** bundled by default; selectable at Admin → Emulators

Oneirodex bundles WebRetro (libretro cores in WASM) and a pinned EmulatorJS
release in the image. EmulatorJS is a second, self-contained shell — its own
UI and core packaging — and can be disabled in Admin → Emulators. It is GPL-3
([EmulatorJS/EmulatorJS](https://github.com/EmulatorJS/EmulatorJS));
you are responsible for the licences of the libretro cores it bundles, same
as for WebRetro's.

Nothing about the household leaves the box: the play shell hands EmulatorJS
the same `/api/downloadrom/<guid>` URL WebRetro uses, and the loader, UI and
cores are served from this origin. There is no CDN fallback in the shell.

## Availability

EmulatorJS is included in the container image from the pinned release. Keep it
enabled to offer both browser engines, or turn **Enable EmulatorJS** off in
Admin → Emulators. WebRetro remains the default unless an admin changes it.
The manual fetch script remains available for local development; production
images obtain the pinned archive during the Docker build.

## What it changes

- The app detects the install by `<data dir>/loader.js`. An admin can disable
  the bundled engine without removing files from the image.
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

Turn **Enable EmulatorJS** off in Admin → Emulators. If EmulatorJS was the
default engine, Oneirodex switches the server default to WebRetro and member
play uses WebRetro.
