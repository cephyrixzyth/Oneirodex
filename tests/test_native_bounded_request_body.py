from __future__ import annotations

import asyncio

from starlette.requests import Request

from oneirodex.runtime_native.bounded_request_body import (
    BODY_TOO_LARGE,
    read_bounded_body,
)


def _request(messages, *, headers=()):
    pending = iter(messages)

    async def receive():
        return next(pending)

    return Request({
        'type': 'http', 'method': 'POST', 'path': '/', 'headers': list(headers),
        'query_string': b'', 'server': ('testserver', 80), 'client': ('127.0.0.1', 1),
        'scheme': 'http', 'http_version': '1.1',
    }, receive=receive)


def test_bounded_body_rejects_declared_oversize_without_reading_stream():
    request = _request(
        [], headers=[(b'content-length', b'9')],
    )
    assert asyncio.run(read_bounded_body(request, 8)) is BODY_TOO_LARGE


def test_bounded_body_caps_chunked_or_underreported_streams():
    request = _request([
        {'type': 'http.request', 'body': b'1234', 'more_body': True},
        {'type': 'http.request', 'body': b'5678', 'more_body': True},
        {'type': 'http.request', 'body': b'9', 'more_body': False},
    ], headers=[(b'content-length', b'1')])

    assert asyncio.run(read_bounded_body(request, 8)) is BODY_TOO_LARGE
