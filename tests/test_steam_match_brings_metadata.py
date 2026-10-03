"""A hand-picked Steam match must bring over Steam's content, not just the name.

Reported: "when I add a steam match nothing is brought over besides the name and
sometimes image". `mark_unmatched_as_kind` (both Unmatched "mark as" routes)
created the game and never mapped Steam's content onto it.
"""
from uuid import uuid4

import pytest

from oneirodex.models import Library, UnmatchedFolder
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import steam_lookup, steam_metadata
from oneirodex.utils.software_identify import mark_unmatched_as_kind

pytestmark = pytest.mark.integration

DETAILS = {
    'steam_app_id': 123456,
    'name': 'Redout',
    'steam_type': 'game',
    'header_image': 'https://cdn.example/redout/header.jpg',
    'short_description': 'An antigravity racer.',
    'genres': ['Racing', 'Indie'],
    'categories': ['Single-player', 'Steam Achievements'],
    'developers': ['34BigThings'],
    'publishers': ['34BigThings srl'],
    'release_date': '12 Sep, 2016',
    'metacritic': 76,
}


def _steam_returns(monkeypatch, fn):
    # steam_metadata binds the name at import, so patch the name it calls.
    monkeypatch.setattr(steam_lookup, 'fetch_steam_app_details', fn)
    monkeypatch.setattr(steam_metadata, 'fetch_steam_app_details', fn)


@pytest.fixture
def folder(db_session):
    library = Library(name=f'SteamMatchLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    row = UnmatchedFolder(
        folder_path=f'/storage/_pc/Redout_{uuid4().hex[:6]}',
        library_uuid=library.uuid,
        status='Unmatched',
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_steam_match_fills_the_game_from_steam(folder, db_session, monkeypatch):
    _steam_returns(monkeypatch, lambda app_id, **kw: dict(DETAILS))

    game = mark_unmatched_as_kind(folder, item_kind='game', name='Redout', steam_app_id=123456)
    db_session.flush()

    assert game.summary == 'An antigravity racer.'
    assert game.cover == 'https://cdn.example/redout/header.jpg'
    assert {g.name for g in game.genres} >= {'Racing', 'Indie'}
    assert game.developer_id is not None and game.publisher_id is not None
    assert game.first_release_date is not None and game.first_release_date.year == 2016
    assert game.steam_app_id == 123456


def test_a_steam_outage_still_creates_the_game(folder, db_session, monkeypatch):
    _steam_returns(monkeypatch, lambda app_id, **kw: None)

    game = mark_unmatched_as_kind(folder, item_kind='game', name='Redout', steam_app_id=123456)
    db_session.flush()

    assert game.name == 'Redout' and game.steam_app_id == 123456
    assert not game.genres


def test_a_match_without_a_steam_id_does_not_call_steam(folder, db_session, monkeypatch):
    calls = []
    _steam_returns(monkeypatch, lambda app_id, **kw: calls.append(app_id))

    game = mark_unmatched_as_kind(folder, item_kind='game', name='Homebrew Thing')
    db_session.flush()

    assert game.name == 'Homebrew Thing' and calls == []


def test_steam_fetch_retries_a_rate_limit_then_succeeds(monkeypatch):
    class Resp:
        def __init__(self, status, body=None, headers=None):
            self.status_code, self._body, self.headers = status, body, headers or {}

        def json(self):
            return self._body

    body = {'123456': {'success': True, 'data': {'name': 'Redout', 'type': 'game'}}}
    answers = [Resp(429, headers={'Retry-After': '0'}), Resp(200, body)]
    seen = []
    monkeypatch.setattr(steam_lookup.requests, 'get', lambda url, **kw: (seen.append(kw), answers.pop(0))[1])
    monkeypatch.setattr(steam_lookup.time, 'sleep', lambda s: None)

    details = steam_lookup.fetch_steam_app_details(123456)

    assert details and details['name'] == 'Redout'
    assert 'User-Agent' in seen[0]['headers'], 'Steam throttles clients without a user agent'
