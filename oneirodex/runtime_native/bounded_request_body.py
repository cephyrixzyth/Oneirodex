"""Small streamed request-body reader for native routes with legacy parsers."""
from __future__ import annotations

from fastapi import Request


BODY_TOO_LARGE = object()


async def read_bounded_body(request: Request, max_bytes: int):
    """Read at most ``max_bytes`` from a request, including chunked bodies."""
    content_length = request.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return BODY_TOO_LARGE
        except ValueError:
            pass

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            return BODY_TOO_LARGE
        body.extend(chunk)
    return bytes(body)
