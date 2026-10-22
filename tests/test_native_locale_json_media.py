import asyncio

from flask import Flask, request as flask_request
from starlette.requests import Request

from oneirodex.runtime_native.locale import _locale_from_request


def _native_request(content_type: str, body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'http',
            'path': '/api/locale',
            'raw_path': b'/api/locale',
            'query_string': b'',
            'headers': [(b'content-type', content_type.encode('ascii'))],
            'server': ('testserver', 80),
            'client': ('127.0.0.1', 12345),
        },
        receive=receive,
    )


def test_locale_json_media_types_match_flask_request_parser():
    body = b'{"locale":"fr"}'
    legacy = Flask('legacy-locale-media')
    with legacy.test_request_context(
        '/api/locale', method='POST', content_type='application/vnd.oneirodex+json',
        data=body,
    ):
        assert flask_request.is_json is True
        assert flask_request.get_json(silent=True) == {'locale': 'fr'}
    with legacy.test_request_context(
        '/api/locale', method='POST', content_type='text/plain+json', data=body,
    ):
        assert flask_request.is_json is False
        assert flask_request.get_json(silent=True) is None

    vendor_locale = asyncio.run(_locale_from_request(
        _native_request('application/vnd.oneirodex+json', body),
    ))
    unrelated_suffix = asyncio.run(_locale_from_request(
        _native_request('text/plain+json', body),
    ))
    misleading_jsonp = asyncio.run(_locale_from_request(
        _native_request('application/jsonp', body),
    ))

    assert vendor_locale == 'fr'
    assert unrelated_suffix is None
    assert misleading_jsonp is None
