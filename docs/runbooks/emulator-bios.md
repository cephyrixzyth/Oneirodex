# Emulator BIOS / firmware (operator-supplied)

**Audience:** Operator · **Stance:** LOCKED

## What Oneirodex does and does not do

Oneirodex **never downloads, bundles, or ships console BIOS**. Those files are
proprietary console firmware — Sony, Sega, Nintendo, Panasonic, SNK and friends
still own them. The application only ever:

1. **describes** what each libretro core asks for (`BIOS_REQUIREMENTS`), and
2. **reports** which of those files are present on your firmware volume.

Filling the gaps is the operator's job, from a source you are entitled to use —
a dump of hardware you own, or a firmware set you already hold. The public image
stays upload-only, and `.gitignore` blocks `bios/`, `**/bios/*.bin`,
`**/bios/*.rom` and `oneirodex/static/library/bios/` so firmware cannot reach the
public repository even by accident.

## Where files go

| Deployment | Location |
|---|---|
| Docker / Unraid | the volume mounted at `EMULATOR_BIOS_PATH` |
| Bare metal (default) | `oneirodex/static/library/bios/` |

Drop files in flat — no per-system subfolders. Names are matched
case-insensitively, so `SCPH5501.BIN` and `scph5501.bin` both count.

## Filling the volume

Operator-supplied only. There is no download button.

| How | When |
|---|---|
| **Upload one file** | Admin → Emulation → Firmware file input (`POST /api/emulator-bios`) |
| **Scan a collection** | Same page: set a folder (and its subfolders). **Scan collection** previews matches; **Install matching firmware** copies the names this service asks for, flattened onto the volume. If several dumps share a filename, pick which one that system should use before installing. A popup lists what is still missing as **copyable markdown**. |
| **Boot import** | Set `BIOS_IMPORT_SOURCE` to that folder. Missing names are copied on startup; existing files are never replaced. |
| **CLI** | `python scripts/import_bios.py --source /path/to/dumps` (preview) then `--apply` |
| **Volume mount** | Bind a private host folder at `EMULATOR_BIOS_PATH` |

The folder must sit under a library root (`ONEIRODEX_LIBRARY_ROOTS` / `BASE_FOLDER_*`) or be the path named by `BIOS_IMPORT_SOURCE`.

Symbolic links inside the collection are skipped, by the admin scan/install, the boot import and `scripts/import_bios.py` alike: a `scph5501.bin -> /somewhere/else` would otherwise copy whatever it points at into the firmware volume, which every signed-in member can download. Keep real files in the collection folder (a hardlink is fine). A file replaced by a link between the scan and the copy is reported as not installed rather than followed.

`GET /api/emulator-bios` includes `import_source` (the configured default) and `missing_markdown`. Preview/apply are `POST /api/emulator-bios/scan` and `POST /api/emulator-bios/install`.

## Checking coverage

**Admin → Emulation → Firmware** lists every system that needs firmware and what
is missing, e.g. *"PC Engine CD — missing `syscard3.pce`"*. The same data is on
`GET /api/emulator-bios`:

- `platforms[]` — per-system view: `required`, `present`, `missing`, `ready`,
  `blocking`
- `cores[]` — the older per-core view, kept for existing callers
- `files[]` — what is actually on the volume

`blocking: true` means that system genuinely cannot boot without the file.
Optional accuracy files (for example `gba_bios.bin`, which mGBA replaces with its
HLE fallback) are reported as missing but never marked blocking, so the panel
does not cry wolf.

## Systems that need firmware

Cores read these names; region variants are interchangeable — **any one** present
is usually enough.

| System | Files |
|---|---|
| PlayStation | `scph5500.bin` · `scph5501.bin` · `scph5502.bin` |
| PlayStation 2 | `scph39001.bin` · `scph70012.bin` |
| Saturn | `saturn_bios.bin` |
| Sega CD | `bios_CD_U.bin` · `bios_CD_E.bin` · `bios_CD_J.bin` |
| Dreamcast | `dc_boot.bin` · `dc_flash.bin` |
| 3DO | `panafz1.bin` · `panafz10.bin` |
| Neo Geo CD | `neocd_f.rom` · `neocd_sf.rom` · `neocd_st.rom` · `neocd_z.rom` · `front-sp1.bin` |
| PC Engine CD / SuperGrafx | `syscard3.pce` |
| Commodore Amiga | `kick34005.A500` · `kick40068.A1200` · `kick33180.A500` |
| Nintendo DS | `bios7.bin` · `bios9.bin` · `firmware.bin` |
| Game Boy Advance *(optional)* | `gba_bios.bin` |
| Atari Lynx | `lynxboot.img` |
| Atari 7800 *(optional)* | `7800 BIOS (U).rom` |
| ColecoVision | `colecovision.rom` |
| Intellivision | `exec.bin` · `grom.bin` |
| Magnavox Odyssey 2 | `o2rom.bin` |
| Amstrad GX4000 | `cpc6128.rom` |
| Atari 5200 | `5200.rom` |
| Fairchild Channel F | `sl31253.bin` · `sl31254.bin` · `sl90025.bin` |
| VTech CreatiVision | `bioss.rom` |
| Nintendo 3DS | `aes_keys.txt` · `boot9.bin` |
| PlayStation Vita | `PSP2UPDAT.PUP` |

### Optional — improves accuracy, not required to boot

These have a slot in the panel so you can see it exists, but the system plays
without them, so a missing file here is not reported as blocking. Browse and
details use the same rule (`firmware_play_state`) — an empty firmware volume
must not grey NES / SNES / N64 / Genesis carts.

| System | Files | Needed for |
|---|---|---|
| Famicom Disk System | `disksys.rom` | FDS disk images only; carts are fine |
| GameCube / Wii | `IPL.bin` | the GameCube boot animation |
| SNES | `dsp1.bin` · `dsp1b.bin` · `dsp2.bin` · `dsp3.bin` · `dsp4.bin` · `cx4.bin` · `st010.bin` · `st011.bin` | a handful of co-processor carts |
| Nintendo 64 | `64DD_IPL.n64` | 64DD disk images |
| Master System / SG-1000 | `bios_U.sms` · `bios.col` | boot-ROM accuracy |
| Atari Jaguar | `jagboot.rom` | the Jaguar boot logo |
| Commodore 64 | `kernal` · `basic` · `chargen` | exact-revision accuracy; the core embeds its own |

Neo Geo AES cart sets expect `neogeo.zip` alongside the ROMs rather than on the
firmware volume — it is a MAME/FBNeo parent set, not a BIOS file. The same is
true of the other MAME-driven systems (Astrocade, Arcadia, Advision, Studio II):
their system files are per-romset archives, so they are deliberately absent from
the firmware panel rather than reported as permanently missing.

### Why some systems are not in the panel at all

One libretro core often serves several consoles, and its firmware usually
belongs to only one of them. `genesis_plus_gx` runs Mega Drive, Master System,
Game Gear, SG-1000, 32X **and** Sega CD — but only the Sega CD needs a BIOS.

Requirements are therefore scoped per *platform*, not per core
(`PLATFORM_BIOS_OVERRIDES` in `oneirodex/utils/emulator_bios.py`). A system that
needs no firmware drops out of the panel rather than appearing with a
requirement that makes no sense for it:

| Core | Firmware belongs to | Absent from the panel |
|---|---|---|
| `genesis_plus_gx` | Sega CD | Mega Drive · Master System · Game Gear · SG-1000 · 32X |
| `mgba` | Game Boy Advance | Game Boy · Game Boy Color |
| `mednafen_pce*` | PC Engine CD | PC Engine (HuCard) · SuperGrafx |
| `dolphin` | GameCube (`IPL.bin`) | Wii |

Before this scoping the panel unioned every core's requirements onto every
platform that core served, so five cartridge Sega systems claimed to need the
Sega CD BIOS — and, once those files were present, all five reported "ready" on
the strength of firmware irrelevant to a cartridge. The verdict was accidentally
right and the reason shown was wrong.

The **per-core** view is unaffected and still lists `genesis_plus_gx` as wanting
the Sega CD files, which is true of the core.

## Upload guardrails

Uploads are treated as untrusted: extension allowlist, and a size cap
(`EMULATOR_BIOS_MAX_BYTES`, default 64 MB) so a stray disk image cannot fill the
volume.

Two firmware names cannot be expressed as an extension — the Commodore 64 ROMs
(`kernal`, `basic`, `chargen`) have no suffix at all, and the 3DS key file is a
plain `.txt`. Those four are allowed by **exact filename** instead, so the volume
does not have to accept every extensionless or text upload to admit them.
