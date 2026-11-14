import asyncio

from flask import Flask, request as flask_request
from starlette.requests import Request

from oneirodex.runtime_native.library_admin_mutations import _create_payload


def _request(content_type: str, body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(
        {
            'type': 'http', 'http_version': '1.1', 'method': 'POST',
            'scheme': 'http', 'path': '/admin/library/add',
            'raw_path': b'/admin/library/add', 'query_string': b'',
            'headers': [(b'content-type', content_type.encode('ascii'))],
            'server': ('testserver', 80), 'client': ('127.0.0.1', 12345),
        },
        receive=receive,
    )


def test_library_create_payload_uses_flask_json_media_classification():
    legacy = Flask('legacy-library-json-media')
    body = b'{"name":"Fixture","platform":"NES"}'
    with legacy.test_request_context(
        '/admin/library/add', method='POST',
        content_type='application/vnd.oneirodex+json', data=body,
    ):
        assert flask_request.is_json is True
        assert flask_request.get_json(silent=True) == {'name': 'Fixture', 'platform': 'NES'}
    with legacy.test_request_context(
        '/admin/library/add', method='POST', content_type='application/jsonp', data=body,
    ):
        assert flask_request.is_json is False
        assert flask_request.get_json(silent=True) is None

    vendor_payload, vendor_image, vendor_too_large = asyncio.run(_create_payload(
        _request('application/vnd.oneirodex+json', body), {'MAX_CONTENT_LENGTH': 4096},
    ))
    jsonp_payload, jsonp_image, jsonp_too_large = asyncio.run(_create_payload(
        _request('application/jsonp', body), {'MAX_CONTENT_LENGTH': 4096},
    ))

    assert vendor_payload == {'name': 'Fixture', 'platform': 'NES'}
    assert vendor_image is None and vendor_too_large is False
    assert jsonp_payload == {}
    assert jsonp_image is None and jsonp_too_large is False
