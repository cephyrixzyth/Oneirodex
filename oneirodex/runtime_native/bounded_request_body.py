"""Small streamed request-body reader for native routes with legacy parsers."""
from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse


BODY_TOO_LARGE = object()


class _RequestBodyLimitExceeded(BaseException):
    """Escape legacy ``except Exception`` JSON fallbacks on oversized streams."""


class ASGIBodyLimitMiddleware:
    """Enforce the configured request ceiling before native handlers buffer it.

    Route helpers should still use ``read_bounded_body`` for smaller endpoint
    limits. This outer guard also covers older native handlers that call
    ``request.json()`` directly, including clients that omit Content-Length.
    """

    def __init__(self, app, *, max_bytes: int, response_headers=None):
        self.app = app
        self.max_bytes = max(1, int(max_bytes))
        self.response_headers = dict(response_headers or {})

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get('headers', ())}
        try:
            declared_size = int(headers.get(b'content-length', b''))
        except (TypeError, ValueError):
            declared_size = 0
        if declared_size > self.max_bytes:
            await self._send_too_large(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def bounded_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get('type') == 'http.request':
                received_bytes += len(message.get('body', b''))
                if received_bytes > self.max_bytes:
                    raise _RequestBodyLimitExceeded()
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get('type') == 'http.response.start':
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except _RequestBodyLimitExceeded:
            if response_started:
                return
            await self._send_too_large(scope, receive, send)

    async def _send_too_large(self, scope, receive, send):
        from oneirodex.utils.api_contract import api_error_payload

        payload, status = api_error_payload(
            'Request body is too large.', code='payload_too_large',
        )
        response = JSONResponse(
            payload, status_code=status, headers=self.response_headers,
        )
        await response(scope, receive, send)


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
