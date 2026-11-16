from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from starlette.datastructures import URL
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request as WerkzeugRequest

from oneirodex.runtime_native.url_compat import request_url_iri


@pytest.mark.parametrize(
    'url',
    [
        'http://testserver/api/path/open?path=%2Fstorage%2Flibrary&note=%26x%3Dy',
        'http://testserver/api/path/open?value=%25%252F&plus=a+b&literal=%2B',
        'http://testserver/api/path/open?emoji=%F0%9F%8E%AE&cafe=caf%C3%A9',
        'http://testserver/api/path/open?semi=a%3Bb&hash=%23tag&amp=x%26y',
        'http://testserver/api/path/open?x=1&x=2&empty=&flag',
        'http://testserver/api/path/open?q=%2f%2F%3a%3A%3f%3F',
    ],
)
def test_request_url_iri_matches_werkzeug_for_encoded_query_values(url):
    parsed = urlsplit(url)
    path = parsed.path + (f'?{parsed.query}' if parsed.query else '')
    builder = EnvironBuilder(path=path, base_url=f'{parsed.scheme}://{parsed.netloc}/')
    try:
        legacy_url = WerkzeugRequest(builder.get_environ()).url
    finally:
        builder.close()

    request = SimpleNamespace(url=URL(url))
    assert request_url_iri(request) == legacy_url
