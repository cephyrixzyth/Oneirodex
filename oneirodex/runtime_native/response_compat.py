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


def flask_route_not_found_response(flask_app, request) -> Response:
    """Match Flask's 404 when a route converter rejects a request path."""
    return flask_http_exception_response(flask_app, request, 404)


def flask_http_exception_response(flask_app, request, status_code: int) -> Response:
    """Match Flask's configured HTTP exception response for a native path."""
    from werkzeug.exceptions import default_exceptions

    from oneirodex.utils.error_envelope import wants_json_error

    error_type = default_exceptions.get(status_code)
    if error_type is None:
        raise ValueError(f'Unsupported HTTP error status: {status_code}')
    error = error_type()
    if wants_json_error(request):
        from starlette.responses import JSONResponse

        from oneirodex.utils.error_envelope import http_error_code
        from oneirodex.utils.api_contract import api_error_payload

        payload, status = api_error_payload(
            error.description,
            code=http_error_code(error.code),
            status=error.code or status_code,
        )
        response = JSONResponse(payload, status_code=status)
    else:
        response = flask_http_error_response(
            status_code,
            head=getattr(request, 'method', '').upper() == 'HEAD',
        )

    if getattr(request, 'method', '').upper() == 'HEAD' and response.body:
        from starlette.responses import Response

        response = Response(
            content=b'', status_code=response.status_code,
            headers=dict(response.headers),
        )

    from oneirodex.utils.security_headers import security_header_values

    config = getattr(flask_app, 'config', flask_app)
    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)
    return response
