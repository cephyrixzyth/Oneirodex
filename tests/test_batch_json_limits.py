"""Small request-body limits for member batch JSON actions."""
from __future__ import annotations

import asyncio

from oneirodex.runtime_native.batch_favorite import (
    BATCH_JSON_BODY_MAX_BYTES,
    JSON_BODY_TOO_LARGE,
    bounded_json_object,
)


class _Request:
    def __init__(self, body: bytes, *, content_length=None):
        headers = {'content-type': 'application/json'}
        if content_length is not None:
            headers['content-length'] = str(content_length)
        self.headers = headers
        self.body = body
        self.stream_started = False

    async def stream(self):
        self.stream_started = True
        if self.body:
            yield self.body


def test_bounded_json_object_parses_small_object():
    request = _Request(b'{"uuids":["game-a"],"favorite":true}')

    result = asyncio.run(bounded_json_object(request))

    assert result == {'uuids': ['game-a'], 'favorite': True}


def test_bounded_json_object_rejects_large_content_length_before_reading():
    request = _Request(b'{"uuids":[]}', content_length=BATCH_JSON_BODY_MAX_BYTES + 1)

    result = asyncio.run(bounded_json_object(request))

    assert result is JSON_BODY_TOO_LARGE
    assert request.stream_started is False


def test_bounded_json_object_stops_when_stream_exceeds_limit():
    request = _Request(b' ' * (BATCH_JSON_BODY_MAX_BYTES + 1))

    result = asyncio.run(bounded_json_object(request))

    assert result is JSON_BODY_TOO_LARGE
