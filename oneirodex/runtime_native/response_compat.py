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


def flask_http_error_response(status_code: int, description: str | None = None, *, head: bool = False) -> Response:
    """Return the Werkzeug HTML error page used by legacy non-API routes."""
    from werkzeug.exceptions import default_exceptions

    error_type = default_exceptions.get(status_code)
    if error_type is None:
        raise ValueError(f'Unsupported HTTP error status: {status_code}')
    error = error_type(description=description) if description is not None else error_type()
    legacy_response = error.get_response()
    body = b'' if head else legacy_response.get_data()
    headers = dict(legacy_response.headers)
    return Response(content=body, status_code=status_code, headers=headers)
