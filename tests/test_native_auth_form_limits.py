import asyncio

import pytest
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from oneirodex.runtime_native.auth_form_posts import _parse_auth_form


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
        'method': 'POST', 'scheme': 'http', 'path': '/login', 'raw_path': b'/login',
        'query_string': b'', 'headers': [(b'content-type', content_type)],
        'client': ('127.0.0.1', 1234), 'server': ('testserver', 80),
    }, receive=receive)


def test_auth_form_rejects_a_field_over_16_kib():
    request = _request(
        b'username=' + (b'a' * (16 * 1024 + 1)),
        b'application/x-www-form-urlencoded',
    )

    with pytest.raises(MultiPartException):
        asyncio.run(_parse_auth_form(request))


def test_auth_form_rejects_more_than_32_fields():
    request = _request(
        b'&'.join(f'field{index}=x'.encode() for index in range(33)),
        b'application/x-www-form-urlencoded',
    )

    with pytest.raises(MultiPartException):
        asyncio.run(_parse_auth_form(request))
