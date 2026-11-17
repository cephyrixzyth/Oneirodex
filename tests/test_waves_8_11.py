"""Waves 8–11 unit tests (no DB)."""

from oneirodex.utils.acquire_scoring import rank_acquire_hits, score_acquire_hit, title_looks_like_newer_repack
from oneirodex.utils.frontend_export import (
    build_es_de_gamelist,
    build_pegasus_metadata,
    portable_export_path,
)
from oneirodex.utils.plugins import get_plugin, list_plugins


def test_acquire_scoring_ranks_seeders_and_gog():
    hits = [
        {'title': 'Some Game Crack Only', 'seeders': 1, 'size': 1000},
        {'title': 'Some Game GOG Repack', 'seeders': 40, 'size': 4 * 1024 ** 3},
    ]
    ranked = rank_acquire_hits(hits, query='Some Game')
    assert ranked[0]['title'].startswith('Some Game GOG')
    assert ranked[0]['score'] > ranked[1]['score']
    assert score_acquire_hit(hits[1], query='Some Game')['is_repack'] is True


def test_newer_repack_heuristic():
    assert title_looks_like_newer_repack('Game FitGirl Repack', 'Game') is True
    assert title_looks_like_newer_repack('Game', 'Game') is False


def test_portable_export_strips_games_root():
    assert portable_export_path(
        '/storage/nes/game.nes',
        library_roots=['/storage'],
    ) == '<library>/nes/game.nes'


def test_portable_export_windows_home_fallback():
    assert portable_export_path(
        r'C:\Users\alice\roms\a.nes',
        library_roots=['/storage'],
    ) == 'a.nes'


def test_portable_export_preserves_relative():
    assert portable_export_path('./alpha.nes') == './alpha.nes'


def test_esde_and_pegasus_export():
    games = [{'name': 'Alpha', 'path': './alpha.nes', 'uuid': 'u1', 'summary': 'A'}]
    xml = build_es_de_gamelist(games, system='NES')
    assert b'<gameList>' in xml
    assert b'Alpha' in xml
    text = build_pegasus_metadata(games, collection='NES')
    assert 'collection: NES' in text
    assert 'game: Alpha' in text


def test_esde_export_no_absolute_paths():
    games = [{
        'name': 'Mario',
        'full_disk_path': '/mnt/user/infernal-data-streams/_software/_games/nes/Mario.nes',
        'uuid': 'u2',
    }]
    xml = build_es_de_gamelist(
        games,
        system='NES',
        library_roots=['/mnt/user/infernal-data-streams/_software/_games'],
    )
    assert b'/mnt/user' not in xml
    assert b'&lt;library&gt;/nes/Mario.nes' in xml


def test_pegasus_export_no_absolute_paths():
    games = [{
        'name': 'Alan Wake',
        'path': r'Z:\gamez\_a\Alan Wake',
    }]
    text = build_pegasus_metadata(
        games,
        collection='PC',
        library_roots=[r'Z:\gamez'],
    )
    assert 'Z:\\' not in text
    assert 'Z:/' not in text
    assert 'file: <library>/_a/Alan Wake' in text


def test_plugin_registry():
    plugins = list_plugins()
    assert len(plugins) >= 10
    assert get_plugin('emu.webretro')['name'] == 'WebRetro'
    assert get_plugin('missing') is None
