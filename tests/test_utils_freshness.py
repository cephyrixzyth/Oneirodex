"""Unit tests for Oneirodex freshness (local vs store) helpers."""

from types import SimpleNamespace

from flask import Flask

from oneirodex.utils.freshness.compare import compare_freshness, parse_version_tuple
from oneirodex.utils.freshness.ids import resolve_steam_app_id
from oneirodex.utils.freshness.local import detect_local_facts


def test_parse_version_tuple():
    assert parse_version_tuple('v1.2.3') == (1, 2, 3)
    assert parse_version_tuple('Build 10') == (10,)
    assert parse_version_tuple(None) is None


def test_detect_local_from_folder_name():
    game = SimpleNamespace(
        name='Some Game',
        full_disk_path=r'Z:\_software\_games\_pc\_h\Hades v1.0.38251 +5 DLCs',
        nfo_content=None,
        updates=[],
        extras=[],
    )
    facts = detect_local_facts(game)
    assert facts['version'] == '1.0.38251'
    assert facts['dlc_count_hint'] == 5
    assert facts['source'] == 'folder_name'


def test_detect_local_from_nfo_when_name_clean():
    game = SimpleNamespace(
        name='Hades',
        full_disk_path=r'E:\games\Hades',
        nfo_content='Release v1.9.23494.3 with extras',
        updates=[],
        extras=[],
    )
    facts = detect_local_facts(game)
    assert facts['version'] == '1.9.23494.3'
    assert facts['source'] == 'nfo'


def test_detect_local_facts_accepts_explicit_app_for_path_allowlisting(tmp_path):
    allowed = tmp_path / 'games'
    inside = allowed / 'Title'
    outside = tmp_path / 'outside'
    inside.mkdir(parents=True)
    outside.mkdir()
    (inside / 'version.txt').write_text('v1.2.3', encoding='utf-8')
    (outside / 'version.txt').write_text('v9.9.9', encoding='utf-8')
    app = Flask(__name__)
    app.config.update(DATA_FOLDER_GAMES=str(allowed))
    game = lambda path: SimpleNamespace(
        name='Title', full_disk_path=str(path), nfo_content=None, updates=[], extras=[],
    )

    accepted = detect_local_facts(game(inside), app=app)
    rejected = detect_local_facts(game(outside), app=app)

    assert accepted['version'] == '1.2.3'
    assert accepted['source'] == 'version_file'
    assert rejected['version'] is None
    assert rejected['source'] is None


def test_resolve_steam_app_id_from_url():
    game = SimpleNamespace(
        steam_app_id=None,
        steam_url='https://store.steampowered.com/app/1145360/Hades/',
        urls=[],
        full_disk_path='',
        name='Hades',
    )
    assert resolve_steam_app_id(game) == 1145360


def test_compare_semantic_behind():
    local = {'version': '1.0.0', 'folder_mtime': None, 'dlc_count_hint': None, 'update_hints': []}
    remotes = [{
        'store': 'gog',
        'ok': True,
        'version': '1.2.0',
        'dlc_count': 0,
        'dlc_titles': [],
    }]
    result = compare_freshness(local, remotes)
    assert result['status'] == 'behind'
    assert result['confidence'] == 'high'


def test_compare_heuristic_news():
    local = {
        'version': None,
        'folder_mtime': '2020-01-01T00:00:00+00:00',
        'dlc_count_hint': None,
        'update_hints': [],
    }
    remotes = [{
        'store': 'steam',
        'ok': True,
        'version': '1 Jan, 2019',
        'release_date': '1 Jan, 2019',
        'last_news_date': '2024-06-01T00:00:00+00:00',
        'dlc_count': 2,
        'dlc_ids': [1, 2],
    }]
    result = compare_freshness(local, remotes)
    assert result['status'] == 'heuristic_behind'
    assert result['confidence'] == 'low'
