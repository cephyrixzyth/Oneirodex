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

    assert len(rows) == len(LibraryPlatform)
    assert {r['state'] for r in rows} <= set(table.STATES)


def test_catalog_only_never_has_a_play_url(rows):
    assert all(not r['play_url'] for r in rows if r['state'] == 'catalog-only')


def test_companion_only_never_has_a_play_url(rows):
    assert all(not r['play_url'] for r in rows if r['state'] == 'companion-only')


def test_bios_blocked_are_hard_firmware_cores(rows):
    from oneirodex.utils.emulator_bios import BIOS_HARD_REQUIRED_CORES

    blocked = [r for r in rows if r['state'] == 'bios-blocked']
    assert blocked, 'expected firmware-dependent browser platforms'
    assert all(r['core'] in BIOS_HARD_REQUIRED_CORES or r['bios_missing'] for r in blocked)


def test_free_rom_platforms_are_browser_playable_and_need_no_firmware(rows):
    by_key = {r['key']: r for r in rows}
    for key in table.FREE_ROM_PLATFORMS.values():
        assert by_key[key]['state'] == 'game-tested', key


def test_core_smoke_platforms_have_a_core_and_no_free_rom(rows):
    smoke = [r for r in rows if r['state'] == 'core-smoke']
    assert smoke and all(r['core'] and not r['free_rom'] for r in smoke)


def test_the_published_table_is_current(rows):
    text = (ROOT / 'docs' / 'dev' / 'virtual-device-pass.md').read_text(encoding='utf-8')
    published = text.split(table.BEGIN, 1)[1].split(table.END, 1)[0].strip()
    assert published == table.to_markdown(rows).strip(), (
        'docs/dev/virtual-device-pass.md is stale: run python scripts/vdevice/platform_table.py --write'
    )
