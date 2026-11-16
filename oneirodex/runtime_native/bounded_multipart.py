"""Multipart parsing with an explicit total request-body ceiling."""
from __future__ import annotations

from fastapi import Request
from starlette.datastructures import FormData


class RequestBodyTooLarge(ValueError):
    """Raised when a multipart request exceeds its configured byte ceiling."""


class InvalidContentLength(ValueError):
    """Raised when Content-Length is present but is not a valid integer."""


async def bounded_multipart_form(
    request: Request,
    *,
    max_body_bytes: int,
    max_files: int,
    max_fields: int,
    max_part_size: int,
) -> FormData:
    """Parse multipart data while counting bytes before Starlette spools files."""
    limit = max(0, int(max_body_bytes))
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            declared_size = int(declared)
        except (TypeError, ValueError):
            raise InvalidContentLength from None
        if declared_size < 0:
            raise InvalidContentLength
        if declared_size > limit:
            raise RequestBodyTooLarge

    received = 0

    async def limited_receive():
        nonlocal received
        message = await request.receive()
        if message.get('type') == 'http.request':
            received += len(message.get('body', b''))
            if received > limit:
                raise RequestBodyTooLarge
        return message

    bounded_request = Request(request.scope, receive=limited_receive)
    return await bounded_request.form(
        max_files=max_files,
        max_fields=max_fields,
        max_part_size=max_part_size,
    )
