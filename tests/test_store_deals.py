"""Deep-discount Discover row (CheapShark, read-only)."""

from __future__ import annotations

from oneirodex.utils import store_deals
from oneirodex.utils import store_deals_poller


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _reset_cache():
    store_deals._cache['at'] = 0.0
    store_deals._cache['rows'] = []


def _payload():
    return [
        {
            'dealID': 'a1',
            'title': 'Owned Steam Hit',
            'storeID': '1',
            'savings': '90.0',
            'salePrice': '1.99',
            'normalPrice': '19.99',
            'steamAppID': '42',
            'thumb': 'https://example.test/a.jpg',
        },
        {
            'dealID': 'b2',
            'title': 'Deep Cut Adventure',
            'storeID': '7',
            'savings': '80.0',
            'salePrice': '2.00',
            'normalPrice': '10.00',
            'steamAppID': None,
            'thumb': 'https://example.test/b.jpg',
        },
        {
            'dealID': 'c3',
            'title': 'Mild Sale',
            'storeID': '1',
            'savings': '20.0',
            'salePrice': '8.00',
            'normalPrice': '10.00',
            'steamAppID': '99',
            'thumb': None,
        },
        {
            'dealID': 'free1',
            'title': 'Free Promotion Duplicate',
            'storeID': '25',
            'savings': '100.0',
            'salePrice': '0.00',
            'normalPrice': '29.99',
            'steamAppID': None,
            'thumb': 'https://example.test/free.jpg',
        },
    ]


def test_list_deep_discount_articles_keeps_steep_savings_and_skips_owned(monkeypatch):
    _reset_cache()
    captured = {}

    def fake_get(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return _FakeResponse(_payload())

    monkeypatch.setattr(store_deals, 'request_with_backoff', fake_get)
    monkeypatch.setattr(
        store_deals,
        '_owned_keys',
        lambda _user: ({('steam', '42')}, {'owned steam hit'}),
    )

    articles = store_deals.list_deep_discount_articles(object(), limit=10)
    assert len(articles) == 1
    assert articles[0]['kind'] == 'deal'
    assert articles[0]['title'] == 'Deep Cut Adventure'
    assert articles[0]['store'] == 'gog'
    assert articles[0]['savings'] == 80
    assert articles[0]['href'].startswith('https://www.cheapshark.com/redirect?dealID=')
    params = captured['kwargs']['params']
    assert params['desc'] == '0'
    assert params['sortBy'] == 'Savings'
    assert captured['kwargs']['headers']['User-Agent'] == store_deals.USER_AGENT
    assert 'python-requests' not in captured['kwargs']['headers']['User-Agent']


def test_steam_deals_prefer_portrait_library_art_and_keep_thumbnail_fallback(monkeypatch):
    monkeypatch.setattr(store_deals, 'request_with_backoff', lambda *args, **kwargs: _FakeResponse(_payload()))

    deals = store_deals.fetch_cheapshark_deals()

    steam = next(row for row in deals if row['deal_id'] == 'a1')
    gog = next(row for row in deals if row['deal_id'] == 'b2')
    assert steam['image_url'] == 'https://cdn.cloudflare.steamstatic.com/steam/apps/42/library_600x900_2x.jpg'
    assert steam['image_fallback_url'] == 'https://example.test/a.jpg'
    assert gog['image_url'] == 'https://example.test/b.jpg'
    assert gog['image_fallback_url'] is None


def test_failed_fetch_keeps_stale_snapshot(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: _FakeResponse(_payload()),
    )
    first = store_deals.cached_deep_discounts(force=True)
    assert [row['deal_id'] for row in first] == ['a1', 'b2']

    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: None,
    )
    stale = store_deals.cached_deep_discounts(force=True)
    assert [row['deal_id'] for row in stale] == [row['deal_id'] for row in first]


def test_successful_empty_pull_clears_snapshot(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: _FakeResponse(_payload()),
    )
    first = store_deals.cached_deep_discounts(force=True)
    assert [row['deal_id'] for row in first] == ['a1', 'b2']

    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: _FakeResponse([]),
    )
    empty = store_deals.cached_deep_discounts(force=True)
    assert empty == []


def test_below_threshold_pull_clears_snapshot(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: _FakeResponse(_payload()),
    )
    assert store_deals.cached_deep_discounts(force=True)

    mild = [row for row in _payload() if float(row['savings']) < 75]
    monkeypatch.setattr(
        store_deals,
        'request_with_backoff',
        lambda *args, **kwargs: _FakeResponse(mild),
    )
    assert store_deals.cached_deep_discounts(force=True) == []


def test_store_deals_row_is_registered():
    from oneirodex.utils.discover_providers import _REGISTRY

    assert 'store_deals' in _REGISTRY
    spec, _selector = _REGISTRY['store_deals']
    assert spec.item_kind == 'articles'


def test_store_deals_scheduler_starts_once(monkeypatch):
    monkeypatch.setattr(store_deals_poller, '_scheduler_started', False)
    started = []

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs.get('name'))

    monkeypatch.setattr(store_deals_poller.threading, 'Thread', _FakeThread)
    store_deals_poller.start_store_deals_scheduler(object())
    store_deals_poller.start_store_deals_scheduler(object())
    assert started == ['oneirodex-store-deals']
