from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from oneirodex.runtime_native.bounded_multipart import (
    InvalidContentLength,
    RequestBodyTooLarge,
    bounded_multipart_form,
)


def _multipart_request(body: bytes, *, chunk_size: int = 32, content_length: str | None = None):
    boundary = b'od-boundary'
    messages = [
        {
            'type': 'http.request',
            'body': body[offset:offset + chunk_size],
            'more_body': offset + chunk_size < len(body),
        }
        for offset in range(0, len(body), chunk_size)
    ]
    if not messages:
        messages = [{'type': 'http.request', 'body': b'', 'more_body': False}]
    index = 0

    async def receive():
        nonlocal index
        message = messages[index]
        index += 1
        return message

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST',
        'scheme': 'http', 'path': '/upload', 'raw_path': b'/upload',
        'query_string': b'', 'headers': [
            (b'content-type', b'multipart/form-data; boundary=od-boundary'),
            *([(b'content-length', content_length.encode())] if content_length is not None else []),
        ],
        'client': ('127.0.0.1', 1), 'server': ('127.0.0.1', 80),
    }
    return Request(scope, receive), boundary


def test_bounded_multipart_form_parses_a_legitimate_file_without_content_length():
    body = (
        b'--od-boundary\r\n'
        b'Content-Disposition: form-data; name="file"; filename="cover.png"\r\n'
        b'Content-Type: image/png\r\n\r\n'
        b'valid-image-bytes\r\n'
        b'--od-boundary--\r\n'
    )
    request, _ = _multipart_request(body)

    form = asyncio.run(bounded_multipart_form(
        request, max_body_bytes=1024, max_files=1, max_fields=2, max_part_size=256,
    ))
    try:
        upload = form.get('file')
        assert upload is not None
        assert upload.filename == 'cover.png'
        assert asyncio.run(upload.read()) == b'valid-image-bytes'
    finally:
        asyncio.run(form.close())


def test_bounded_multipart_form_rejects_streamed_overflow_before_parser_finishes():
    body = (
        b'--od-boundary\r\n'
        b'Content-Disposition: form-data; name="file"; filename="oversized.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n'
        + b'x' * 512
        + b'\r\n--od-boundary--\r\n'
    )
    request, _ = _multipart_request(body, chunk_size=32)

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(bounded_multipart_form(
            request, max_body_bytes=128, max_files=1, max_fields=2, max_part_size=64,
        ))


@pytest.mark.parametrize('content_length', ['not-a-number', '-1'])
def test_bounded_multipart_form_rejects_invalid_content_length(content_length):
    request, _ = _multipart_request(b'', content_length=content_length)

    with pytest.raises(InvalidContentLength):
        asyncio.run(bounded_multipart_form(
            request, max_body_bytes=128, max_files=1, max_fields=2, max_part_size=64,
        ))


def test_bounded_multipart_form_rejects_oversized_declared_length_before_reading():
    request, _ = _multipart_request(b'', content_length='129')
    receive_calls = 0
    original_receive = request.receive

    async def observe_receive():
        nonlocal receive_calls
        receive_calls += 1
        return await original_receive()

    request._receive = observe_receive

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(bounded_multipart_form(
            request, max_body_bytes=128, max_files=1, max_fields=2, max_part_size=64,
        ))

    assert receive_calls == 0
