"""Flask-WTF-compatible CSRF validation for native ASGI write routes."""
from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import Response


def csrf_error_response(
    request: Request,
    session_data: Mapping,
    config: Mapping,
    *,
    token: str | None = None,
) -> Response | None:
    """Return the shared API error when a browser write token is invalid."""
    if not config.get('WTF_CSRF_ENABLED', True):
        return None

    from oneirodex.runtime_native.session_compat import CsrfTokenError, validate_csrf_token
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    token = token or request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
    field_name = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    try:
        validate_csrf_token(
            token,
            session_data,
            config.get('WTF_CSRF_SECRET_KEY') or config.get('SECRET_KEY'),
            field_name=field_name,
            time_limit=config.get('WTF_CSRF_TIME_LIMIT', 3600),
        )
    except CsrfTokenError as exc:
        payload, status = api_error_payload(str(exc), code='bad_request')
        return JSONResponse(payload, status_code=status)
    return None
