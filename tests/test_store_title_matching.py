"""Store title matching and what built-in stores hand back.

From a real scan export: ~300 PC folders stayed Unmatched although the games are
on Steam/GOG, because Stage D compared plain casefolded text ("Assassins Creed
Rogue" != "Assassin's Creed Rogue"), and `fetch_steam_data` attached whatever the
*first* Steam hit was when nothing matched exactly.

The store payload shapes below are written to the documented/observed structure
of each endpoint; they were not captured live from this sandbox.
"""
from types import SimpleNamespace

import pytest

from oneirodex.utils import secondary_scrapers as ss
from oneirodex.utils.software_identify import exact_title_hits
from oneirodex.utils.software_identify_store import title_match_key


@pytest.mark.parametrize('folder, store', [
    ('Assassins Creed Rogue', "Assassin's Creed Rogue"),
    ('Star Wars Knights of the Old Republic', 'STAR WARS™ - Knights of the Old Republic™'),
    ('Death Horizon Cyberfusion', 'Death Horizon: Cyberfusion'),
    ('Witcher 3 Wild Hunt', 'The Witcher 3: Wild Hunt'),
    ('Tomb Raider', 'Tomb Raider®'),
    ('Pokemon Quest', 'Pokémon Quest'),
    ('Redout', 'REDOUT'),
    ('Tom Clancys Splinter Cell', 'Tom Clancy’s Splinter Cell'),
    ('Dungeons and Dragons Dark Alliance', 'Dungeons & Dragons: Dark Alliance'),
])
def test_the_same_title_printed_differently_matches(folder, store):
    assert title_match_key(folder) == title_match_key(store)


@pytest.mark.parametrize('folder, store', [
    ("Baldur's Gate 2", "Baldur's Gate"),
    ('Alan Wake 2', 'Alan Wake'),
    ('Arizona Sunshine 2', 'Arizona Sunshine'),
    ('Hades', 'Hades II'),
    ('Redout', 'REDOUT: Lightspeed Edition'),
])
def test_sequels_and_editions_are_not_the_same_title(folder, store):
    assert title_match_key(folder) != title_match_key(store)


def test_exact_hits_use_the_normalised_key_and_stay_unique():
    hits = [{'name': "Assassin's Creed Rogue"}, {'name': "Assassin's Creed Rogue Remastered"}]
    assert exact_title_hits('Assassins Creed Rogue', hits) == [hits[0]]
    twice = [{'name': 'Redout'}, {'name': 'REDOUT'}]
    assert len(exact_title_hits('redout', twice)) == 2  # ambiguous stays ambiguous


class _Resp:
    def __init__(self, body):
        self._body = body
        self.content = b'x'

    def json(self):
        return self._body


def _steam(monkeypatch, items, app_data=None):
    def fake(url, **kw):
        if 'storesearch' in url:
            return _Resp({'items': items})
        return _Resp({'1': {'data': app_data or {}}, '2': {'data': app_data or {}}})

    monkeypatch.setattr(ss, 'request_with_backoff', fake)


def test_steam_enrichment_never_falls_back_to_the_first_hit(monkeypatch):
    _steam(monkeypatch, [{'id': 1, 'name': "Baldur's Gate: Dark Alliance"}], {'name': 'wrong game'})
    assert ss.fetch_steam_data("Baldur's Gate 2") is None


def test_steam_enrichment_matches_a_punctuation_variant(monkeypatch):
    data = {'short_description': 'x', 'genres': [{'description': 'RPG'}], 'developers': ['Obsidian'],
            'publishers': ['Obsidian'], 'categories': [], 'release_date': {'date': '1 Jan, 2018'},
            'header_image': 'h.jpg'}
    _steam(monkeypatch, [{'id': 2, 'name': "Assassin's Creed Rogue"}, {'id': 3, 'name': 'Other'}], data)
    found = ss.fetch_steam_data('Assassins Creed Rogue')
    assert found and found['steam_app_id'] == 2 and found['developer'] == 'Obsidian'


def test_steam_enrichment_refuses_an_ambiguous_title(monkeypatch):
    _steam(monkeypatch, [{'id': 1, 'name': 'Redout'}, {'id': 2, 'name': 'REDOUT'}], {'name': 'x'})
    assert ss.fetch_steam_data('Redout') is None


def test_gog_hits_keep_developer_publisher_and_genre(monkeypatch):
    body = {'products': [{'id': 1, 'title': 'Gothic 3', 'slug': 'gothic_3', 'image': '//i/g3',
                          'developer': 'Piranha Bytes', 'publisher': 'JoWooD', 'category': 'Role-playing',
                          'releaseDate': 1163376000}]}
    monkeypatch.setattr(ss, 'request_with_backoff', lambda url, **kw: _Resp(body))
    hit = ss.search_gog_games('Gothic 3')[0]
    assert hit['developer'] == 'Piranha Bytes' and hit['publisher'] == 'JoWooD'
    assert hit['genres'] == ['Role-playing'] and hit['release_date'] == '2006-11-13'


def test_gog_hit_without_those_fields_has_no_empty_keys(monkeypatch):
    body = {'products': [{'id': 1, 'title': 'Bare', 'slug': 'bare'}]}
    monkeypatch.setattr(ss, 'request_with_backoff', lambda url, **kw: _Resp(body))
    hit = ss.search_gog_games('Bare')[0]
    assert not {'developer', 'publisher', 'genres', 'release_date'} & set(hit)


def test_epic_hits_read_custom_attributes(monkeypatch):
    body = {'elements': [{'id': 'o1', 'title': 'Alan Wake', 'urlSlug': 'alan-wake',
                          'customAttributes': [{'key': 'developerName', 'value': 'Remedy'},
                                               {'key': 'publisherName', 'value': 'Epic Games'}],
                          'releaseDate': '2012-02-16T00:00:00.000Z'}]}
    monkeypatch.setattr(ss, 'request_with_backoff', lambda url, **kw: _Resp(body))
    hit = ss.search_epic_games('Alan Wake')[0]
    assert (hit['developer'], hit['publisher'], hit['release_date']) == ('Remedy', 'Epic Games', '2012-02-16')


def test_itch_hits_read_the_author_and_genre(monkeypatch):
    body = {'games': [{'id': 9, 'title': 'Tiny Game', 'url': 'https://a.itch.io/tiny',
                       'user': {'display_name': 'A Dev'}, 'genre': 'Platformer'}]}
    monkeypatch.setattr(ss, 'request_with_backoff', lambda url, **kw: _Resp(body))
    hit = ss.search_itch_games('Tiny Game')[0]
    assert hit['developer'] == 'A Dev' and hit['genres'] == ['Platformer']


def test_store_hits_now_satisfy_the_cascade_core_fields():
    from oneirodex.utils.metadata_cascade import hit_to_metadata

    meta = hit_to_metadata({'summary': 's', 'genres': ['RPG'], 'developer': 'Dev', 'publisher': 'Pub'})
    assert not ss.missing_core_fields(meta)
