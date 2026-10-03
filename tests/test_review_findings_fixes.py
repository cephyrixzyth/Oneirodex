"""Regression tests for the six issues the code review found."""
import os
from pathlib import Path

import pytest

from oneirodex.utils import disk_rename, path_repoint, secondary_scrapers as ss
from oneirodex.utils.game_name_parse import looks_like_patch_package
from oneirodex.utils.launcher_imports import parse_export


# 1 -- repointing must survive differently-spelled stored paths -------------------

@pytest.mark.parametrize('stored', [
    '/g/_a/Foo', '/g/_a/Foo/', '/g/_a//Foo', '/g/_a/Foo/./',
])
def test_the_folder_itself_is_repointed_however_it_is_spelled(stored):
    assert path_repoint._moved(stored, '/g/_a/Foo', '/g/_a/Bar') == '/g/_a/Bar'


def test_children_keep_their_own_spelling_and_siblings_are_untouched():
    assert path_repoint._moved('/g/_a/Foo/disc1/Game.iso', '/g/_a/Foo/', '/g/_a/Bar') == '/g/_a/Bar/disc1/Game.iso'
    assert path_repoint._moved('/g/_a/Foobar', '/g/_a/Foo', '/g/_a/Bar') is None
    assert path_repoint._moved('/g/_a/Foo_2', '/g/_a/Foo', '/g/_a/Bar') is None


# 2 -- media never follow a root rename that failed ---------------------------------

def test_media_are_not_moved_when_the_game_folder_rename_failed(tmp_path):
    game = tmp_path / '_a' / 'Old Name'
    game.mkdir(parents=True)
    (game / 'cover.jpg').write_bytes(b'x')
    blocker = tmp_path / '_a' / 'New Name'
    blocker.mkdir()                       # destination exists -> root rename is refused
    (blocker / 'keep.txt').write_text('other game')
    plan = [
        {'kind': 'root_folder', 'from_path': str(game), 'to_path': str(blocker)},
        {'kind': 'top_level_media', 'from_path': str(game / 'cover.jpg'), 'to_path': str(blocker / 'cover-new.jpg')},
    ]

    results = disk_rename.apply_rename_plan(plan, [str(tmp_path)])

    assert not results[0]['ok']
    assert 'rename failed' in (results[1]['error'] or '')
    assert (game / 'cover.jpg').exists(), 'the file must stay in the original game folder'
    assert not (blocker / 'cover-new.jpg').exists()


def test_media_still_follow_a_root_rename_that_worked(tmp_path):
    game = tmp_path / '_a' / 'Old'
    game.mkdir(parents=True)
    (game / 'cover.jpg').write_bytes(b'x')
    new = tmp_path / '_a' / 'New'
    plan = [
        {'kind': 'root_folder', 'from_path': str(game), 'to_path': str(new)},
        {'kind': 'top_level_media', 'from_path': str(game / 'cover.jpg'), 'to_path': str(new / 'cover-new.jpg')},
    ]
    results = disk_rename.apply_rename_plan(plan, [str(tmp_path)])
    assert [r['ok'] for r in results] == [True, True]
    assert (new / 'cover-new.jpg').exists()


# 3 -- a bundled "+ Update N" is a game, not a patch --------------------------------

@pytest.mark.parametrize('name', [
    'Game + Update 3', 'Game & Update 2', 'Game with Update 1', 'Game plus Update 4',
    'Metro 2033 Redux Update 1', 'Patch Quest 2', 'Hades Update',
])
def test_bundled_or_ambiguous_update_words_are_not_patch_packages(name):
    assert not looks_like_patch_package(name)


@pytest.mark.parametrize('name', [
    'Beast of Reincarnation update 1.0.7.0 - 1.0.8.0', 'Grim Dawn Update_from_v1.3.0.0_to_v1.3.0.3-ElAmigos',
    'Sengoku Dynasty Update v1.2.3.0', 'L Records Blooma Rag Update 1 02.119782',
])
def test_version_shaped_updates_still_are(name):
    assert looks_like_patch_package(name)


# 4 -- duplicate-named Steam entries narrow before giving up ------------------------

class _Resp:
    def __init__(self, body):
        self._body, self.content = body, b'x'

    def json(self):
        return self._body


def _steam(monkeypatch, items):
    data = {'short_description': 's', 'genres': [{'description': 'RPG'}], 'developers': ['Dev'],
            'publishers': ['Pub'], 'categories': [], 'release_date': {'date': '1 Jan, 2020'}, 'header_image': 'h'}

    def fake(url, **kw):
        if 'storesearch' in url:
            return _Resp({'items': items})
        return _Resp({str(i['id']): {'data': data} for i in items})

    monkeypatch.setattr(ss, 'request_with_backoff', fake)


def test_a_demo_with_the_same_title_does_not_cost_the_game_its_enrichment(monkeypatch):
    _steam(monkeypatch, [{'id': 1, 'name': 'Redout', 'type': 'demo'}, {'id': 2, 'name': 'Redout', 'type': 'app'}])
    assert ss.fetch_steam_data('Redout')['steam_app_id'] == 2


def test_the_literally_spelled_title_wins_over_a_punctuation_variant(monkeypatch):
    _steam(monkeypatch, [{'id': 1, 'name': 'Half-Life 2', 'type': 'app'}, {'id': 2, 'name': 'Half Life 2', 'type': 'app'}])
    assert ss.fetch_steam_data('Half Life 2')['steam_app_id'] == 2


def test_truly_indistinguishable_duplicates_still_refuse(monkeypatch):
    _steam(monkeypatch, [{'id': 1, 'name': 'Redout', 'type': 'app'}, {'id': 2, 'name': 'Redout', 'type': 'app'}])
    assert ss.fetch_steam_data('Redout') is None


# 5 -- Playnite: PluginId is shared by a whole plugin, never a game id ---------------

def test_playnite_games_from_one_plugin_are_not_collapsed():
    export = [
        {'Name': 'Portal', 'PluginId': 'cb91dfc9-b977-43bf-8e70-55f46e410fab'},
        {'Name': 'Half-Life', 'PluginId': 'cb91dfc9-b977-43bf-8e70-55f46e410fab'},
    ]
    _fmt, titles = parse_export(export, launcher='playnite')
    assert {t.name for t in titles} == {'Portal', 'Half-Life'}
    assert len({t.external_id for t in titles}) == 2


# 6 -- bulk enrichment must not sit in Steam's backoff -------------------------------

def test_the_fast_steam_fetch_makes_one_attempt_and_never_sleeps(monkeypatch):
    from oneirodex.utils import steam_lookup

    calls, sleeps = [], []

    class Throttled:
        status_code, headers = 429, {'Retry-After': '30'}

        def json(self):
            return {}

    monkeypatch.setattr(steam_lookup.requests, 'get', lambda url, **kw: (calls.append(kw), Throttled())[1])
    monkeypatch.setattr(steam_lookup.time, 'sleep', lambda s: sleeps.append(s))

    assert steam_lookup.fetch_steam_app_details(123, fast=True) is None
    assert len(calls) == 1 and sleeps == []
    assert calls[0]['timeout'] <= 5.0


def test_a_complete_game_makes_no_steam_call_during_enrichment(monkeypatch):
    from types import SimpleNamespace
    from oneirodex.utils.services import game_enrich

    game = SimpleNamespace(summary='s', genres=['RPG'], developer_id=1, publisher_id=2,
                           first_release_date=object(), steam_app_id=620)
    assert not game_enrich._game_steam_fields_missing(game)
    game.publisher_id = None
    assert game_enrich._game_steam_fields_missing(game)
