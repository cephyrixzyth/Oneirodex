"""Unit tests for ROM language / patch filename heuristics."""

from types import SimpleNamespace

from oneirodex.utils.rom_language import (
    apply_rom_language_fields,
    classify_patch_file,
    parse_rom_language_tags,
    preferred_locale_matches,
    rom_language_fields_from_path,
)
from oneirodex.utils.rom_name_peel import parse_console_rom_label


def test_parse_japan_region_implies_ja():
    parsed = parse_rom_language_tags('Final Fantasy (Japan).sfc')
    assert parsed['rom_region'] == 'JPN'
    assert parsed['languages'] == ['ja']
    assert parsed['has_english'] is False


def test_parse_usa_implies_en():
    parsed = parse_rom_language_tags('Super Metroid (USA).sfc')
    assert parsed['rom_region'] == 'USA'
    assert 'en' in parsed['languages']
    assert parsed['has_english'] is True


def test_parse_explicit_lang_list():
    parsed = parse_rom_language_tags('Game (Europe) (En,Fr,De).nes')
    assert parsed['rom_region'] == 'EUR'
    assert parsed['languages'] == ['en', 'fr', 'de']
    assert parsed['has_english'] is True


def test_path_projection_handles_windows_separators_and_empty_paths():
    assert rom_language_fields_from_path(r'R:\ROMs\Game (Japan) (En,Ja).zip') == {
        'rom_region': 'JPN', 'rom_languages': 'en,ja',
    }
    assert rom_language_fields_from_path(None) == {
        'rom_region': None, 'rom_languages': None,
    }


def test_preferred_locale_mismatch_jpn_vs_en_us():
    assert preferred_locale_matches('en-US', ['ja'], region='JPN') is False
    assert preferred_locale_matches('ja-JP', ['ja'], region='JPN') is True
    assert preferred_locale_matches('en-US', ['en'], region='USA') is True


def test_classify_patch_file():
    meta = classify_patch_file('MyGame_English.bps')
    assert meta is not None
    assert meta['extra_kind'] == 'translation_patch'
    assert meta['patch_format'] == 'bps'
    assert meta['target_language'] == 'en'
    assert classify_patch_file('readme.txt') is None


def test_apply_rom_language_fields_persists_region_paren():
    game = SimpleNamespace(name='x', full_disk_path=None, rom_region=None, rom_languages=None, has_english=None)
    apply_rom_language_fields(game, r'C:\roms\Super Metroid (USA).sfc')
    assert game.rom_region == 'USA'
    assert game.rom_languages == 'en'
    assert game.has_english is True


def test_apply_rom_language_fields_persists_lang_list():
    game = SimpleNamespace(name='x', full_disk_path=None, rom_region=None, rom_languages=None, has_english=None)
    apply_rom_language_fields(game, 'Game (Europe) (En,Fr,De).nes')
    assert game.rom_region == 'EUR'
    assert game.rom_languages == 'en,fr,de'
    assert game.has_english is True


def test_apply_prefers_peel_capture_over_cleaned_name():
    """Peel captures win even when game.name is already stripped of tags."""
    game = SimpleNamespace(
        name='Game',
        full_disk_path=None,
        rom_region=None,
        rom_languages=None,
        has_english=None,
    )
    peel = parse_console_rom_label('Game (Europe) (En,Fr,De).gb')
    assert peel['cleaned_name'] == 'Game'
    assert peel['rom_region'] == 'EUR'
    apply_rom_language_fields(game, peel=peel)
    assert game.rom_region == 'EUR'
    assert game.rom_languages == 'en,fr,de'


def test_console_peel_exposes_region_and_lang_keys():
    peel = parse_console_rom_label('Final Fantasy (Japan).sfc')
    assert peel['rom_region'] == 'JPN'
    assert peel['rom_languages'] == 'ja'
    assert peel['has_english'] is False
    assert peel['languages'] == ['ja']
