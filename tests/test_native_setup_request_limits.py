import asyncio
import json

import pytest
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from oneirodex.runtime_native.setup_transition import _parse_setup_form, _validated_body


def _request(body, content_type):
    consumed = False

    async def receive():
        nonlocal consumed
        if consumed:
            return {'type': 'http.disconnect'}
        consumed = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request({
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/api/setup/transition',
        'raw_path': b'/api/setup/transition', 'query_string': b'',
        'headers': [(b'content-type', content_type)],
        'client': ('127.0.0.1', 1234), 'server': ('testserver', 80),
    }, receive=receive)


def test_setup_form_rejects_field_over_16_kib():
    request = _request(
        b'username=' + (b'a' * (16 * 1024 + 1)),
        b'application/x-www-form-urlencoded',
    )

    with pytest.raises(MultiPartException):
        asyncio.run(_parse_setup_form(request))


def test_setup_json_rejects_oversized_chunked_body_before_schema_validation():
    request = _request(
        b' ' * (64 * 1024 + 1), b'application/json',
    )

    body, error = asyncio.run(_validated_body(request))

    assert body is None
    assert error.status_code == 413
    assert json.loads(error.body)['error_code'] == 'payload_too_large'
