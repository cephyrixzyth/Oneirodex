"""Response shapes shared with Flask/Werkzeug during the ASGI migration."""
from __future__ import annotations

from html import escape

from starlette.responses import Response


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
