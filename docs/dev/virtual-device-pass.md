# Virtual-device pass

> **Doc status:** Active

How Oneirodex is tested against platforms and devices we do not own, and what each result can honestly claim. Plan: four layers, cheapest first. Run from a container with headless Chromium; nothing here needs a GPU, a console, a headset or a store account.

| Layer | What | Where | Status |
|---|---|---|---|
| 1 | Every platform, no boot: play mode, core, firmware, free ROM | `scripts/vdevice/platform_table.py`, `tests/test_platform_capability_table.py` | Done |
| 2 | Real browser boot of free-ROM platforms | `scripts/fetch-free-roms.py` supplies candidate inputs | Open. A boot run needs a provisioned core, the corresponding ROM and a browser that reaches gameplay. |
| 3 | Virtual devices (stubs and emulated contexts) | `tests/test_vdevice_fake_*.py`, `scripts/vdevice/gamepad.py`, `scripts/vdevice/hover_stability.py`, `ui_sweep.py --viewports` | Done for the devices below |
| 4 | Whole-app UI sweep, admin and member | `scripts/vdevice/ui_sweep.py` | Done: ~49 routes x 6 viewports (desktop, phone, phone-landscape, tablet, TV, Quest) |

## Virtual devices

| Device | Stand-in | Covers | Check |
|---|---|---|---|
| Desktop companion | Fake client with a Bearer token | queue → heartbeat → ack/nack → lifecycle, over the real routes | `tests/test_vdevice_fake_companion.py` |
| Game server | Real loopback TCP listener | status up/down, no host or exception text leaked, blocked health URL | `tests/test_vdevice_fake_game_server.py` |
| Lighting controller | Local Hyperion JSON-RPC stub | colour then clear, bearer token, admin-only | `tests/test_vdevice_fake_ambient_lighting.py` |
| Remote play host | Sunshine/Wolf base URL | member status without the operator token, metadata hosts refused | `tests/test_vdevice_fake_remote_play.py` |
| Game controller | `navigator.getGamepads` replacement | Big Picture d-pad, stick, confirm | `scripts/vdevice/gamepad.py` |
| Phone, tablet, TV, Quest | Playwright viewports | overflow, console errors, 5xx, blank or stuck-loading pages on every route | `scripts/vdevice/ui_sweep.py --viewports …` |
| Pointer on tiles | Real mouse across the first row | the top bar stays on top (regression for the blink) | `scripts/vdevice/hover_stability.py` |

Not covered here, and why: real console emulators and Moonlight (no hardware), OpenXR (no headset; `/vr` is swept in a Quest-sized viewport only), live store accounts (CSV and mocked sync only), WASM emulator boot (Layer 2 remains open).

## Findings so far

| Found by | Finding | Status |
|---|---|---|
| Layer 4 | `GET /admin/api/ops/system` returned 503 on every install with at least one logged event (`get_log_info()['latest']` is an ORM row, not JSON). Admin → Ops lost its System panel. | Fixed, regression test `tests/test_ops_system_snapshot.py` |
| Layer 3 (fake companion) | `POST /api/client/commands` returned 500 for every install/update/uninstall queued from the web: a local `select = data.get('select')` shadowed SQLAlchemy's `select`. | Fixed, `tests/test_vdevice_fake_companion.py` |
| Layer 4 (hover) | The top bar blinked/hid while hovering tiles. `scripts/vdevice/hover_stability.py` reproduces it in a real browser (old CSS: the scroll pane flips over the bar; `/library`: the bar is covered for the whole sweep) and showed the first fix was **incomplete**: `od-era.css` (the default look) carried the same `:has(.game-card:hover)` lift as `od-shell.css`. | Fixed in both files; sweep reports STABLE on `/discover` and `/library` |
| Layer 4 (phone) | `/admin/arr` (+155px) and `/admin/reference_sets` (+61px) scrolled sideways: the legacy admin content shrank to fit-content instead of filling its grid track. | Fixed in `od-shell.css`; applies after *Reset Themes* copies the theme |

Run the sweep with `python scripts/serve_capture.py` in one shell and `python scripts/vdevice/ui_sweep.py` in another (`--viewports desktop`, `--no-screenshots` available).

## What a result can claim

| State | Meaning |
|---|---|
| `boot-eligible` | The browser advertises a core, no required firmware is missing, and the free-ROM manifest lists a candidate for a boot test. |
| `core-smoke` | The browser advertises a core and the sample manifest lists no ROM for this platform. A core-load check applies. |
| `bios-blocked` | Browser play, but the core needs firmware Oneirodex never ships. The pass asserts the blocker message, not a boot. |
| `companion-only` | Played by a desktop emulator (Dolphin, PCSX2 …). Not testable in a container; the pass tests only the server side of the companion protocol. |
| `catalog-only` | Never offered play; asserted to stay that way. |

## Platforms

The table uses the stock WebRetro provisioning list, default platform profiles and an empty firmware store. Each platform is classified twice through the same browse helper used for games. The first entry has an attached temporary binary file. The second has no source path. The synthetic file exercises launch eligibility. Actual ROM compatibility and gameplay require a separate boot run. If a previously attached file disappears from disk, the ROM download endpoint checks it again when the member opens it.

Regenerate with `python scripts/vdevice/platform_table.py --write`.

<!-- platform-table:begin -->
88 platforms: 10 boot-eligible, 10 core-smoke, 11 bios-blocked, 49 companion-only, 8 catalog-only.

With no file attached, 0 of 88 entries expose a browser Play URL. 38 report `missing_game_file`.

| Platform | Mode with file | Browser core | Free ROM listed | Browser firmware | Applicable check |
|---|---|---|---|---|---|
| Other (`OTHER`) | companion | – | no | – | companion-only |
| PC Windows (`PCWIN`) | companion | – | no | – | companion-only |
| PC DOS (`PCDOS`) | companion | – | no | – | companion-only |
| Mac (`MAC`) | companion | – | no | – | companion-only |
| Nintendo Entertainment System (NES) (`NES`) | browser | nestopia | yes | no blocker | boot-eligible |
| Super Nintendo Entertainment System (SNES) (`SNES`) | browser | snes9x | yes | no blocker | boot-eligible |
| Nintendo GameCube (`NGC`) | companion | – | no | – | companion-only |
| Nintendo 64 (`N64`) | browser | mupen64plus_next | yes | no blocker | boot-eligible |
| Nintendo GameBoy (`GB`) | browser | mgba | yes | no blocker | boot-eligible |
| Nintendo GameBoy Advance (`GBA`) | browser | mgba | yes | no blocker | boot-eligible |
| Nintendo GameBoy Color (`GBC`) | browser | mgba | yes | no blocker | boot-eligible |
| Nintendo DS (`NDS`) | browser | melonds | no | missing | bios-blocked |
| Nintendo Virtual Boy (`VB`) | browser | mednafen_vb | yes | no blocker | boot-eligible |
| Nintendo Wii (`WII`) | companion | – | no | – | companion-only |
| Nintendo 3DS (`N3DS`) | companion | – | no | – | companion-only |
| Sega Mega Drive/Genesis (MD) (`SEGA_MD`) | browser | genesis_plus_gx | yes | no blocker | boot-eligible |
| Sega Master System (MS) (`SEGA_MS`) | browser | genesis_plus_gx | no | no blocker | core-smoke |
| Sega CD (`SEGA_CD`) | browser | genesis_plus_gx | no | missing | bios-blocked |
| Sega 32X (`SEGA_32X`) | browser | genesis_plus_gx | no | no blocker | core-smoke |
| Sega Game Gear (GG) (`SEGA_GG`) | browser | genesis_plus_gx | no | no blocker | core-smoke |
| Sega Saturn (`SEGA_SATURN`) | browser | yabause | no | missing | bios-blocked |
| Sega Dreamcast (`SEGA_DC`) | companion | – | no | – | companion-only |
| Atari 7800 (`ATARI_7800`) | browser | prosystem | no | no blocker | core-smoke |
| Atari 5200 (`ATARI_5200`) | browser | a5200 | no | missing | bios-blocked |
| Atari 2600 (`ATARI_2600`) | browser | stella2014 | yes | no blocker | boot-eligible |
| Atari Lynx (`LYNX`) | browser | handy | yes | no blocker | boot-eligible |
| Atari Jaguar (`JAGUAR`) | browser | virtualjaguar | no | no blocker | core-smoke |
| PC Engine (`PCE`) | companion | – | no | – | companion-only |
| PC-FX (`PCFX`) | companion | – | no | – | companion-only |
| Neo Geo Pocket (`NGP`) | browser | mednafen_ngp | no | no blocker | core-smoke |
| WonderSwan (`WS`) | browser | mednafen_wswan | no | no blocker | core-smoke |
| ColecoVision (`COLECO`) | browser | gearcoleco | no | missing | bios-blocked |
| 3DO (`THREEDO`) | browser | opera | no | missing | bios-blocked |
| Vectrex (`VECTREX`) | browser | vecx | no | no blocker | core-smoke |
| Commodore 64 (`VICE_X64SC`) | companion | – | no | – | companion-only |
| Commodore 128 (`VICE_X128`) | companion | – | no | – | companion-only |
| Commodore VIC-20 (`VICE_XVIC`) | companion | – | no | – | companion-only |
| Commodore Plus/4 (`VICE_XPLUS4`) | companion | – | no | – | companion-only |
| Commodore PET (`VICE_XPET`) | companion | – | no | – | companion-only |
| Xbox (`XBOX`) | companion | – | no | – | companion-only |
| Xbox 360 (`X360`) | companion | – | no | – | companion-only |
| Xbox One (`XONE`) | companion | – | no | – | companion-only |
| Xbox Series X (`XSX`) | catalog | – | no | – | catalog-only |
| Sony Playstation (PSX) (`PSX`) | browser | mednafen_psx_hw | no | missing | bios-blocked |
| Sony PS2 (`PS2`) | companion | – | no | – | companion-only |
| Sony PS3 (`PS3`) | companion | – | no | – | companion-only |
| Sony PS4 (`PS4`) | companion | – | no | – | companion-only |
| Sony PS5 (`PS5`) | catalog | – | no | – | catalog-only |
| Sony PSP (`PSP`) | companion | – | no | – | companion-only |
| Sony PS Vita (`PSVITA`) | companion | – | no | – | companion-only |
| Intellivision (`INTV`) | browser | freeintv | no | missing | bios-blocked |
| Fairchild Channel F (`CHAF`) | browser | freechaf | no | missing | bios-blocked |
| Magnavox Odyssey 2 (`O2EM`) | browser | o2em | no | missing | bios-blocked |
| Neo Geo CD (`NEOGEO_CD`) | browser | neocd | no | missing | bios-blocked |
| Neo Geo AES (`NEOGEO`) | catalog | – | no | – | catalog-only |
| Nintendo Switch (`SWITCH`) | catalog | – | no | – | catalog-only |
| Arcade (`ARCADE`) | catalog | – | no | – | catalog-only |
| Commodore Amiga (`AMIGA`) | companion | – | no | – | companion-only |
| Sega SG-1000 (`SEGA_SG1000`) | browser | genesis_plus_gx | no | no blocker | core-smoke |
| PC Engine SuperGrafx (`SUPERGRAFX`) | companion | – | no | – | companion-only |
| PC Engine CD / TurboGrafx-CD (`PCE_CD`) | companion | – | no | – | companion-only |
| Neo Geo Pocket Color (`NGPC`) | browser | mednafen_ngp | no | no blocker | core-smoke |
| Watara Supervision (`SUPERVISION`) | companion | – | no | – | companion-only |
| Amstrad GX4000 (`GX4000`) | companion | – | no | – | companion-only |
| Bally Astrocade (`ASTROCADE`) | companion | – | no | – | companion-only |
| Emerson Arcadia 2001 (`ARCADIA`) | companion | – | no | – | companion-only |
| VTech CreatiVision (`CREATIVISION`) | companion | – | no | – | companion-only |
| Entex Adventure Vision (`ADVISION`) | companion | – | no | – | companion-only |
| RCA Studio II (`STUDIO2`) | companion | – | no | – | companion-only |
| WoW Action Max (`ACTIONMAX`) | catalog | – | no | – | catalog-only |
| Daphne (laserdisc) (`DAPHNE`) | companion | – | no | – | companion-only |
| Pinball (Future Pinball / VP) (`PINBALL`) | catalog | – | no | – | catalog-only |
| Nintendo Wii U (`WII_U`) | catalog | – | no | – | catalog-only |
| Pokémon Mini (`POKE_MINI`) | companion | – | no | – | companion-only |
| Nintendo Game & Watch (`GAME_WATCH`) | companion | – | no | – | companion-only |
| Philips CD-i (`CD_I`) | companion | – | no | – | companion-only |
| Sega Pico (`SEGA_PICO`) | companion | – | no | – | companion-only |
| Atari Jaguar CD (`JAGUAR_CD`) | companion | – | no | – | companion-only |
| Commodore Amiga CD32 (`AMIGA_CD32`) | companion | – | no | – | companion-only |
| MSX (`MSX`) | companion | – | no | – | companion-only |
| ZX Spectrum (`ZX_SPECTRUM`) | companion | – | no | – | companion-only |
| Amstrad CPC (`CPC`) | companion | – | no | – | companion-only |
| Atari ST (`ATARI_ST`) | companion | – | no | – | companion-only |
| Apple II (`APPLE_II`) | companion | – | no | – | companion-only |
| Atari 8-bit (`ATARI_8BIT`) | companion | – | no | – | companion-only |
| Sharp X68000 (`X68000`) | companion | – | no | – | companion-only |
| NEC PC-98 (`PC_98`) | companion | – | no | – | companion-only |
| BBC Micro (`BBC_MICRO`) | companion | – | no | – | companion-only |
<!-- platform-table:end -->
