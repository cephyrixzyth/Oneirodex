"""DB-free checks for fixed-provider debrid redirects."""

from __future__ import annotations


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {'ok': True}


def test_debrid_requests_use_public_https_redirect_validator(monkeypatch):
    from oneirodex.utils import debrid_connectors

    calls = []
    monkeypatch.setattr(
        debrid_connectors,
        'get_debrid_config',
        lambda: {
            'real_debrid_token': 'test-token',
            'alldebrid_api_key': 'test-key',
            'premiumize_api_key': 'test-key',
            'torbox_api_key': 'test-key',
        },
    )

    def fake_fetch(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response()

    monkeypatch.setattr(
        debrid_connectors, 'fetch_with_challenge_retry', fake_fetch
    )

    debrid_connectors.real_debrid_add_magnet('magnet:?xt=urn:btih:abc')
    debrid_connectors.alldebrid_upload_magnet('magnet:?xt=urn:btih:abc')
    debrid_connectors.premiumize_add_magnet('magnet:?xt=urn:btih:abc')
    debrid_connectors.torbox_add_magnet('magnet:?xt=urn:btih:abc')

    assert len(calls) == 4
    assert all(call[2]['validator'] is debrid_connectors._validate_debrid_url for call in calls)
    assert all(debrid_connectors._validate_debrid_url(url)[0] for _, url, _ in calls)
    assert not debrid_connectors._validate_debrid_url('http://example.com/')[0]
    assert not debrid_connectors._validate_debrid_url('https://127.0.0.1/')[0]
    assert not debrid_connectors._validate_debrid_url('https://169.254.169.254/')[0]
