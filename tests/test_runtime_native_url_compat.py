from types import SimpleNamespace

from starlette.datastructures import URL

from oneirodex.runtime_native.url_compat import request_url_iri


def test_request_url_iri_matches_werkzeug_query_decoding_without_splitting_reserved_values():
    request = SimpleNamespace(
        url=URL('http://testserver/api/path/open?path=%2Fstorage%2Flibrary&note=%26x%3Dy')
    )

    assert request_url_iri(request) == (
        'http://testserver/api/path/open?path=/storage/library&note=%26x%3Dy'
    )
