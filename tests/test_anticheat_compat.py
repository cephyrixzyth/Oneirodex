"""INSP-35 / H1e: the community anti-cheat compatibility source.

The parser and the lookups run against ``tests/fixtures/anticheat_games.json``;
the fetch is exercised only through a mocked ``safe_request`` and stays off
under pytest unless a test opts in with ``ANTICHEAT_COMPAT_IN_TESTS=1``.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from oneirodex.utils import anticheat_compat as ac

FIXTURE = Path(__file__).parent / 'fixtures' / 'anticheat_games.json'


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    target = tmp_path / 'anticheat' / 'games.json'
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, target)
    monkeypatch.setenv('ANTICHEAT_CACHE_PATH', str(target))
    monkeypatch.delenv('ENABLE_ANTICHEAT_COMPAT', raising=False)
    ac.load_index(force=True)
    yield target
    ac.load_index(force=True)


def test_parse_feed_keeps_known_rows_and_drops_junk():
    index = ac.parse_feed(FIXTURE.read_bytes())
    assert index['count'] == 3  # two real rows + the malformed-but-named one; no-name and 'junk' dropped
    row = index['by_steam']['440000']
    assert row['status'] == 'denied'
    assert row['anticheats'] == ['Easy Anti-Cheat']
    assert row['reports'] == 2
    assert row['updated'] == '2026-01-10'
    assert row['source_url'] == 'https://areweanticheatyet.com/game/rocket-fortress'
    # Numeric steam id, empty updates, unknown vocabulary all normalise
    assert index['by_steam']['550000']['reports'] == 0
    assert index['by_name']['nameless entry']['status'] == 'unknown'
    assert index['by_name']['nameless entry']['anticheats'] == []


def test_parse_feed_rejects_non_lists_and_empty_feeds():
    with pytest.raises(ValueError):
        ac.parse_feed(json.dumps({'hello': 'world'}))
    with pytest.raises(ValueError):
        ac.parse_feed('[]')
    with pytest.raises(ValueError):
        ac.parse_feed('not json')


def test_lookup_by_steam_id_then_name_then_none(cache_file):
    assert ac.lookup(steam_app_id=440000)['name'] == 'Rocket Fortress'
    assert ac.lookup(steam_app_id='550000')['status'] == 'supported'
    assert ac.lookup(name='ROCKET  Fortress!')['status'] == 'denied'
    assert ac.lookup(steam_app_id=1, name='Unknown Title') is None
    assert ac.lookup() is None


def test_lookup_is_none_without_a_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTICHEAT_CACHE_PATH', str(tmp_path / 'missing.json'))
    ac.load_index(force=True)
    assert ac.lookup(steam_app_id=440000) is None
    assert ac.status_summary()['configured'] is False


def test_disabled_flag_silences_everything(cache_file, monkeypatch):
    monkeypatch.setenv('ENABLE_ANTICHEAT_COMPAT', 'false')
    ac.load_index(force=True)
    assert ac.lookup(steam_app_id=440000) is None
    summary = ac.status_summary()
    assert summary['enabled'] is False and summary['configured'] is False


def _game(*, steam_app_id=None, name='Rocket Fortress', platform='PCWIN'):
    library = SimpleNamespace(platform=SimpleNamespace(name=platform)) if platform else None
    return SimpleNamespace(steam_app_id=steam_app_id, name=name, library=library)


def test_game_anticheat_uses_steam_id_and_pc_name_fallback_only(cache_file):
    assert ac.game_anticheat(_game(steam_app_id=550000, name='Anything'))['status'] == 'supported'
    assert ac.game_anticheat(_game(name='Rocket Fortress'))['status'] == 'denied'
    # A console shelf never name-matches: the list is a PC story
    assert ac.game_anticheat(_game(name='Rocket Fortress', platform='SNES')) is None
    assert ac.game_anticheat(None) is None


def test_game_card_flags_emits_anticheat(cache_file):
    from oneirodex.utils.secondary_scrapers import game_card_flags

    flags = game_card_flags(_game(steam_app_id=440000))
    assert flags['anticheat']['status'] == 'denied'
    assert flags['anticheat']['reports'] == 2


def test_refresh_is_off_under_pytest_unless_opted_in(app, cache_file, monkeypatch):
    monkeypatch.delenv('ANTICHEAT_COMPAT_IN_TESTS', raising=False)
    with app.app_context(), patch.object(ac, 'safe_request') as req:
        assert ac.refresh_if_stale(force=True) is False
        req.assert_not_called()


def test_refresh_writes_cache_and_keeps_old_file_on_failure(app, tmp_path, monkeypatch):
    target = tmp_path / 'ac' / 'games.json'
    monkeypatch.setenv('ANTICHEAT_CACHE_PATH', str(target))
    monkeypatch.setenv('ANTICHEAT_COMPAT_IN_TESTS', '1')
    monkeypatch.delenv('ENABLE_ANTICHEAT_COMPAT', raising=False)
    ac.load_index(force=True)
    body = FIXTURE.read_bytes()

    good = SimpleNamespace(status_code=200, content=body)
    with app.app_context(), patch.object(ac, 'safe_request', return_value=good) as req:
        assert ac.refresh_if_stale() is True
        assert req.call_args.kwargs['validator'] is ac.validate_user_outbound_http_url
        assert req.call_args.kwargs['stream'] is True
    assert target.exists()
    assert ac.lookup(steam_app_id=440000)['status'] == 'denied'

    # Fresh cache: no second fetch
    with app.app_context(), patch.object(ac, 'safe_request') as req:
        assert ac.refresh_if_stale() is False
        req.assert_not_called()

    # Stale + broken answers keep the file we have
    old = time.time() - ac.CACHE_TTL_SECONDS - 10
    os.utime(target, (old, old))
    for bad in (SimpleNamespace(status_code=503, content=b''), SimpleNamespace(status_code=200, content=b'{}')):
        with app.app_context(), patch.object(ac, 'safe_request', return_value=bad):
            assert ac.refresh_if_stale() is False
        assert target.read_bytes() == body
    with app.app_context(), patch.object(ac, 'safe_request', side_effect=OSError('offline')):
        assert ac.refresh_if_stale() is False
    assert target.read_bytes() == body
    ac.load_index(force=True)


def test_parse_feed_enforces_row_limit(monkeypatch):
    monkeypatch.setattr(ac, 'MAX_FEED_ROWS', 1)
    with pytest.raises(ValueError, match='row limit'):
        ac.parse_feed(FIXTURE.read_bytes())
