from __future__ import annotations

import asyncio

from starlette.requests import Request
from fastapi import FastAPI
from starlette.responses import JSONResponse

from oneirodex.runtime_native.bounded_request_body import (
    ASGIBodyLimitMiddleware,
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


def _limited_app():
    app = FastAPI()
    app.add_middleware(ASGIBodyLimitMiddleware, max_bytes=8)

    @app.post('/')
    async def parse_body(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return JSONResponse(payload)

    return app


def _asgi_call(app, messages, *, headers=()):
    pending = iter(messages)
    sent = []

    async def receive():
        return next(pending)

    async def send(message):
        sent.append(message)

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/', 'raw_path': b'/',
        'query_string': b'', 'headers': list(headers),
        'server': ('testserver', 80), 'client': ('127.0.0.1', 1),
    }
    asyncio.run(app(scope, receive, send))
    return sent


def test_asgi_body_limit_rejects_oversized_declared_json_before_handler():
    sent = _asgi_call(
        _limited_app(), [],
        headers=[(b'content-type', b'application/json'), (b'content-length', b'9')],
    )

    assert sent[0]['status'] == 413
    assert b'payload_too_large' in sent[1]['body']


def test_asgi_body_limit_rejects_oversized_chunked_json_before_handler_fallback():
    sent = _asgi_call(
        _limited_app(), [
            {'type': 'http.request', 'body': b'{"a":', 'more_body': True},
            {'type': 'http.request', 'body': b'1234}', 'more_body': False},
        ], headers=[(b'content-type', b'application/json')],
    )

    assert sent[0]['status'] == 413
    assert b'payload_too_large' in sent[1]['body']
