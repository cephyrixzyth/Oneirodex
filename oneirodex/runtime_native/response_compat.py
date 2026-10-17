"""Response shapes shared with Flask/Werkzeug during the ASGI migration."""
from __future__ import annotations

from html import escape

from starlette.responses import Response


def add_vary_header(response, name: str) -> None:
    """Merge a Vary dimension across Starlette and Werkzeug responses."""
    headers = response.headers
    getlist = getattr(headers, 'getlist', None)
    existing = getlist('vary') if callable(getlist) else [headers.get('Vary', '')]
    values = [part.strip() for value in existing for part in value.split(',') if part.strip()]
    if any(value == '*' for value in values):
        return
    if name.casefold() not in {value.casefold() for value in values}:
        values.append(name)
    if values:
        headers['Vary'] = ', '.join(values)


def flask_redirect_response(location: str, *, status_code: int = 302) -> Response:
    """Build the small HTML body Werkzeug emits for ``flask.redirect``."""
    location = str(location)
    safe_location = escape(location, quote=True)
    body = (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        f'<a href="{safe_location}">{safe_location}</a>. If not, click the link.\n'
    )
    return Response(
        content=body,
        status_code=status_code,
        headers={'Location': location},
        media_type='text/html',
    )
