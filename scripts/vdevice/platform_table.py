#!/usr/bin/env python3
"""Platform x virtual-device coverage table (Layer 1: every platform, no boot).

For each LibraryPlatform: how it is played, which core, whether firmware is
missing on an empty install, whether a legal free ROM exists, and -- the point
of the table -- what the virtual-device pass can honestly claim for it:

  game-tested     browser play AND a free ROM: boot test applies
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
}

STATES = ('game-tested', 'core-smoke', 'bios-blocked', 'companion-only', 'catalog-only')


def _free_rom_keys() -> set[str]:
    spec = importlib.util.spec_from_file_location('fetch_free_roms', ROOT / 'scripts' / 'fetch-free-roms.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    manifest = mod.load_simple_manifest(ROOT / 'samples' / 'free-roms' / 'manifest.yaml')
    return {FREE_ROM_PLATFORMS[r['platform']] for r in manifest['roms'] if r['platform'] in FREE_ROM_PLATFORMS}


def build_rows() -> list[dict]:
    from oneirodex.platform import LibraryPlatform, mapped_core_ids
    from oneirodex.utils.play_url import browse_play_fields

    free = _free_rom_keys()

    def resolve(name: str) -> dict:
        cores = mapped_core_ids(name)
        return {'emulators': cores, 'preferred': cores[0] if cores else None}

    rows = []
    # An empty install: no BIOS uploaded, so the firmware column is the honest default.
    with mock.patch('oneirodex.utils.emulator_bios.list_bios_files', return_value=[]), mock.patch(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform', resolve
    ):
        for plat in LibraryPlatform:
            game = SimpleNamespace(
                uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                library=SimpleNamespace(platform=SimpleNamespace(name=plat.name)),
            )
            fields = browse_play_fields(game)
            mode = fields['play_mode']
            has_rom = plat.name in free
            if mode == 'catalog':
                state = 'catalog-only'
            elif mode == 'companion':
                state = 'companion-only'
            elif fields.get('firmware_missing'):
                state = 'bios-blocked'
            elif has_rom:
                state = 'game-tested'
            else:
                state = 'core-smoke'
            rows.append({
                'key': plat.name,
                'label': str(plat.value),
                'mode': mode,
                'core': fields.get('emulator_core') or '',
                'play_url': bool(fields.get('play_url')),
                'bios_missing': bool(fields.get('firmware_missing')),
                'free_rom': has_rom,
                'state': state,
            })
    return rows


def to_markdown(rows: list[dict]) -> str:
    counts = {s: sum(1 for r in rows if r['state'] == s) for s in STATES}
    lines = [
        f'{len(rows)} platforms: ' + ', '.join(f'{counts[s]} {s}' for s in STATES) + '.',
        '',
        '| Platform | Mode | Core | Free ROM | Firmware | Pass can claim |',
        '|---|---|---|---|---|---|',
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} (`{r['key']}`) | {r['mode']} | {r['core'] or '–'} | "
            f"{'yes' if r['free_rom'] else 'no'} | {'missing' if r['bios_missing'] else 'ok'} | {r['state']} |"
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
