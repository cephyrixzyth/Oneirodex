"""Scans find Quest-only games on the Meta store and fix their own wrong matches.

From the 2026-11-26 scan review: "Golden Gloves Boxing VR" is only on the Meta
Quest store (as "Golden Gloves"), and folders matched to the wrong title
("Star Trek Deep Space Nine Dominion Wars" → "Star Trek: Armada") stayed wrong
because rescans skip folders already in the library. Both must be automatic: no
folder tags, no manual re-identify.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.utils.meta_store import parse_meta_store_page
from oneirodex.utils.meta_store_search import (
    parse_brave_results,
    parse_site_search_response,
    reset_search_state,
    search_meta_site,
    search_meta_store,
)
from oneirodex.utils.software_identify import (
    match_meta_store_hits,
    meta_search_forms,
    meta_tail_corroborated,
    resolve_meta_store_search_candidate,
)

@pytest.fixture(autouse=True)
def _fresh_search_state():
    """Breaker counts and cached answers are module state; keep tests apart."""
    reset_search_state()
    yield
    reset_search_state()


FIXTURE = Path(__file__).parent / 'fixtures' / 'meta_store_golden_gloves.html'
GOLDEN_GLOVES_ID = '5682829115084320'


def _golden_gloves_details():
    return parse_meta_store_page(FIXTURE.read_text(), app_id=GOLDEN_GLOVES_ID)


def _hit(app_id, name):
    return {'source': 'meta_quest', 'id': app_id, 'meta_quest_id': app_id, 'name': name,
            'url': f'https://www.meta.com/experiences/{app_id}/'}


SEARCH_HITS = [
    _hit(GOLDEN_GLOVES_ID, 'Golden Gloves'),
    _hit('3008315795852749', 'The Thrill of the Fight'),
    _hit('30865511726397301', 'Creed: Rise to Glory'),
]


# --- Meta store search responses ---------------------------------------------

def _site_response(nodes):
    return 'for (;;);' + json.dumps({'data': {'response': {
        'search_session_id': 'x', 'search_results': {'nodes': nodes},
    }}}) + '\r\n{"label":"stream"}'


def test_parse_site_search_response_keeps_apps_only():
    text = _site_response([
        {'__typename': 'XFBDollySearchResultAppItem', 'id': GOLDEN_GLOVES_ID, 'type': 'OCULUS_APP',
         'title': 'Golden Gloves', 'uri': f'https://www.meta.com/experiences/{GOLDEN_GLOVES_ID}/',
         'image_transcoded': {'uri': 'https://cdn.example/gg.png'},
         'quality_rating_aggregate': 4.2, 'quality_rating_count': 220},
        {'id': '123', 'type': 'PRODUCT', 'title': 'Quest 3'},
        {'id': 'not-an-id', 'type': 'OCULUS_APP', 'title': 'Broken'},
    ])
    hits = parse_site_search_response(text)
    assert [h['name'] for h in hits] == ['Golden Gloves']
    assert hits[0]['meta_quest_id'] == GOLDEN_GLOVES_ID
    assert hits[0]['cover_url'] == 'https://cdn.example/gg.png'
    assert hits[0]['rating'] == 84.0 and hits[0]['rating_count'] == 220


@pytest.mark.parametrize('text', ['', 'not json', '{"errors":[{"message":"x"}]}'])
def test_parse_site_search_response_unreadable_is_none(text):
    assert parse_site_search_response(text) is None


def test_parse_brave_results_reads_store_ids_in_rank_order():
    payload = {'web': {'results': [
        {'url': f'https://www.meta.com/experiences/golden-gloves/{GOLDEN_GLOVES_ID}/', 'title': 'Golden Gloves'},
        {'url': 'https://www.meta.com/blog/some-post/'},
        {'url': f'https://www.meta.com/en-gb/experiences/{GOLDEN_GLOVES_ID}/'},
        {'url': 'https://www.oculus.com/experiences/quest/3008315795852749/'},
    ]}}
    assert parse_brave_results(payload) == [GOLDEN_GLOVES_ID, '3008315795852749']


def test_search_falls_back_to_brave_when_meta_search_fails(app):
    brave_hits = [dict(SEARCH_HITS[0], details=_golden_gloves_details())]
    with patch('oneirodex.utils.meta_store_search._live_search_allowed', return_value=True), \
            patch('oneirodex.utils.meta_store_search.search_meta_site', return_value=None) as site, \
            patch('oneirodex.utils.meta_store_search.search_meta_via_brave', return_value=brave_hits) as brave:
        assert search_meta_store('golden gloves boxing') == brave_hits
    site.assert_called_once()
    brave.assert_called_once()


def test_search_uses_meta_first(app):
    with patch('oneirodex.utils.meta_store_search._live_search_allowed', return_value=True), \
            patch('oneirodex.utils.meta_store_search.search_meta_site', return_value=SEARCH_HITS), \
            patch('oneirodex.utils.meta_store_search.search_meta_via_brave') as brave:
        assert search_meta_store('golden gloves') == SEARCH_HITS
    brave.assert_not_called()


def test_search_stays_offline_in_tests(app):
    with patch('oneirodex.utils.meta_store_search.search_meta_site') as site:
        assert search_meta_store('golden gloves') == []
    site.assert_not_called()


def test_search_answers_are_cached_for_the_scan(app):
    with patch('oneirodex.utils.meta_store_search._live_search_allowed', return_value=True), \
            patch('oneirodex.utils.meta_store_search.search_meta_site', return_value=SEARCH_HITS) as site:
        assert search_meta_store('Golden Gloves') == SEARCH_HITS
        assert search_meta_store('golden gloves') == SEARCH_HITS
    site.assert_called_once()


def test_failed_search_is_not_cached(app):
    with patch('oneirodex.utils.meta_store_search._live_search_allowed', return_value=True), \
            patch('oneirodex.utils.meta_store_search.search_meta_site', return_value=None) as site, \
            patch('oneirodex.utils.meta_store_search.search_meta_via_brave', return_value=None):
        assert search_meta_store('golden gloves') == []
        assert search_meta_store('golden gloves') == []
    assert site.call_count == 2


def test_meta_site_search_pauses_after_repeated_failures(app, monkeypatch):
    """A changed Meta endpoint must not cost every folder of every scan."""
    from oneirodex.utils import meta_store_search as mss

    monkeypatch.setattr(mss, '_site_token', lambda refresh=False: 'tok')
    posts = []
    monkeypatch.setattr(mss, '_post_site_search', lambda q, limit, token: posts.append(q))
    clock = [1000.0]
    monkeypatch.setattr(mss.time, 'monotonic', lambda: clock[0])

    for _ in range(mss.BREAKER_FAILURES):
        assert search_meta_site('x') is None
    calls = len(posts)
    assert search_meta_site('x') is None
    assert len(posts) == calls  # breaker open: not asked

    clock[0] += mss.BREAKER_COOLDOWN_SEC + 1
    assert search_meta_site('x') is None
    assert len(posts) > calls  # one retry after the cool-down
    calls = len(posts)
    assert search_meta_site('x') is None
    assert len(posts) == calls  # that retry failed: open again


def test_meta_site_search_success_resets_the_breaker(app, monkeypatch):
    from oneirodex.utils import meta_store_search as mss

    monkeypatch.setattr(mss, '_site_token', lambda refresh=False: 'tok')
    # Two failed searches (each: a post, a token refresh, a second post)...
    answers = iter([None, None, None, None, SEARCH_HITS])
    monkeypatch.setattr(mss, '_post_site_search', lambda q, limit, token: next(answers))
    assert search_meta_site('x') is None
    assert search_meta_site('x') is None
    # ...then one that works clears the count.
    assert search_meta_site('x') == SEARCH_HITS
    assert not mss._breaker_open('meta_site')


# --- scoring Meta hits like the other stores ---------------------------------

def test_meta_forms_drop_the_vr_suffix():
    assert meta_search_forms(['Golden Gloves Boxing VR']) == ['Golden Gloves Boxing VR', 'Golden Gloves Boxing']
    assert meta_search_forms(['SuperhotVR']) == ['SuperhotVR', 'Superhot']


def test_exact_title_wins():
    hit, mode, tail = match_meta_store_hits(['Golden Gloves VR'], SEARCH_HITS)
    assert hit['id'] == GOLDEN_GLOVES_ID and mode == 'exact_title' and tail == []


def test_store_title_plus_a_folder_word_is_a_prefix_match():
    hit, mode, tail = match_meta_store_hits(['Golden Gloves Boxing VR'], SEARCH_HITS)
    assert hit['id'] == GOLDEN_GLOVES_ID
    assert mode == 'title_prefix'
    assert tail == ['boxing']


@pytest.mark.parametrize('folder', [
    'Golden Gloves 2',                     # a sequel number is a different product
    'Golden Gloves Remastered',            # an edition word too
    'Golden Gloves Boxing Champions League',  # too many extra words
    'Gloves',                              # shorter than the store title
])
def test_prefix_rule_refuses(folder):
    assert match_meta_store_hits([folder], SEARCH_HITS) is None


def test_one_word_store_title_is_never_a_prefix_match():
    hits = [_hit('111111111111111', 'Golden')]
    assert match_meta_store_hits(['Golden Gloves'], hits) is None


def test_prefix_hit_must_rank_near_the_top():
    hits = [_hit(str(10**15 + i), f'Other Game {i}') for i in range(3)] + [SEARCH_HITS[0]]
    assert match_meta_store_hits(['Golden Gloves Boxing'], hits) is None


def test_two_exact_hits_mean_a_person_decides():
    hits = [_hit('111111111111111', 'Golden Gloves'), _hit('222222222222222', 'Golden Gloves')]
    assert match_meta_store_hits(['Golden Gloves'], hits) is None


def test_tail_words_must_be_on_the_store_page():
    details = _golden_gloves_details()
    assert meta_tail_corroborated(['boxing'], details)
    assert not meta_tail_corroborated(['racing'], details)


def test_resolve_meta_search_candidate(app):
    details = _golden_gloves_details()
    with patch('oneirodex.utils.meta_store_search.search_meta_store', return_value=SEARCH_HITS) as search, \
            patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details):
        candidate = resolve_meta_store_search_candidate(['Golden Gloves Boxing VR'])
    assert search.call_args[0][0] == 'Golden Gloves Boxing'
    assert candidate['name'] == 'Golden Gloves'
    assert candidate['source'] == 'meta_quest'
    assert candidate['match_mode'] == 'meta_search_title_prefix'


def test_resolve_meta_search_refuses_an_uncorroborated_tail(app):
    details = dict(_golden_gloves_details(), summary='A rhythm game.', genres=['Music'])
    with patch('oneirodex.utils.meta_store_search.search_meta_store', return_value=SEARCH_HITS), \
            patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details):
        assert resolve_meta_store_search_candidate(['Golden Gloves Boxing VR']) is None


# --- scan: Quest-only game found with no folder tag --------------------------

_SETTINGS = {
    'use_local_metadata': False,
    'write_local_metadata': False,
    'use_local_images': False,
    'local_metadata_filename': 'oneirodex.json',
    'propose_only_scan': False,
}


@pytest.fixture
def pc_library(db_session):
    from oneirodex.models import Library
    from oneirodex.platform import LibraryPlatform

    lib = Library(name=f'Meta_Lib_{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    return lib


@pytest.mark.integration
def test_scan_finds_a_quest_only_game_on_the_meta_store(app, db_session, pc_library, tmp_path):
    from oneirodex.models import GameURL
    from oneirodex.utils.game_core import retrieve_and_save_game
    from oneirodex.utils.software_identify import CUSTOM_IGDB_BASE

    details = _golden_gloves_details()
    path = tmp_path / 'Golden Gloves Boxing VR'
    path.mkdir()
    flat_igdb = {'id': 4242, 'name': 'Golden Gloves', 'platforms': [{'name': 'Amiga'}]}

    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', return_value=[dict(flat_igdb)]), \
            patch('oneirodex.utils.meta_store_search.search_meta_store', return_value=SEARCH_HITS) as meta, \
            patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details), \
            patch('oneirodex.utils.services.scan_identify.notify_admins_new_game'), \
            patch('oneirodex.utils.software_identify.search_steam_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_gog_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_epic_games', return_value=[]), \
            patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates', return_value=0):
        result = retrieve_and_save_game(
            'Golden Gloves Boxing', str(path),
            library_uuid=pc_library.uuid, settings=dict(_SETTINGS),
        )

    assert result is not None
    # The flat Amiga "Golden Gloves" on IGDB is not the Quest game.
    assert result.igdb_id >= CUSTOM_IGDB_BASE
    assert result.name == 'Golden Gloves'
    assert meta.call_count == 1  # searched once, not again in Stage D
    urls = db_session.query(GameURL).filter_by(game_uuid=result.uuid, url_type='meta_quest').all()
    assert [u.url for u in urls] == [details['url']]


# --- match audit: wrong matches fixed on rescan ------------------------------

from oneirodex.utils.match_audit import (  # noqa: E402
    audit_library_matches,
    match_disagreement,
)


def _game(db_session, library, *, name, igdb_id, path, **extra):
    from oneirodex.models import Game

    game = Game(
        name=name, igdb_id=igdb_id, full_disk_path=path, library_uuid=library.uuid,
        slug=f'slug-{uuid4().hex[:10]}', **extra,
    )
    db_session.add(game)
    db_session.flush()
    return game


def test_disagreement_is_local_and_skips_locked_and_recent():
    def game(name, path, **kw):
        return SimpleNamespace(name=name, full_disk_path=path, match_locked=kw.get('locked', False),
                               match_checked_at=kw.get('checked'))

    assert match_disagreement(game('Star Trek: Armada', '/pc/Star Trek Deep Space Nine Dominion Wars'))
    assert match_disagreement(game('Star Wars', '/pc/Star Wars Battle for Naboo'))
    assert match_disagreement(game('Half-Life 2', '/pc/Half-Life 2')) is None
    assert match_disagreement(game('Star Trek: Armada', '/pc/Star Trek DS9', locked=True)) is None
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    assert match_disagreement(game('Star Wars', '/pc/Star Wars Battle for Naboo', checked=recent)) is None
    old = datetime.now(timezone.utc) - timedelta(days=45)
    assert match_disagreement(game('Star Wars', '/pc/Star Wars Battle for Naboo', checked=old))


DS9 = {'id': 1597, 'name': 'Star Trek: Deep Space Nine - Dominion Wars', 'slug': 'ds9-dominion-wars',
       'summary': 'Dominion War fleet battles.', 'platforms': [{'name': 'PC (Microsoft Windows)'}],
       'genres': [{'name': 'Strategy'}], 'first_release_date': 999302400}


@pytest.mark.integration
def test_rescan_rematches_a_wrong_igdb_match_in_place(app, db_session, pc_library):
    from oneirodex.models import UnmatchedFolder

    wrong = _game(db_session, pc_library, name='Star Trek: Armada', igdb_id=18902,
                  path='/pc/_s/Star Trek Deep Space Nine Dominion Wars')
    wrong_uuid = wrong.uuid
    dup = UnmatchedFolder(folder_path='/pc/_s/Star Trek Armada', library_uuid=pc_library.uuid,
                          status='Duplicate', matched_game_uuid=wrong_uuid)
    db_session.add(dup)
    db_session.flush()

    def igdb(name, platform_id, limit=10, **kwargs):
        return [dict(DS9)] if 'deep space' in name.lower() else []

    released = []
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', side_effect=igdb), \
            patch('oneirodex.utils.services.scan_identify.enumerate_companies'):
        changes = audit_library_matches(
            [wrong], pc_library, on_rematched=lambda change: released.extend(change['released']),
        )

    assert [(c['old'], c['new']) for c in changes] == [
        ('Star Trek: Armada', 'Star Trek: Deep Space Nine - Dominion Wars'),
    ]
    assert wrong.uuid == wrong_uuid  # same row: favourites and play state stay attached
    assert wrong.igdb_id == 1597
    assert {g.name for g in wrong.genres} == {'Strategy'}
    assert wrong.match_checked_at is not None
    # The folder that was a "duplicate" of the wrong title is free to be identified.
    assert released == ['/pc/_s/Star Trek Armada']
    assert db_session.query(UnmatchedFolder).filter_by(matched_game_uuid=wrong_uuid).count() == 0


@pytest.mark.integration
def test_rescan_keeps_a_match_nothing_fits_better(app, db_session, pc_library):
    game = _game(db_session, pc_library, name='Grand Theft Auto V', igdb_id=1020, path='/pc/_g/GTA V')
    gta = {'id': 1020, 'name': 'Grand Theft Auto V', 'platforms': [{'name': 'PC (Microsoft Windows)'}]}
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', return_value=[gta]), \
            patch('oneirodex.utils.software_identify.resolve_stage_d_store_candidate', return_value=None):
        assert audit_library_matches([game], pc_library) == []
    assert game.igdb_id == 1020 and game.name == 'Grand Theft Auto V'
    assert game.match_checked_at is not None


@pytest.mark.integration
def test_igdb_outage_does_not_mark_games_checked(app, db_session, pc_library):
    """Nothing was searched, so the next scan must try again."""
    from oneirodex.utils.clients.igdb import IgdbUnavailable

    game = _game(db_session, pc_library, name='Star Trek: Armada', igdb_id=1100,
                 path='/pc/_g/Star Trek Deep Space Nine Dominion Wars')
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game',
               side_effect=IgdbUnavailable('down')):
        assert audit_library_matches([game], pc_library) == []
    assert game.match_checked_at is None
    assert game.name == 'Star Trek: Armada'


@pytest.mark.integration
def test_store_lookup_error_does_not_mark_games_checked(app, db_session, pc_library):
    game = _game(db_session, pc_library, name='Star Trek: Armada', igdb_id=1101,
                 path='/pc/_g/Star Trek Deep Space Nine Dominion Wars')
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', return_value=[]), \
            patch('oneirodex.utils.software_identify.resolve_stage_d_store_candidate',
                  side_effect=RuntimeError('store down')):
        assert audit_library_matches([game], pc_library) == []
    assert game.match_checked_at is None


@pytest.mark.integration
def test_rescan_never_touches_a_person_chosen_title(app, db_session, pc_library):
    game = _game(db_session, pc_library, name='Star Trek: Armada', igdb_id=18903,
                 path='/pc/_s/Star Trek Deep Space Nine Dominion Wars 2', match_locked=True)
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game') as igdb:
        assert audit_library_matches([game], pc_library) == []
    igdb.assert_not_called()
    assert game.name == 'Star Trek: Armada'


@pytest.mark.integration
def test_rescan_moves_a_wrong_match_to_the_meta_store_game(app, db_session, pc_library):
    from oneirodex.models import GameURL
    from oneirodex.utils.software_identify import CUSTOM_IGDB_BASE

    game = _game(db_session, pc_library, name='Golden Axe', igdb_id=4321,
                 path='/pc/_g/Golden Gloves Boxing VR')
    details = _golden_gloves_details()
    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', return_value=[]), \
            patch('oneirodex.utils.meta_store_search.search_meta_store', return_value=SEARCH_HITS), \
            patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details), \
            patch('oneirodex.utils.software_identify.search_steam_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_gog_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_epic_games', return_value=[]):
        changes = audit_library_matches([game], pc_library)

    assert [c['new'] for c in changes] == ['Golden Gloves']
    assert game.igdb_id >= CUSTOM_IGDB_BASE
    assert game.summary == details['summary']
    urls = db_session.query(GameURL).filter_by(game_uuid=game.uuid).all()
    assert [(u.url_type, u.url) for u in urls] == [('meta_quest', details['url'])]


def test_manual_identify_locks_the_match():
    source = Path(__file__).parents[1] / 'oneirodex' / 'runtime_native' / 'manual_identify_mutations.py'
    text = source.read_text()
    assert text.count('match_locked') >= 2
