"""Network-free checks for the gaming news fetch boundary."""

import ipaddress

import requests

from oneirodex.utils import gaming_news, security


FEED_XML = (
    b'<rss><channel><item><title>Fresh news</title>'
    b'<link>https://story.example/news</link></item></channel></rss>'
)


def _response(status: int, body: bytes = b'', *, location: str | None = None):
    response = requests.Response()
    response.status_code = status
    response._content = body
    response._content_consumed = True
    if location:
        response.headers['Location'] = location
    return response


def test_public_feed_uses_streaming_validated_fetch(monkeypatch):
    monkeypatch.setattr(gaming_news, 'feed_urls', lambda: ('https://public.example/rss',))
    monkeypatch.setattr(security, '_resolve_host', lambda _host: [ipaddress.ip_address('93.184.216.34')])
    requests_sent = []

    def request(_session, method, url, **kwargs):
        requests_sent.append((method, url, kwargs))
        return _response(200, FEED_XML)

    monkeypatch.setattr(requests.Session, 'request', request)
    items = gaming_news.fetch_gaming_headlines()

    assert len(items) == 1
    assert items[0]['title'] == 'Fresh news'
    assert len(requests_sent) == 1
    method, url, kwargs = requests_sent[0]
    assert method == 'GET'
    assert url.startswith('https://93.184.216.34/')
    assert kwargs['headers']['Host'] == 'public.example'
    assert kwargs['stream'] is True
    assert kwargs['timeout'] == 6
    assert kwargs['headers']['User-Agent'] == 'OneirodexNews/0.2'


def test_private_initial_feed_never_connects(monkeypatch):
    monkeypatch.setattr(gaming_news, 'feed_urls', lambda: ('http://127.0.0.1/rss',))
    requests_sent = []
    monkeypatch.setattr(requests.Session, 'request', lambda *_args, **_kwargs: requests_sent.append(True))

    assert gaming_news.fetch_gaming_headlines() == []
    assert not requests_sent


def test_private_redirect_is_blocked_and_next_feed_succeeds(monkeypatch):
    monkeypatch.setattr(gaming_news, 'feed_urls', lambda: (
        'https://redirect.example/rss', 'https://good.example/rss',
    ))
    monkeypatch.setattr(security, '_resolve_host', lambda _host: [ipaddress.ip_address('93.184.216.34')])
    sent_hosts = []

    def request(_session, _method, _url, **kwargs):
        host = kwargs['headers']['Host']
        sent_hosts.append(host)
        if host == 'redirect.example':
            return _response(302, location='http://169.254.169.254/latest/meta-data/')
        return _response(200, FEED_XML)

    monkeypatch.setattr(requests.Session, 'request', request)
    items = gaming_news.fetch_gaming_headlines()

    assert [item['title'] for item in items] == ['Fresh news']
    assert sent_hosts == ['redirect.example', 'good.example']


def test_oversized_decoded_body_stops_reading_and_tries_next_feed(monkeypatch):
    monkeypatch.setattr(gaming_news, 'feed_urls', lambda: (
        'https://large.example/rss', 'https://good.example/rss',
    ))
    chunks_read = []
    closed = []

    class StreamingResponse:
        def __init__(self, large):
            self.large = large

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closed.append(self.large)

        def raise_for_status(self):
            pass

        def iter_content(self, *, chunk_size):
            assert chunk_size == 64 * 1024
            if self.large:
                for index in range(100):
                    chunks_read.append(index)
                    yield b'x' * chunk_size
            else:
                yield FEED_XML

    def safe_get(url, **kwargs):
        assert kwargs['stream'] is True
        return StreamingResponse('large.example' in url)

    monkeypatch.setattr(gaming_news, 'safe_get', safe_get)
    items = gaming_news.fetch_gaming_headlines()

    assert [item['title'] for item in items] == ['Fresh news']
    assert len(chunks_read) == 8
    assert closed == [True, False]
