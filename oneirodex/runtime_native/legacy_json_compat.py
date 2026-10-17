"""Request JSON parsing edges used by retained legacy form endpoints."""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse


class LegacyJSONError(ValueError):
    def __init__(self, status_code: int, description: str):
        super().__init__(description)
        self.status_code = status_code
        self.description = description


async def parse_legacy_json(request: Request):
    """Match Flask ``request.json`` MIME, empty-body, and JSON decoding rules."""
    media_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if not (media_type == 'application/json' or (
        media_type.startswith('application/') and media_type.endswith('+json')
    )):
        raise LegacyJSONError(
            415,
            'The server does not support the media type transmitted in the request.',
        )

    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise LegacyJSONError(
            400,
            'The browser (or proxy) sent a request that this server could not understand.',
        ) from None


def legacy_json_error_response(request: Request, exc: LegacyJSONError):
    """Render the same HTML-vs-JSON error choice as the legacy Flask handler."""
    from oneirodex.utils.api_contract import api_error_payload

    accept = request.headers.get('accept', '')
    wants_json = (
        request.url.path.startswith('/api/')
        or 'application/json' in accept.lower()
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    )
    if wants_json:
        code = 'payload_too_large' if exc.status_code == 413 else 'bad_request'
        payload, status = api_error_payload(
            exc.description, code=code, status=exc.status_code,
        )
        return JSONResponse(payload, status_code=status)

    title = {400: '400 Bad Request', 413: '413 Request Entity Too Large',
             415: '415 Unsupported Media Type'}.get(exc.status_code, 'Error')
    heading = title.split(' ', 1)[1]
    return HTMLResponse(
        '<!doctype html>\n<html lang=en>\n<title>' + title + '</title>\n'
        '<h1>' + heading + '</h1>\n<p>' + exc.description + '</p>\n',
        status_code=exc.status_code,
    )


def legacy_unexpected_error_response(request: Request):
    """Match the shared legacy error handler for uncaught non-HTTP errors."""
    from oneirodex.utils.api_contract import api_error_payload

    accept = request.headers.get('accept', '')
    wants_json = (
        request.url.path.startswith('/api/')
        or 'application/json' in accept.lower()
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    )
    message = 'Something went wrong on our end. The error has been logged.'
    if wants_json:
        payload, status = api_error_payload(message, code='internal', status=500)
        return JSONResponse(payload, status_code=status)
    return HTMLResponse(
        '<!doctype html>\n<html lang=en>\n<title>500 Internal Server Error</title>\n'
        '<h1>Internal Server Error</h1>\n<p>The server encountered an internal error and was unable to complete your request. Either the server is overloaded or there is an error in the application.</p>\n',
        status_code=500,
    )
