#!/usr/bin/env python3
"""Platform x virtual-device coverage table (Layer 1: every platform, no boot).

For each LibraryPlatform: how it is played, which core, whether firmware is
missing on an empty install, whether a legal free ROM exists, and -- the point
of the table -- what the virtual-device pass can honestly claim for it:

  boot-eligible   browser play with a free ROM listed for a future boot check
  core-smoke      browser play, no legal ROM: the core can only be smoke-tested
  bios-blocked    browser play, but the core needs firmware we do not ship
  companion-only  played by a desktop emulator; not testable in this container
  catalog-only    never offered play; asserted to stay that way

Offline: no database, no network. Used by tests/test_platform_capability_table.py
and, with --write, to refresh the table in docs/dev/virtual-device-pass.md.

    python scripts/vdevice/platform_table.py            # print markdown
    python scripts/vdevice/platform_table.py --write    # refresh the doc
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('SECRET_KEY', 'vdevice-table-only-' + 'x' * 40)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DOC = ROOT / 'docs' / 'dev' / 'virtual-device-pass.md'
BEGIN = '<!-- platform-table:begin -->'
END = '<!-- platform-table:end -->'

#: manifest platform id -> LibraryPlatform key
FREE_ROM_PLATFORMS = {
    'nes': 'NES',
    'gb': 'GB',
    'gbc': 'GBC',
    'gba': 'GBA',
    'genesis': 'SEGA_MD',
    'atari2600': 'ATARI_2600',
    'snes': 'SNES',
    'n64': 'N64',
    'lynx': 'LYNX',
    'vb': 'VB',
}

STATES = ('boot-eligible', 'core-smoke', 'bios-blocked', 'companion-only', 'catalog-only')


def _free_rom_keys() -> set[str]:
    spec = importlib.util.spec_from_file_location('fetch_free_roms', ROOT / 'scripts' / 'fetch-free-roms.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    manifest = mod.load_simple_manifest(ROOT / 'samples' / 'free-roms' / 'manifest.yaml')
    return {FREE_ROM_PLATFORMS[r['platform']] for r in manifest['roms'] if r['platform'] in FREE_ROM_PLATFORMS}


def build_rows() -> list[dict]:
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.play_url import browse_play_fields

    free = _free_rom_keys()

    rows = []
    # Use the stock core list and settings. An operator's optional cores,
    # profiles and firmware must not change the published baseline.
    with (
        tempfile.TemporaryDirectory(prefix='oneirodex-platform-') as folder,
        mock.patch('oneirodex.utils.webretro_cores.discover_webretro_cores', return_value=frozenset()),
        mock.patch('oneirodex.utils.emulator_profiles.get_emulator_profiles', return_value={}),
        mock.patch('oneirodex.utils.browser_player._settings_row', return_value=None),
        mock.patch('oneirodex.utils.emulator_bios.list_bios_files', return_value=[]),
    ):
        sample = Path(folder) / 'sample.bin'
        sample.write_bytes(b'Oneirodex classification fixture')
        for plat in LibraryPlatform:
            game = SimpleNamespace(
                uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                library=SimpleNamespace(platform=plat),
                full_disk_path=str(sample),
            )
            fields = browse_play_fields(game)
            game.full_disk_path = None
            unattached = browse_play_fields(game)
            mode = fields['play_mode']
            has_rom = plat.name in free
            if mode == 'catalog':
                state = 'catalog-only'
            elif mode == 'companion':
                state = 'companion-only'
            elif fields.get('firmware_missing'):
                state = 'bios-blocked'
            elif has_rom:
                state = 'boot-eligible'
            else:
                state = 'core-smoke'
            rows.append({
                'key': plat.name,
                'label': str(plat.value),
                'mode': mode,
                'core': fields.get('emulator_core') or '',
                'play_url': bool(fields.get('play_url')),
                'unattached_play_url': bool(unattached.get('play_url')),
                'unattached_blocker': unattached.get('play_blocker'),
                'bios_missing': bool(fields.get('firmware_missing')),
                'free_rom': has_rom,
                'state': state,
            })
    return rows


def to_markdown(rows: list[dict]) -> str:
    counts = {s: sum(1 for r in rows if r['state'] == s) for s in STATES}
    unattached_links = sum(r['unattached_play_url'] for r in rows)
    missing_file = sum(r['unattached_blocker'] == 'missing_game_file' for r in rows)
    lines = [
        f'{len(rows)} platforms: ' + ', '.join(f'{counts[s]} {s}' for s in STATES) + '.',
        '',
        f'With no file attached, {unattached_links} of {len(rows)} entries expose a browser Play URL. '
        f'{missing_file} report `missing_game_file`.',
        '',
        '| Platform | Mode with file | Browser core | Free ROM listed | Browser firmware | Applicable check |',
        '|---|---|---|---|---|---|',
    ]
    for r in rows:
        firmware = ('missing' if r['bios_missing'] else 'no blocker') if r['mode'] == 'browser' else '–'
        lines.append(
            f"| {r['label']} (`{r['key']}`) | {r['mode']} | {r['core'] or '–'} | "
            f"{'yes' if r['free_rom'] else 'no'} | {firmware} | {r['state']} |"
        )
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--write', action='store_true', help=f'refresh the table in {DOC.relative_to(ROOT)}')
    args = parser.parse_args(argv)
    table = to_markdown(build_rows())
    if not args.write:
        sys.stdout.write(table + '\n')
        return 0
    text = DOC.read_text(encoding='utf-8')
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    DOC.write_text(f'{head}{BEGIN}\n{table}\n{END}{tail}', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
