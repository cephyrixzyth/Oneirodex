"""Free-game claim URLs are scheme-checked: only http(s) is stored or returned.

GamerPower is a third-party feed. Its ``open_giveaway_url`` used to be stored
and returned as given, then handed to ``window.open`` by the News page and
wrapped into a ``steam://openurl/`` deeplink, so a hostile feed could serve a
``javascript:`` or ``data:`` URL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from oneirodex.utils import free_games as fg

HOSTILE = [
    'javascript:alert(document.domain)',
    'JaVaScRiPt:alert(1)',
    '  javascript:alert(1)',
    'java\tscript:alert(1)',
    'java\nscript:alert(1)',
    '\x01javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    'blob:https://example.test/abc',
    'steam://openurl/https://example.test',
    'ftp://example.test/claim',
    '//example.test/claim',
    '/relative/claim',
    'example.test/claim',
    'https://',
    'http:///nohost',
    'https:// spaced.test/',
    '',
    '   ',
]


@pytest.mark.parametrize('value', [
    'https://store.steampowered.com/app/123/',
    'http://example.test/claim?x=1#frag',
    'HTTPS://Example.test/Claim',
    '  https://example.test/padded  ',
])
def test_http_url_or_none_keeps_http_and_https(value):
    assert fg.http_url_or_none(value) == value.strip()


@pytest.mark.parametrize('value', HOSTILE + [None, 42, ['https://example.test'], {'u': 'https://x.test'}])
def test_http_url_or_none_drops_everything_else(value):
    assert fg.http_url_or_none(value) is None


def _gamerpower(monkeypatch, payload):
    monkeypatch.setattr(
        fg,
        'request_with_backoff',
        lambda *_a, **_k: SimpleNamespace(json=lambda: payload),
    )
    return fg.fetch_gamerpower_giveaways()


def _giveaway(**overrides):
    row = {
        'id': 1,
        'title': 'Free Thing',
        'platforms': 'PC, GOG',
        'status': 'Active',
        'open_giveaway_url': 'https://www.gog.com/en/game/free_thing',
        'image': 'https://www.gamerpower.com/offers/1.jpg',
    }
    row.update(overrides)
    return row


def test_gamerpower_keeps_a_normal_https_claim_url(monkeypatch):
    rows = _gamerpower(monkeypatch, [_giveaway()])
    assert len(rows) == 1
    assert rows[0]['claim_url'] == 'https://www.gog.com/en/game/free_thing'
    assert rows[0]['store_url'] == 'https://www.gog.com/en/game/free_thing'


@pytest.mark.parametrize('hostile', HOSTILE)
def test_gamerpower_drops_an_offer_whose_only_url_is_hostile(monkeypatch, hostile):
    rows = _gamerpower(monkeypatch, [_giveaway(open_giveaway_url=hostile)])
    assert rows == []


@pytest.mark.parametrize('hostile', [h for h in HOSTILE if h.strip()])
def test_gamerpower_falls_back_to_a_safe_gamerpower_url(monkeypatch, hostile):
    """A bad open_giveaway_url loses to a good gamerpower_url, not the other way round."""
    rows = _gamerpower(monkeypatch, [_giveaway(
        open_giveaway_url=hostile,
        gamerpower_url='https://www.gamerpower.com/free-thing',
    )])
    assert [r['claim_url'] for r in rows] == ['https://www.gamerpower.com/free-thing']
    assert [r['store_url'] for r in rows] == ['https://www.gamerpower.com/free-thing']


def test_gamerpower_drops_hostile_rows_but_keeps_the_rest(monkeypatch):
    rows = _gamerpower(monkeypatch, [
        _giveaway(id=1, title='Bad One', open_giveaway_url='javascript:alert(1)'),
        _giveaway(id=2, title='Good One'),
        _giveaway(id=3, title='Bad Two', open_giveaway_url='data:text/html,x',
                  gamerpower_url='vbscript:x'),
    ])
    assert [r['title'] for r in rows] == ['Good One']


@pytest.mark.parametrize('hostile', [h for h in HOSTILE if h.strip()])
def test_claim_links_never_returns_or_wraps_a_hostile_url(hostile):
    """Rows stored before the ingest check are cleaned on the way out too."""
    links = fg.claim_links(
        {'store': 'steam', 'claim_url': hostile, 'store_url': hostile},
        connected_stores={'steam'},
    )
    assert links == {'https': None, 'protocol': None}


def test_claim_links_prefers_a_safe_store_url_over_a_hostile_claim_url():
    links = fg.claim_links(
        {
            'store': 'steam',
            'claim_url': 'javascript:alert(1)',
            'store_url': 'https://store.steampowered.com/app/9/',
        },
        connected_stores={'steam'},
    )
    assert links['https'] == 'https://store.steampowered.com/app/9/'
    assert links['protocol'] == 'steam://openurl/https://store.steampowered.com/app/9/'


def test_claim_links_epic_deeplink_is_not_built_from_a_hostile_url():
    links = fg.claim_links(
        {'store': 'epic', 'claim_url': 'javascript:/p/pwned', 'store_url': None},
        connected_stores={'epic'},
    )
    assert links == {'https': None, 'protocol': None}


def test_offer_api_dict_does_not_return_a_hostile_stored_url():
    row = SimpleNamespace(
        id=7,
        store='other',
        external_id='gp-7',
        title='Stored Before The Fix',
        description=None,
        image_url=None,
        claim_url='javascript:alert(document.cookie)',
        store_url='data:text/html,<script>alert(1)</script>',
        worth=None,
        starts_at=None,
        ends_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        source='gamerpower',
        active=True,
        first_seen_at=None,
        last_seen_at=None,
    )
    out = fg.offer_to_api_dict(row, connected_stores=set())
    assert out['claim_url'] is None
    assert out['store_url'] is None
    assert out['links'] == {'https': None, 'protocol': None}


def test_offer_api_dict_keeps_a_normal_url():
    row = SimpleNamespace(
        id=8,
        store='epic',
        external_id='e-8',
        title='Fine',
        description=None,
        image_url=None,
        claim_url='https://store.epicgames.com/en-US/p/fine',
        store_url='https://store.epicgames.com/en-US/p/fine',
        worth=None,
        starts_at=None,
        ends_at=None,
        source='epic',
        active=True,
        first_seen_at=None,
        last_seen_at=None,
    )
    out = fg.offer_to_api_dict(row, connected_stores={'epic'})
    assert out['claim_url'] == 'https://store.epicgames.com/en-US/p/fine'
    assert out['links']['protocol'] == 'com.epicgames.launcher://store/en-US/p/fine'
