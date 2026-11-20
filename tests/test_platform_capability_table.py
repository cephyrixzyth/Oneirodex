"""Layer 1 of the virtual-device pass: every platform, no boot."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('platform_table', ROOT / 'scripts' / 'vdevice' / 'platform_table.py')
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)


@pytest.fixture(scope='module')
def rows():
    return table.build_rows()


def test_every_platform_gets_exactly_one_known_state(rows):
    from oneirodex.platform import LibraryPlatform

    assert sorted(r['key'] for r in rows) == sorted(p.name for p in LibraryPlatform)
    assert {r['state'] for r in rows} <= set(table.STATES)


def test_catalog_only_never_has_a_play_url(rows):
    assert all(not r['play_url'] for r in rows if r['state'] == 'catalog-only')


def test_companion_only_never_has_a_play_url(rows):
    assert all(not r['play_url'] for r in rows if r['state'] == 'companion-only')


def test_bios_blocked_are_hard_firmware_cores(rows):
    from oneirodex.utils.emulator_bios import BIOS_HARD_REQUIRED_CORES, PLATFORM_BIOS_OVERRIDES

    blocked = [r for r in rows if r['state'] == 'bios-blocked']
    assert blocked, 'expected firmware-dependent browser platforms'

    for row in blocked:
        assert row['play_url'] and row['bios_missing']
        assert row['core'] in BIOS_HARD_REQUIRED_CORES or PLATFORM_BIOS_OVERRIDES.get(row['key'])


def test_free_rom_platforms_are_browser_playable_and_need_no_firmware(rows):
    by_key = {r['key']: r for r in rows}
    for key in table.FREE_ROM_PLATFORMS.values():
        row = by_key[key]
        assert row['state'] == 'boot-eligible', key
        assert row['play_url'] and row['core'] and row['free_rom'] and not row['bios_missing'], key


def test_core_smoke_platforms_have_a_core_and_no_free_rom(rows):
    smoke = [r for r in rows if r['state'] == 'core-smoke']
    assert smoke and all(r['play_url'] and r['core'] and not r['free_rom'] and not r['bios_missing'] for r in smoke)


def test_unattached_entries_never_advertise_browser_play(rows):
    from oneirodex.utils.play_url import WEBRETRO_PLATFORMS

    assert all(not row['unattached_play_url'] for row in rows)
    for row in rows:
        if row['key'] in WEBRETRO_PLATFORMS:
            assert row['unattached_blocker'] == 'missing_game_file', row['key']


def test_the_published_table_is_current(rows):
    text = (ROOT / 'docs' / 'dev' / 'virtual-device-pass.md').read_text(encoding='utf-8')
    published = text.split(table.BEGIN, 1)[1].split(table.END, 1)[0].strip()
    assert published == table.to_markdown(rows).strip(), (
        'docs/dev/virtual-device-pass.md is stale: run python scripts/vdevice/platform_table.py --write'
    )
