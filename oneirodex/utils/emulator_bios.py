"""Admin BIOS / system file management for WebRetro / RetroArch."""

from __future__ import annotations

import os
from typing import Any

from flask import current_app, g, has_request_context
from werkzeug.utils import secure_filename

# Common libretro system files (operators supply legally obtained BIOS).
#
# Oneirodex never downloads or bundles BIOS: these files are proprietary console
# firmware. This table only describes what a core *asks for*, so the admin UI can
# say "PS2 needs scph39001.bin — missing" and the operator supplies it from their
# own dump or their own firmware set. See docs/runbooks/emulator-bios.md.
BIOS_REQUIREMENTS: dict[str, list[str]] = {
    'mednafen_psx_hw': ['scph5500.bin', 'scph5501.bin', 'scph5502.bin'],
    'opera': ['panafz1.bin', 'panafz10.bin'],
    'neocd': ['neocd_f.rom', 'neocd_sf.rom', 'neocd_st.rom', 'neocd_z.rom', 'front-sp1.bin'],
    'yabause': ['saturn_bios.bin'],
    'genesis_plus_gx': ['bios_CD_U.bin', 'bios_CD_E.bin', 'bios_CD_J.bin'],
    # Console-gaming leaf systems (2026-08-03).
    'flycast': ['dc_boot.bin', 'dc_flash.bin'],
    'pcsx2': ['scph39001.bin', 'scph70012.bin'],
    'melonds': ['bios7.bin', 'bios9.bin', 'firmware.bin'],
    'mgba': ['gba_bios.bin'],
    'handy': ['lynxboot.img'],
    'gearcoleco': ['colecovision.rom'],
    'freeintv': ['exec.bin', 'grom.bin'],
    'o2em': ['o2rom.bin'],
    'mednafen_pce': ['syscard3.pce'],
    'mednafen_pce_fast': ['syscard3.pce'],
    'mednafen_supergrafx': ['syscard3.pce'],
    'puae': ['kick34005.A500', 'kick40068.A1200', 'kick33180.A500'],
    'cap32': ['cpc6128.rom'],
    'prosystem': ['7800 BIOS (U).rom'],
    # --- Coverage completion (2026-08-24) -----------------------------------
    # Every core reachable from platform_emulator_mapping that asks for a system
    # file now has a row, so the panel can answer "what do I still need?" for
    # the whole catalog instead of the subset that happened to be filled in.
    # Cores that need nothing (stella2014, mednafen_vb/_wswan/_ngp, potator,
    # vecx, dosbox*) are deliberately still absent — a row for them would be a
    # permanent "missing" the operator can never satisfy.
    #
    # Hard requirements: the core cannot boot the system at all without these.
    'a5200': ['5200.rom'],
    'freechaf': ['sl31253.bin', 'sl31254.bin', 'sl90025.bin'],
    'crvision': ['bioss.rom'],
    'citra': ['aes_keys.txt', 'boot9.bin'],
    'vita3k': ['PSP2UPDAT.PUP'],
    # Optional/accuracy files. Listed so the operator can see the slot exists,
    # but kept out of BIOS_HARD_REQUIRED_CORES so the panel does not call a
    # working system broken:
    #   nestopia   — disksys.rom is Famicom Disk System only; carts are fine.
    #   dolphin    — GameCube IPL is the boot animation, not a requirement.
    #   snes9x     — DSP/CX4 co-processor ROMs, needed by a handful of titles.
    #   *_n64      — 64DD IPL, needed only for 64DD disk images.
    #   gearsystem — SMS/Coleco boot ROMs improve accuracy; not required.
    #   virtualjaguar — jagboot.rom is the Jaguar boot logo.
    #   vice_x64   — the libretro core embeds the C64 ROMs; external copies
    #                only matter for exact-revision accuracy.
    'nestopia': ['disksys.rom'],
    'dolphin': ['IPL.bin'],
    'snes9x': ['dsp1.bin', 'dsp1b.bin', 'dsp2.bin', 'dsp3.bin', 'dsp4.bin', 'cx4.bin', 'st010.bin', 'st011.bin'],
    'mupen64plus_next': ['64DD_IPL.n64'],
    'parallel_n64': ['64DD_IPL.n64'],
    'gearsystem': ['bios_U.sms', 'bios.col'],
    'virtualjaguar': ['jagboot.rom'],
    'vice_x64': ['kernal', 'basic', 'chargen'],
    # Deliberately absent: mame / mame2003_plus. MAME system files are per-romset
    # archives (neogeo.zip and friends) that live beside the ROMs, not single
    # files on the firmware volume, so listing them here would report a
    # permanent shortfall against a volume that is not where they belong.
}

# Which of the above a core genuinely cannot boot without. Everything else is an
# optional accuracy/enhancement file, so the UI does not cry wolf about e.g.
# gba_bios.bin, which mGBA happily runs without via its HLE fallback.
BIOS_HARD_REQUIRED_CORES = frozenset({
    'mednafen_psx_hw', 'opera', 'neocd', 'yabause', 'flycast', 'pcsx2',
    'melonds', 'mednafen_pce', 'mednafen_pce_fast', 'mednafen_supergrafx',
    'puae', 'freeintv', 'o2em', 'gearcoleco',
    # Coverage completion (2026-08-24): these will not boot their system at all
    # without the listed file, so the panel should say so plainly.
    'a5200', 'freechaf', 'crvision', 'citra', 'vita3k',
})


# Firmware a *platform* needs, where that differs from what its core asks for.
#
# BIOS_REQUIREMENTS is keyed by core, which is right for the per-core view but
# wrong for the per-system one, because one core covers many consoles. The
# per-platform panel used to union every requirement of every core mapped to a
# platform, so `genesis_plus_gx` needing the Sega CD BIOS made Master System,
# Game Gear, SG-1000, Mega Drive and 32X all claim to need it — and, once the
# Sega CD files were present, all report "ready" on the strength of firmware
# that has nothing to do with a cartridge. The verdict was accidentally correct
# and the reasoning shown to the operator was nonsense.
#
# A platform listed here uses exactly these files, whatever its cores ask for.
# An empty tuple means the system needs no firmware at all, so it drops out of
# the panel entirely — the same treatment cores with no requirements already get,
# and better than a row the operator can never satisfy.
PLATFORM_BIOS_OVERRIDES: dict[str, tuple[str, ...]] = {
    # genesis_plus_gx carries the Sega CD BIOS; only the Sega CD needs it.
    'SEGA_MD': (),
    'SEGA_MS': (),
    'SEGA_GG': (),
    'SEGA_32X': (),
    'SEGA_SG1000': (),
    # mgba carries gba_bios.bin, which is a GBA file. Game Boy and Game Boy
    # Color run on the same core and need nothing.
    'GB': (),
    'GBC': (),
    # mednafen_pce* carry the CD system card. HuCard and SuperGrafx carts do not
    # use it; only the CD add-on does.
    'PCE': (),
    'SUPERGRAFX': (),
    # dolphin carries the GameCube IPL. The Wii does not use it.
    'WII': (),
    # Optional accuracy files must not make the cartridge console look unready.
    'NES': (),
    'SNES': (),
    'N64': (),
    # Same core as MD carts; only the CD add-on is a hard BIOS gate for Play.
    'SEGA_CD': ('bios_CD_U.bin', 'bios_CD_E.bin', 'bios_CD_J.bin'),
}


def bios_status_for_platforms() -> list[dict[str, Any]]:
    """Per-system BIOS readiness for the admin firmware panel.

    Answers the operator question directly — "which of my systems can actually
    play?" — instead of making them map libretro core ids to consoles by hand.

    Readiness is judged on *loadable* files only, the same rule
    bios_status_for_cores follows. Both views read one list, so counting a
    nested file here would have this panel call a system ready while the core
    panel called the same file misplaced.
    """
    from oneirodex.platform import LibraryPlatform, platform_emulator_mapping

    files = list_bios_files()
    present = {row['name'].lower() for row in files if row['loadable']}
    nested = {
        row['name'].lower(): row['subdir'] for row in files if not row['loadable']
    }
    rows: list[dict[str, Any]] = []
    for platform, cores in platform_emulator_mapping.items():
        core_ids = [c.value for c in cores]
        if platform.name in PLATFORM_BIOS_OVERRIDES:
            # The platform states its own firmware, because its core's list
            # belongs to a different console on the same core.
            needed = set(PLATFORM_BIOS_OVERRIDES[platform.name])
        else:
            needed = {
                name
                for core in core_ids
                for name in BIOS_REQUIREMENTS.get(core, [])
            }
        if not needed:
            continue
        missing = sorted(n for n in needed if n.lower() not in present)
        found = sorted(n for n in needed if n.lower() in present)
        # Named separately so the panel can say "move these" rather than
        # "missing" for a file the operator can plainly see on disk.
        misplaced = [
            {'name': name, 'subdir': nested[name.lower()]}
            for name in sorted(needed)
            if name.lower() in nested and name.lower() not in present
        ]
        hard = any(core in BIOS_HARD_REQUIRED_CORES for core in core_ids)
        rows.append({
            'platform': platform.name,
            'label': platform.value,
            'cores': core_ids,
            'required': sorted(needed),
            'present': found,
            'missing': missing,
            'misplaced': misplaced,
            # Any one accepted file is usually enough (region variants).
            'ready': bool(found),
            'blocking': bool(missing) and not found and hard,
        })
    rows.sort(key=lambda r: (not r['blocking'], r['label']))
    return rows


def firmware_play_state(platform_key: str | None, core: str | None) -> dict[str, Any]:
    """Member Play honesty — block only when the system cannot boot.

    Admin already scopes firmware with ``PLATFORM_BIOS_OVERRIDES`` and
    ``BIOS_HARD_REQUIRED_CORES``. Browse used to treat every
    ``BIOS_REQUIREMENTS`` row as a hard gate, so an empty firmware volume
    greyed NES (optional ``disksys.rom``), SNES (DSP/CX4), N64 (64DD IPL),
    and Genesis carts (Sega CD BIOS on the shared core).
    """
    empty = {
        'bios_required': False,
        'firmware_missing': False,
        'required': [],
        'present': [],
        'missing': [],
        'ready': True,
    }
    if not core:
        return empty

    if platform_key and platform_key in PLATFORM_BIOS_OVERRIDES:
        needed = list(PLATFORM_BIOS_OVERRIDES[platform_key])
        hard = bool(needed)
    else:
        needed = list(BIOS_REQUIREMENTS.get(core) or [])
        hard = core in BIOS_HARD_REQUIRED_CORES

    if not needed or not hard:
        return empty

    present_names = {
        row['name'].lower()
        for row in list_bios_files()
        if row.get('loadable', True)
    }
    found = [name for name in needed if name.lower() in present_names]
    missing = [name for name in needed if name.lower() not in present_names]
    firmware_missing = len(found) == 0
    return {
        'bios_required': True,
        'firmware_missing': firmware_missing,
        'required': needed,
        'present': found,
        'missing': missing,
        'ready': not firmware_missing,
    }


def bios_root() -> str:
    root = current_app.config.get('EMULATOR_BIOS_PATH')
    if root:
        return root
    # Imported here: scripts/import_bios.py loads this module by path, without
    # the oneirodex package, for BIOS_REQUIREMENTS alone.
    from oneirodex.utils.library_paths import library_dir

    return os.path.join(library_dir(), 'bios')


def list_bios_files() -> list[dict[str, Any]]:
    """Every BIOS file under the firmware volume, including subdirectories.

    This used to be a flat ``os.listdir`` that skipped directories, so a
    firmware set organised the way they almost always ship — ``bios/psx/``,
    ``bios/saturn/`` — was invisible. The operator saw "no BIOS loaded" having
    just copied a hundred files in, with nothing explaining why.

    Subdirectories are walked so those files are *found*, but each row carries
    ``subdir`` because being found is not the same as being usable: libretro
    cores look for firmware in the system root only. A file one level down is
    present on disk and still will not load, and the UI has to be able to say
    so rather than silently listing it as ready.
    """
    if has_request_context() and hasattr(g, '_bios_files_cache'):
        return g._bios_files_cache

    root = bios_root()
    os.makedirs(root, exist_ok=True)
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        subdir = '' if rel == '.' else rel.replace(os.sep, '/')
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if not os.path.isfile(path):
                continue
            rows.append({
                'name': name,
                'size': os.path.getsize(path),
                'subdir': subdir,
                # Cores read the system root; anything nested needs moving.
                'loadable': subdir == '',
            })

    rows.sort(key=lambda row: (row['subdir'], row['name'].lower()))

    if has_request_context():
        g._bios_files_cache = rows
    return rows


def bios_status_for_cores() -> list[dict[str, Any]]:
    """Per-core readiness, distinguishing "absent" from "present but misplaced".

    Those are different problems with different fixes — download it, versus move
    it up a directory — and reporting both as "missing" is what made a populated
    firmware volume look empty.
    """
    files = list_bios_files()
    loadable = {row['name'].lower() for row in files if row['loadable']}
    misplaced = {
        row['name'].lower(): row['subdir'] for row in files if not row['loadable']
    }

    status = []
    for core, required in BIOS_REQUIREMENTS.items():
        found = [name for name in required if name.lower() in loadable]
        nested = [
            {'name': name, 'subdir': misplaced[name.lower()]}
            for name in required
            if name.lower() in misplaced and name.lower() not in loadable
        ]
        status.append({
            'core': core,
            'required': required,
            'present': found,
            'ready': len(found) > 0,
            # Named separately so the UI can say "move these" rather than
            # "missing" for a file the operator can plainly see on disk.
            'misplaced': nested,
        })
    return status


# Firmware is operator-supplied and lands on a mounted volume, so the upload
# path is treated as untrusted input: allowlist the shapes a libretro core can
# actually consume rather than accepting anything with a safe-looking name.
ALLOWED_BIOS_EXTENSIONS = frozenset({
    '.bin', '.rom', '.img', '.bios', '.sys', '.dat', '.zip',
    # PC Engine CD system card, and the Amiga Kickstart names puae expects
    # (`kick34005.A500`). Anything listed in BIOS_REQUIREMENTS has to be
    # uploadable, or the panel reports a missing file the operator cannot supply.
    '.pce', '.a500', '.a600', '.a1200', '.a4000',
    # Coverage completion (2026-08-24), same rule — each of these is the literal
    # shape of a file now named in BIOS_REQUIREMENTS:
    #   .pup  vita3k's PSP2UPDAT.PUP    .n64  64DD_IPL.n64
    #   .sms  gearsystem's bios_U.sms   .col  gearsystem's bios.col
    '.pup', '.n64', '.sms', '.col',
})

# Firmware files an extension allowlist cannot express.
#
# The VICE C64 ROMs ship with no suffix at all, and citra's key file is a plain
# `.txt` — admitting either by extension would mean admitting every
# extensionless upload, or every text file, onto the firmware volume. Matching
# the exact names instead keeps the hole the size of the actual requirement.
ALLOWED_BIOS_EXACT_NAMES = frozenset({
    'kernal', 'basic', 'chargen',   # vice_x64
    'aes_keys.txt',                 # citra
})

# Retro system files are small; the cap exists to stop a mistaken ROM-set or
# disk-image upload filling the BIOS volume. Override with EMULATOR_BIOS_MAX_BYTES.
DEFAULT_BIOS_MAX_BYTES = 64 * 1024 * 1024


def _max_bios_bytes() -> int:
    try:
        value = int(current_app.config.get('EMULATOR_BIOS_MAX_BYTES') or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_BIOS_MAX_BYTES


def _upload_size(file_storage) -> int:
    """Byte length of an upload without reading it into memory."""
    stream = getattr(file_storage, 'stream', None)
    if stream is None or not hasattr(stream, 'seek') or not hasattr(stream, 'tell'):
        return 0
    try:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current)
        return int(size)
    except (OSError, ValueError):
        return 0


def store_bios_file(file_storage) -> dict[str, Any]:
    """Persist one operator-supplied firmware file to the BIOS volume.

    BIOS/firmware is never bundled or downloaded by Oneirodex — it is uploaded
    by the operator from media they own. This function is the only write path,
    so validation lives here rather than at the route.

    Raises ValueError with a user-safe message on every rejection.
    """
    root = bios_root()
    os.makedirs(root, exist_ok=True)

    original = secure_filename(getattr(file_storage, 'filename', None) or '')
    if not original:
        raise ValueError('Filename required')

    extension = os.path.splitext(original)[1].lower()
    if (
        extension not in ALLOWED_BIOS_EXTENSIONS
        and original.lower() not in ALLOWED_BIOS_EXACT_NAMES
    ):
        allowed = ', '.join(sorted(ALLOWED_BIOS_EXTENSIONS))
        raise ValueError(
            f'Unsupported firmware file type "{extension or "none"}". Allowed: {allowed}'
        )

    size = _upload_size(file_storage)
    limit = _max_bios_bytes()
    if size > limit:
        raise ValueError(
            f'Firmware file is {size // (1024 * 1024)}MB; limit is {limit // (1024 * 1024)}MB'
        )
    if size == 0:
        raise ValueError('Firmware file is empty')

    dest = os.path.join(root, original)
    # Defence in depth: secure_filename already strips separators, but the
    # destination must provably stay inside the BIOS volume before we write.
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(dest)]) != os.path.realpath(root):
        raise ValueError('Invalid destination path')

    file_storage.save(dest)
    return {'name': original, 'size': os.path.getsize(dest)}
