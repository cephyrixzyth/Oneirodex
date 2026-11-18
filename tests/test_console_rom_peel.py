"""Console file-leaf ROM peel — B15–B20 + C12 (W20-7 GM fixtures)."""

from __future__ import annotations

import pytest

from oneirodex.platform import LibraryPlatform
from oneirodex.utils.gamenames import generate_goty_variants
from oneirodex.utils.rom_language import parse_rom_language_tags
from oneirodex.utils.rom_name_peel import ARCADE_PROPOSE_FIRST_CHILD_THRESHOLD, arcade_library_is_large, looks_like_arcade_set_basename, looks_like_console_rom_dump_label, parse_console_rom_label, should_arcade_propose_first, should_use_console_rom_peel
from oneirodex.utils.set_completion import normalize_set_title
from oneirodex.utils.software_identify import (
    filter_tgdb_hits_for_platform,
    tgdb_platform_matches,
)


class _Lib:
    def __init__(self, platform):
        self.platform = platform


# GM AC fixture table (16 rows)
GM_FIXTURES = [
    (
        'Pokemon - Red Version (USA, Europe) (SGB Enhanced) (Rev A) [!].gb',
        'Pokemon - Red Version',
    ),
    (
        'Legend of Zelda, The (USA) (Rev B) [!].gb',
        'Legend of Zelda, The',
    ),
    (
        'Tetris (World) (Rev 1) [!].gb',
        'Tetris',
    ),
    (
        'Super Mario Land (Japan) [S][!].gb',
        'Super Mario Land',
    ),
    (
        "Kirby's Dream Land (USA, Europe) (Rev A) (SGB Enhanced) [!].gb",
        "Kirby's Dream Land",
    ),
    (
        'Final Fantasy Legend, The (USA) (Rev 1) [!].gb',
        'Final Fantasy Legend, The',
    ),
    (
        'Metroid II - Return of Samus (USA, Europe) (Rev A) [!].gb',
        'Metroid II - Return of Samus',
    ),
    (
        'Donkey Kong (World) (Rev A) (SGB Enhanced) [!].gb',
        'Donkey Kong',
    ),
    (
        'Wario Land II (USA, Europe) (SGB Enhanced) [!].gbc',
        'Wario Land II',
    ),
    (
        "Harry Potter and the Sorcerer's Stone (USA).zip",
        "Harry Potter and the Sorcerer's Stone",
    ),
    (
        'Action Force (USA).zip',
        'Action Force',
    ),
    (
        'Game (Europe) (En,Fr,De).gb',
        'Game',
    ),
    (
        'All-Star Baseball 99 (U) [!].gb',
        'All-Star Baseball 99',
    ),
    (
        'Double Dragon (1995)(SNK)(Jp-US)[!].zip',
        'Double Dragon',
    ),
    (
        'Dr. Mario (Japan) (Rev A) [S][!].gb',
        'Dr. Mario',
    ),
    (
        'Asteroids (USA) [b1].gb',
        'Asteroids',
    ),
]

EXTRA_GB_GBC_FIXTURES = [
    ('Pokemon - Blue Version (USA) (Rev A) [!].gb', 'Pokemon - Blue Version'),
    ('Super Mario Land 2 - 6 Golden Coins (USA) (Rev A) [!].gb', 'Super Mario Land 2 - 6 Golden Coins'),
    ('Mega Man V (USA) [!].gb', 'Mega Man V'),
    ('FIFA 98 - Road to World Cup (Europe) (SGB Enhanced) [!].gb', 'FIFA 98 - Road to World Cup'),
    ('4-in-1 Fun Pak (USA) [!].gb', '4-in-1 Fun Pak'),
    ('Some Hack (USA) [h].gb', 'Some Hack'),
]

CROSS_PLATFORM_FIXTURES = [
    ('Super Mario 64 (USA) [!].z64', 'Super Mario 64'),
    ('Chrono Trigger (USA) [!].sfc', 'Chrono Trigger'),
    ('Sonic the Hedgehog (USA) (Rev A) [!].md', 'Sonic the Hedgehog'),
    ('Castlevania - Symphony of the Night (USA) [!].bin', 'Castlevania - Symphony of the Night'),
    ('Metroid Fusion (USA) [!].gba', 'Metroid Fusion'),
]


@pytest.mark.parametrize('raw,expected', GM_FIXTURES)
def test_gm_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


@pytest.mark.parametrize('raw,expected', EXTRA_GB_GBC_FIXTURES + CROSS_PLATFORM_FIXTURES)
def test_extra_console_fixtures(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_transform_trail_stages():
    raw = 'Super Mario Land (Japan) [S][!].gb'
    result = parse_console_rom_label(raw)
    stages = [t['stage'] for t in result['transforms']]
    assert 'B15' in stages
    assert 'B16' in stages
    assert stages.index('B15') < stages.index('B16')
    for i in range(1, len(result['transforms'])):
        assert result['transforms'][i]['before'] == result['transforms'][i - 1]['after']


def test_c12_article_reorder_variants():
    cleaned = parse_console_rom_label('Legend of Zelda, The (USA) [!].gb')['cleaned_name']
    variants = generate_goty_variants(cleaned)
    assert 'The Legend of Zelda' in variants

    ff = parse_console_rom_label('Final Fantasy Legend, The (USA) [!].gb')['cleaned_name']
    assert 'The Final Fantasy Legend' in generate_goty_variants(ff)


def test_rom_language_tags_on_raw_basename():
    raw = 'Game (Europe) (En,Fr,De).gb'
    parsed = parse_rom_language_tags(raw)
    assert parsed['rom_region'] == 'EUR'
    assert 'de' in parsed['languages']

    peel = parse_console_rom_label(raw)
    assert peel['rom_region'] == 'EUR'
    assert peel['rom_languages'] == 'en,fr,de'
    assert peel['cleaned_name'] == 'Game'


def test_normalize_set_title_uses_shared_peel():
    assert normalize_set_title('Balloon Fight (USA) [!].nes') == 'balloon fight'
    assert normalize_set_title('Castlevania (USA) (Rev A)') == 'castlevania'


def test_multicart_propose_only():
    result = parse_console_rom_label('4-in-1 Fun Pak (USA) [!].gb')
    assert result['is_multicart'] is True
    assert result['propose_only'] is True


def test_hack_propose_only():
    result = parse_console_rom_label('Some Hack (USA) [h].gb')
    assert result['propose_only'] is True


def test_proto_propose_only():
    result = parse_console_rom_label('Early Game (Proto) (USA) [!].gb')
    assert result['propose_only'] is True


def test_should_use_console_rom_peel_pilot():
    gb_lib = _Lib(LibraryPlatform.GB)
    pc_lib = _Lib(LibraryPlatform.PCWIN)
    n64_lib = _Lib(LibraryPlatform.N64)
    snes_lib = _Lib(LibraryPlatform.SNES)
    gba_lib = _Lib(LibraryPlatform.GBA)
    nes_lib = _Lib(LibraryPlatform.NES)
    psx_lib = _Lib(LibraryPlatform.PSX)
    md_lib = _Lib(LibraryPlatform.SEGA_MD)
    nds_lib = _Lib(LibraryPlatform.NDS)
    ngc_lib = _Lib(LibraryPlatform.NGC)
    wii_lib = _Lib(LibraryPlatform.WII)
    psp_lib = _Lib(LibraryPlatform.PSP)
    ms_lib = _Lib(LibraryPlatform.SEGA_MS)
    gg_lib = _Lib(LibraryPlatform.SEGA_GG)
    cd_lib = _Lib(LibraryPlatform.SEGA_CD)
    a2600_lib = _Lib(LibraryPlatform.ATARI_2600)
    neogeo_lib = _Lib(LibraryPlatform.NEOGEO)
    arcade_lib = _Lib(LibraryPlatform.ARCADE)
    switch_lib = _Lib(LibraryPlatform.SWITCH)
    files = {'scan_mode': 'files'}
    assert should_use_console_rom_peel(gb_lib, '/roms/tetris.gb', files)
    assert should_use_console_rom_peel(n64_lib, '/roms/mario.z64', files)
    assert should_use_console_rom_peel(snes_lib, '/roms/chrono.sfc', files)
    assert should_use_console_rom_peel(gba_lib, '/roms/fusion.gba', files)
    assert should_use_console_rom_peel(nes_lib, '/roms/zelda.nes', files)
    assert should_use_console_rom_peel(psx_lib, '/roms/sotn.bin', files)
    assert should_use_console_rom_peel(md_lib, '/roms/sonic.md', files)
    # BE-DET-3 P1 files-mode gate
    assert should_use_console_rom_peel(nds_lib, '/roms/mario.nds', files)
    assert should_use_console_rom_peel(ngc_lib, '/roms/sunshine.gcm', files)
    assert should_use_console_rom_peel(wii_lib, '/roms/mk.wbfs', files)
    assert should_use_console_rom_peel(psp_lib, '/roms/game.cso', files)
    assert should_use_console_rom_peel(ms_lib, '/roms/sonic.sms', files)
    assert should_use_console_rom_peel(gg_lib, '/roms/sonic.gg', files)
    assert should_use_console_rom_peel(cd_lib, '/roms/sonic.cue', files)
    assert should_use_console_rom_peel(a2600_lib, '/roms/pac.a26', files)
    assert should_use_console_rom_peel(neogeo_lib, '/roms/mslug.zip', files)
    assert should_use_console_rom_peel(arcade_lib, '/roms/mslug.zip', files)
    assert should_use_console_rom_peel(switch_lib, '/roms/title.nsp', files)
    # BE-DET-7 disc/late gate
    saturn_lib = _Lib(LibraryPlatform.SEGA_SATURN)
    dc_lib = _Lib(LibraryPlatform.SEGA_DC)
    neogeo_cd_lib = _Lib(LibraryPlatform.NEOGEO_CD)
    assert should_use_console_rom_peel(saturn_lib, '/roms/panzer.cue', files)
    assert should_use_console_rom_peel(dc_lib, '/roms/sonic.gdi', files)
    assert should_use_console_rom_peel(neogeo_cd_lib, '/roms/kof.chd', files)
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.PCE), '/roms/bomberman.pce', files
    )
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.SEGA_32X), '/roms/knuckles.32x', files
    )
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.AMIGA), '/roms/lemmings.adf', files
    )
    assert parse_console_rom_label('Bomberman (Japan).pce')['cleaned_name'] == 'Bomberman'
    assert not should_use_console_rom_peel(pc_lib, '/roms/tetris.gb', files)
    # Folders-mode without dump tags stays off (plain / non-dump leaf).
    folders = {'scan_mode': 'folders'}
    assert not should_use_console_rom_peel(gb_lib, '/roms/tetris.gb', folders)
    assert not should_use_console_rom_peel(n64_lib, '/roms/mario.z64', folders)
    assert not should_use_console_rom_peel(nes_lib, '/roms/zelda.nes', folders)
    assert not should_use_console_rom_peel(psx_lib, '/roms/sotn.bin', folders)
    assert not should_use_console_rom_peel(md_lib, '/roms/sonic.md', folders)
    assert not should_use_console_rom_peel(nds_lib, '/roms/mario.nds', folders)
    assert not should_use_console_rom_peel(switch_lib, '/roms/title.nsp', folders)


def test_looks_like_console_rom_dump_label():
    assert looks_like_console_rom_dump_label('Super Mario Bros. (USA)')
    assert looks_like_console_rom_dump_label('Chrono Trigger (USA) [!].sfc')
    assert looks_like_console_rom_dump_label('Double Dragon (1995)(SNK)(Jp-US)[!].zip')
    assert not looks_like_console_rom_dump_label('tetris.gb')
    assert not looks_like_console_rom_dump_label('Plain Title Folder')
    assert not looks_like_console_rom_dump_label('Super Mario Bros')


def test_should_use_console_rom_peel_folders_mode_dump_basename():
    """BE-DET-2 — folders-mode gate when leaf basename looks No-Intro/GoodTools."""
    nes_lib = _Lib(LibraryPlatform.NES)
    snes_lib = _Lib(LibraryPlatform.SNES)
    n64_lib = _Lib(LibraryPlatform.N64)
    gb_lib = _Lib(LibraryPlatform.GB)
    gba_lib = _Lib(LibraryPlatform.GBA)
    psx_lib = _Lib(LibraryPlatform.PSX)
    md_lib = _Lib(LibraryPlatform.SEGA_MD)
    pc_lib = _Lib(LibraryPlatform.PCWIN)
    folders = {'scan_mode': 'folders'}
    dump_leaf = '/roms/Super Mario Bros. (USA)'
    assert should_use_console_rom_peel(nes_lib, dump_leaf, folders)
    assert should_use_console_rom_peel(snes_lib, dump_leaf, folders)
    assert should_use_console_rom_peel(n64_lib, dump_leaf, folders)
    assert should_use_console_rom_peel(gb_lib, dump_leaf, folders)
    assert should_use_console_rom_peel(gba_lib, '/roms/Metroid Fusion (USA) [!]', folders)
    assert should_use_console_rom_peel(psx_lib, '/roms/Castlevania - Symphony of the Night (USA)', folders)
    assert should_use_console_rom_peel(md_lib, '/roms/Sonic the Hedgehog (USA) [!]', folders)
    # PCWIN never uses console peel even with dump-shaped folder names.
    assert not should_use_console_rom_peel(pc_lib, dump_leaf, folders)
    assert not should_use_console_rom_peel(nes_lib, '/roms/Plain Title Folder', folders)


def test_should_use_console_rom_peel_folders_mode_primary_dump(tmp_path):
    """BE-DET-2 — plain folder name still gates when primary dump inside looks dump-tagged."""
    nes_lib = _Lib(LibraryPlatform.NES)
    pc_lib = _Lib(LibraryPlatform.PCWIN)
    leaf = tmp_path / 'Mario'
    leaf.mkdir()
    (leaf / 'Super Mario Bros. (USA).nes').write_bytes(b'ROM')
    folders = {'scan_mode': 'folders'}
    assert should_use_console_rom_peel(nes_lib, str(leaf), folders)
    assert not should_use_console_rom_peel(pc_lib, str(leaf), folders)
    plain = tmp_path / 'Zelda'
    plain.mkdir()
    (plain / 'zelda.nes').write_bytes(b'ROM')
    assert not should_use_console_rom_peel(nes_lib, str(plain), folders)

def test_sequel_numeral_not_peeled():
    result = parse_console_rom_label('Super Mario Land 2 (USA) [!].gb')
    assert '2' in result['cleaned_name']


# --- W22 match slice: N64 + C14 + SNES/GBA gates ---

N64_FIXTURES = [
    (
        'Armorines - Project S.W.A.R.M. (U) [!].z64',
        'Armorines - Project S.W.A.R.M.',
    ),
    ('Super Mario 64 (USA) [!].z64', 'Super Mario 64'),
    (
        'Legend of Zelda, The - Ocarina of Time (USA) (Rev A) [!].z64',
        'Legend of Zelda, The - Ocarina of Time',
    ),
    ('Mario Kart 64 (USA) [!].n64', 'Mario Kart 64'),
    ('GoldenEye 007 (USA) [!].z64', 'GoldenEye 007'),
    ('Banjo-Kazooie (USA) [!].z64', 'Banjo-Kazooie'),
    ('Paper Mario (USA) [!].v64', 'Paper Mario'),
    ('1080 Snowboarding (USA) [!].z64', '1080 Snowboarding'),
]


@pytest.mark.parametrize('raw,expected', N64_FIXTURES)
def test_n64_w22_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_n64_c14_punctuation_light_swarm_variant():
    cleaned = parse_console_rom_label(
        'Armorines - Project S.W.A.R.M. (U) [!].z64'
    )['cleaned_name']
    assert cleaned == 'Armorines - Project S.W.A.R.M.'
    variants = generate_goty_variants(cleaned)
    assert 'Armorines - Project SWARM' in variants
    # Primary cleaned form stays first / present — C14 is additive only.
    assert cleaned in variants


def test_n64_c12_ocarina_article_reorder():
    cleaned = parse_console_rom_label(
        'Legend of Zelda, The - Ocarina of Time (USA) (Rev A) [!].z64'
    )['cleaned_name']
    variants = generate_goty_variants(cleaned)
    assert 'The Legend of Zelda - Ocarina of Time' in variants


def test_n64_multicart_and_hack_propose_only():
    multi = parse_console_rom_label('Multi Game 2-in-1 (USA) [!].z64')
    assert multi['is_multicart'] is True
    assert multi['propose_only'] is True
    hack = parse_console_rom_label('Some Hack (USA) [h].z64')
    assert hack['propose_only'] is True


SNES_GBA_FIXTURES = [
    ('Chrono Trigger (USA) [!].sfc', 'Chrono Trigger'),
    ('Super Metroid (Japan, USA) (En,Ja) [!].sfc', 'Super Metroid'),
    (
        'Legend of Zelda, The - A Link to the Past (USA) [!].sfc',
        'Legend of Zelda, The - A Link to the Past',
    ),
    ('Metroid Fusion (USA) [!].gba', 'Metroid Fusion'),
    (
        'Pokemon - Emerald Version (USA, Europe) [!].gba',
        'Pokemon - Emerald Version',
    ),
    (
        'The Legend of Zelda - The Minish Cap (USA) [!].gba',
        'The Legend of Zelda - The Minish Cap',
    ),
]


@pytest.mark.parametrize('raw,expected', SNES_GBA_FIXTURES)
def test_snes_gba_w22_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_snes_c12_link_to_the_past():
    cleaned = parse_console_rom_label(
        'Legend of Zelda, The - A Link to the Past (USA) [!].sfc'
    )['cleaned_name']
    variants = generate_goty_variants(cleaned)
    assert 'The Legend of Zelda - A Link to the Past' in variants


# --- BE-DET-1: NES · PSX · SEGA_MD files-mode gate + fixtures ---

NES_FIXTURES = [
    ('Balloon Fight (USA) [!].nes', 'Balloon Fight'),
    (
        'Legend of Zelda, The (USA) (Rev A) [!].nes',
        'Legend of Zelda, The',
    ),
    ('Super Mario Bros. (World) [!].nes', 'Super Mario Bros.'),
    ('Metroid (USA) (Rev A) [!].nes', 'Metroid'),
    ('Castlevania (USA) (Rev A) [!].nes', 'Castlevania'),
    ('Dr. Mario (Japan, USA) (Rev A) [!].nes', 'Dr. Mario'),
]

PSX_FIXTURES = [
    (
        'Castlevania - Symphony of the Night (USA) [!].bin',
        'Castlevania - Symphony of the Night',
    ),
    ('Final Fantasy VII (USA) (Disc 1) [!].bin', 'Final Fantasy VII'),
    ('Crash Bandicoot (USA) [!].cue', 'Crash Bandicoot'),
    (
        'Metal Gear Solid (USA) (Disc 1) [!].bin',
        'Metal Gear Solid',
    ),
    ('Spyro the Dragon (USA) [!].bin', 'Spyro the Dragon'),
    ('Tekken 3 (USA) [!].bin', 'Tekken 3'),
]

SEGA_MD_FIXTURES = [
    ('Sonic the Hedgehog (USA) (Rev A) [!].md', 'Sonic the Hedgehog'),
    ('Streets of Rage 2 (USA) [!].md', 'Streets of Rage 2'),
    ('Gunstar Heroes (USA) [!].gen', 'Gunstar Heroes'),
    ('Phantasy Star IV (USA) [!].md', 'Phantasy Star IV'),
    ('Shining Force II (USA) [!].md', 'Shining Force II'),
    ('Altered Beast (USA, Europe) [!].md', 'Altered Beast'),
]


@pytest.mark.parametrize('raw,expected', NES_FIXTURES)
def test_nes_be_det1_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


@pytest.mark.parametrize('raw,expected', PSX_FIXTURES)
def test_psx_be_det1_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


@pytest.mark.parametrize('raw,expected', SEGA_MD_FIXTURES)
def test_sega_md_be_det1_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_nes_c12_zelda_article_reorder():
    cleaned = parse_console_rom_label(
        'Legend of Zelda, The (USA) (Rev A) [!].nes'
    )['cleaned_name']
    variants = generate_goty_variants(cleaned)
    assert 'The Legend of Zelda' in variants


def test_psx_disc_tag_stripped():
    result = parse_console_rom_label('Final Fantasy VII (USA) (Disc 1) [!].bin')
    assert result['cleaned_name'] == 'Final Fantasy VII'
    assert '(Disc' not in result['cleaned_name']
    assert result['disc_index'] == 1


# --- BE-DET-3: P1 gate + ROM_EXT fixtures (files-mode minimum) ---

P1_FIXTURES = [
    # NDS
    ('Mario Kart DS (USA) (Rev 1) [!].nds', 'Mario Kart DS'),
    ('New Super Mario Bros. (USA) [!].nds', 'New Super Mario Bros.'),
    # NGC / Wii
    ('Super Mario Sunshine (USA).gcm', 'Super Mario Sunshine'),
    ('Metroid Prime (USA) [!].iso', 'Metroid Prime'),
    ('Mario Kart Wii (USA) (Rev 1).wbfs', 'Mario Kart Wii'),
    ('Super Mario Galaxy (USA).rvz', 'Super Mario Galaxy'),
    # PSP
    (
        'Crisis Core - Final Fantasy VII (USA).cso',
        'Crisis Core - Final Fantasy VII',
    ),
    ('God of War - Chains of Olympus (USA).iso', 'God of War - Chains of Olympus'),
    ('Lumines (USA).pbp', 'Lumines'),
    # Sega cart / CD (MS · GG · CD; MD already BE-DET-1)
    ('Sonic the Hedgehog (USA) [!].sms', 'Sonic the Hedgehog'),
    ('Sonic the Hedgehog (World) [!].gg', 'Sonic the Hedgehog'),
    ('Sonic CD (USA).cue', 'Sonic CD'),
    ('Lunar - Eternal Blue (USA).chd', 'Lunar - Eternal Blue'),
    # Atari 2600
    ('Pac-Man (USA).a26', 'Pac-Man'),
    ('Pitfall! (USA) [!].a26', 'Pitfall!'),
    # Neo Geo AES / Arcade (zip set basenames)
    ('Metal Slug (World).zip', 'Metal Slug'),
    ('Street Fighter II (World) [!].zip', 'Street Fighter II'),
    # Switch
    ('Celeste (USA).nsp', 'Celeste'),
    ('Hades (USA) [!].xci', 'Hades'),
]


@pytest.mark.parametrize('raw,expected', P1_FIXTURES)
def test_be_det3_p1_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_be_det3_rom_ext_strips_new_forms():
    """B15 strips P1 disc/handheld/Switch extensions from ROM_EXT_RE."""
    cases = [
        ('Title (USA).nds', 'Title'),
        ('Title (USA).gcm', 'Title'),
        ('Title (USA).rvz', 'Title'),
        ('Title (USA).wbfs', 'Title'),
        ('Title (USA).pbp', 'Title'),
        ('Title (USA).cso', 'Title'),
        ('Title (USA).nsp', 'Title'),
        ('Title (USA).xci', 'Title'),
        ('Title (USA).nsz', 'Title'),
        ('Title (USA).xcz', 'Title'),
        ('Title (USA).a26', 'Title'),
        ('Title (USA).cia', 'Title'),
        ('Title (USA).3ds', 'Title'),
        ('Title (Japan).pce', 'Title'),
        ('Title (Japan).sgx', 'Title'),
        ('Title (World).ws', 'Title'),
        ('Title (World).wsc', 'Title'),
        ('Title (World) (En,Ja).ngc', 'Title'),
        ('Title (Japan, Europe) (En,Ja).ngp', 'Title'),
        ('Title (USA).adf', 'Title'),
        ('Title (USA).ssd', 'Title'),
        ('Title (World).mgw', 'Title'),
        ('Title (USA).vb', 'Title'),
    ]
    for raw, expected in cases:
        assert parse_console_rom_label(raw)['cleaned_name'] == expected


def test_be_det3_p1_folders_mode_dump_basename_still_gates():
    """BE-DET-2 dump-shape folders gate remains for newly gated P1 platforms."""
    folders = {'scan_mode': 'folders'}
    dump_leaf = '/roms/Super Mario Sunshine (USA)'
    assert should_use_console_rom_peel(_Lib(LibraryPlatform.NGC), dump_leaf, folders)
    assert should_use_console_rom_peel(_Lib(LibraryPlatform.WII), dump_leaf, folders)
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.NDS), '/roms/Mario Kart DS (USA) [!]', folders
    )
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.SWITCH), '/roms/Celeste (USA)', folders
    )
    assert should_use_console_rom_peel(
        _Lib(LibraryPlatform.ARCADE), '/roms/Metal Slug (World)', folders
    )
    assert not should_use_console_rom_peel(
        _Lib(LibraryPlatform.NGC), '/roms/Plain Title Folder', folders
    )


# --- BE-DET-7: disc/late consoles + Redump fixtures + Switch A1∪B16 ---

BE_DET7_REDUMP_FIXTURES = [
    # NGC / Wii Redump-style region + disc parens (no GoodTools brackets)
    ('Resident Evil (USA) (Disc 1).iso', 'Resident Evil'),
    ('Metroid Prime 2 - Echoes (USA) (En,Fr,Es).iso', 'Metroid Prime 2 - Echoes'),
    ('Super Mario Galaxy (USA) (Disc 1).rvz', 'Super Mario Galaxy'),
    ('Mario Kart Wii (Europe) (En,Fr,De,Es,It).wbfs', 'Mario Kart Wii'),
    # PSP Redump-ish
    (
        'Crisis Core - Final Fantasy VII (USA) (En,Fr,De,Es,It).iso',
        'Crisis Core - Final Fantasy VII',
    ),
    # SEGA_CD already gated; Redump multi-disc
    ('Lunar - Eternal Blue (USA) (Disc 1).cue', 'Lunar - Eternal Blue'),
    ('Sonic CD (USA) (Rev A).chd', 'Sonic CD'),
    # SEGA_SATURN
    ('Panzer Dragoon (USA).cue', 'Panzer Dragoon'),
    ('Panzer Dragoon Saga (USA) (Disc 1).bin', 'Panzer Dragoon Saga'),
    ('NiGHTS into Dreams (USA) (En,Ja).chd', 'NiGHTS Into Dreams'),
    # SEGA_DC (gdi/cdi forms)
    ('Sonic Adventure (USA).gdi', 'Sonic Adventure'),
    ('Crazy Taxi (USA) [!].cdi', 'Crazy Taxi'),
    ('Shenmue (USA) (Disc 1).chd', 'Shenmue'),
    # NEOGEO_CD
    ('Metal Slug (World).chd', 'Metal Slug'),
    ('The King of Fighters 94 (Japan).iso', 'The King of Fighters 94'),
    ('Samurai Shodown (USA) (Disc 1).cue', 'Samurai Shodown'),
]


@pytest.mark.parametrize('raw,expected', BE_DET7_REDUMP_FIXTURES)
def test_be_det7_redump_fixture_cleaned_name(raw, expected):
    result = parse_console_rom_label(raw)
    assert result['cleaned_name'] == expected


def test_be_det7_rom_ext_strips_dreamcast_forms():
    assert parse_console_rom_label('Title (USA).gdi')['cleaned_name'] == 'Title'
    assert parse_console_rom_label('Title (USA).cdi')['cleaned_name'] == 'Title'


def test_be_det7_redump_disc_index_captured():
    result = parse_console_rom_label('Shenmue (USA) (Disc 1).chd')
    assert result['cleaned_name'] == 'Shenmue'
    assert result['disc_index'] == 1


def test_be_det7_late_platforms_files_and_folders_gate():
    files = {'scan_mode': 'files'}
    folders = {'scan_mode': 'folders'}
    dump_leaf = '/roms/Panzer Dragoon (USA)'
    for platform in (
        LibraryPlatform.SEGA_SATURN,
        LibraryPlatform.SEGA_DC,
        LibraryPlatform.NEOGEO_CD,
    ):
        lib = _Lib(platform)
        assert should_use_console_rom_peel(lib, '/roms/title.cue', files)
        assert should_use_console_rom_peel(lib, dump_leaf, folders)
        assert not should_use_console_rom_peel(lib, '/roms/Plain Title Folder', folders)


def test_be_det7_switch_title_dir_scene_peel_a1_b16():
    """SWITCH title dirs: A1 scene/repack ∪ B16 dump brackets."""
    repack = parse_console_rom_label(
        'Celeste [Repack]',
        platform=LibraryPlatform.SWITCH,
    )
    assert repack['cleaned_name'] == 'Celeste'
    reasons = {t['reason'] for t in repack['transforms']}
    assert 'scene_repack_brackets' in reasons

    dump = parse_console_rom_label(
        'Hades (USA) [!]',
        platform=LibraryPlatform.SWITCH,
    )
    assert dump['cleaned_name'] == 'Hades'
    assert any(t['reason'] == 'dump_brackets' for t in dump['transforms'])

    # Household A10 alias (code-only) — hyphen form allows single head token.
    scene = parse_console_rom_label(
        'Celeste-scenegrp',
        platform=LibraryPlatform.SWITCH,
    )
    assert scene['cleaned_name'] == 'Celeste'
    assert any(t['reason'] == 'unbracketed_scene_suffix' for t in scene['transforms'])

    # Non-SWITCH does not apply A1/A10 stages.
    plain = parse_console_rom_label('Celeste-scenegrp')
    assert plain['cleaned_name'] == 'Celeste-scenegrp'


def test_be_det7_switch_folders_gates_on_scene_or_dump():
    """BE-DET-7 — SWITCH folders-mode gates on A1∪B16, not only No-Intro parens."""
    switch_lib = _Lib(LibraryPlatform.SWITCH)
    folders = {'scan_mode': 'folders'}
    assert should_use_console_rom_peel(switch_lib, '/roms/Celeste [Repack]', folders)
    assert should_use_console_rom_peel(switch_lib, '/roms/Celeste-scenegrp', folders)
    assert should_use_console_rom_peel(switch_lib, '/roms/Celeste (USA)', folders)
    assert not should_use_console_rom_peel(switch_lib, '/roms/Plain Title Folder', folders)
    # Other gated platforms still require dump-shape (not bare scene suffix alone).
    assert not should_use_console_rom_peel(
        _Lib(LibraryPlatform.NES), '/roms/Celeste-scenegrp', folders
    )


# --- BE-DET-8: Arcade / Neo Geo AES set normalize + AES≠CD ---

BE_DET8_SET_FOLDER_FIXTURES = [
    # compact set dirs / zip-per-set
    ('mslug', 'mslug', True),
    ('mslug.zip', 'mslug', True),
    ('sf2ce', 'sf2ce', True),
    ('kof94.zip', 'kof94', True),
    ('metal_slug', 'Metal Slug', True),
    # dump-titled arcade — peel tags, not set-basename
    ('Metal Slug (World).zip', 'Metal Slug', False),
    ('Street Fighter II (World) [!].zip', 'Street Fighter II', False),
]


@pytest.mark.parametrize('raw,expected,is_set', BE_DET8_SET_FOLDER_FIXTURES)
def test_be_det8_arcade_set_folder_peel(raw, expected, is_set):
    result = parse_console_rom_label(raw, platform=LibraryPlatform.ARCADE)
    assert result['cleaned_name'] == expected
    assert result['is_arcade_set'] is is_set
    if is_set:
        assert result['propose_only'] is True
        assert any(t['reason'] == 'arcade_set_normalize' for t in result['transforms'])


def test_be_det8_neogeo_aes_set_folder_peel_not_cd():
    """NEOGEO (AES) gets set peel; NEOGEO_CD never treated as set folder."""
    aes = parse_console_rom_label('mslug.zip', platform=LibraryPlatform.NEOGEO)
    assert aes['cleaned_name'] == 'mslug'
    assert aes['is_arcade_set'] is True
    assert aes['propose_only'] is True

    cd = parse_console_rom_label('mslug.zip', platform=LibraryPlatform.NEOGEO_CD)
    assert cd['is_arcade_set'] is False
    # Without dump tags, CD zip still peels ext + title-cases (not set normalize).
    assert cd['cleaned_name'] == 'Mslug'
    assert not any(t['reason'] == 'arcade_set_normalize' for t in cd['transforms'])


def test_be_det8_looks_like_arcade_set_basename():
    assert looks_like_arcade_set_basename('mslug')
    assert looks_like_arcade_set_basename('mslug.zip')
    assert looks_like_arcade_set_basename('sf2ce')
    assert looks_like_arcade_set_basename('/roms/kof94')
    assert not looks_like_arcade_set_basename('Metal Slug (World)')
    assert not looks_like_arcade_set_basename('Plain Title Folder')
    assert not looks_like_arcade_set_basename('mslug (World).zip')


def test_be_det8_folders_gate_set_folder_arcade_and_neogeo():
    """Folders-mode gates on dump-shape OR compact set basename for ARCADE/NEOGEO."""
    folders = {'scan_mode': 'folders'}
    arcade = _Lib(LibraryPlatform.ARCADE)
    neogeo = _Lib(LibraryPlatform.NEOGEO)
    neogeo_cd = _Lib(LibraryPlatform.NEOGEO_CD)
    assert should_use_console_rom_peel(arcade, '/roms/mslug', folders)
    assert should_use_console_rom_peel(neogeo, '/roms/mslug', folders)
    assert should_use_console_rom_peel(arcade, '/roms/Metal Slug (World)', folders)
    # NEOGEO_CD still requires dump-shape for folders (not set basename).
    assert not should_use_console_rom_peel(neogeo_cd, '/roms/mslug', folders)
    assert should_use_console_rom_peel(neogeo_cd, '/roms/Metal Slug (World)', folders)
    # Other platforms still require dump-shape for bare set tokens.
    assert not should_use_console_rom_peel(
        _Lib(LibraryPlatform.NES), '/roms/mslug', folders
    )


def test_be_det8_folders_gate_set_zip_child(tmp_path):
    arcade = _Lib(LibraryPlatform.ARCADE)
    leaf = tmp_path / 'mslug'
    leaf.mkdir()
    (leaf / 'mslug.zip').write_bytes(b'ZIP')
    folders = {'scan_mode': 'folders'}
    assert should_use_console_rom_peel(arcade, str(leaf), folders)


def test_be_det8_propose_first_set_and_large(tmp_path):
    arcade = _Lib(LibraryPlatform.ARCADE)
    arcade.last_scan_folder = None
    arcade.uuid = None
    set_parsed = parse_console_rom_label('mslug', platform=LibraryPlatform.ARCADE)
    assert should_arcade_propose_first(arcade, '/roms/mslug', set_parsed) is True

    dump_parsed = parse_console_rom_label(
        'Metal Slug (World).zip', platform=LibraryPlatform.ARCADE,
    )
    assert dump_parsed['is_arcade_set'] is False
    # Small tree: dump-titled leaf may auto-import (not propose-first).
    assert should_arcade_propose_first(arcade, '/roms/Metal Slug (World)', dump_parsed) is False

    # Large tree under last_scan_folder → propose-first even for dump titles.
    root = tmp_path / 'arcade_roms'
    root.mkdir()
    for i in range(ARCADE_PROPOSE_FIRST_CHILD_THRESHOLD):
        (root / f'set{i:03d}').mkdir()
    arcade.last_scan_folder = str(root)
    assert arcade_library_is_large(arcade, str(root / 'set000')) is True
    assert should_arcade_propose_first(
        arcade, str(root / 'set000' / 'Metal Slug (World)'), dump_parsed,
    ) is True

    # Non-ARCADE never propose-first via this helper.
    assert should_arcade_propose_first(
        _Lib(LibraryPlatform.NEOGEO), '/roms/mslug', set_parsed,
    ) is False


def test_be_det8_tgdb_aes_never_matches_cd():
    """Substring ``neogeo`` ⊂ ``neogeocd`` must not cross-map AES ↔ CD."""
    assert tgdb_platform_matches(['Neo Geo'], 'NEOGEO')
    assert tgdb_platform_matches(['Neo Geo AES'], 'NEOGEO')
    assert not tgdb_platform_matches(['Neo Geo CD'], 'NEOGEO')
    assert not tgdb_platform_matches(['NeoGeo CD'], 'NEOGEO')
    assert tgdb_platform_matches(['Neo Geo CD'], 'NEOGEO_CD')
    assert tgdb_platform_matches(['NeoGeo CD'], 'NEOGEO_CD')
    assert not tgdb_platform_matches(['Neo Geo AES'], 'NEOGEO_CD')
    assert not tgdb_platform_matches(['Neo Geo'], 'NEOGEO_CD')
    assert not tgdb_platform_matches(['Neo Geo Pocket'], 'NEOGEO')

    hits = [
        {'name': 'Metal Slug', 'platforms': ['Neo Geo AES']},
        {'name': 'Metal Slug', 'platforms': ['Neo Geo CD']},
        {'name': 'Metal Slug', 'platforms': ['Arcade']},
    ]
    aes_hits = filter_tgdb_hits_for_platform(hits, 'NEOGEO')
    assert len(aes_hits) == 1
    assert aes_hits[0]['platforms'] == ['Neo Geo AES']
    cd_hits = filter_tgdb_hits_for_platform(hits, 'NEOGEO_CD')
    assert len(cd_hits) == 1
    assert cd_hits[0]['platforms'] == ['Neo Geo CD']

