"""Shared helpers for turning an error into the API JSON envelope.

Why this exists
---------------
``oneirodex/utils/api_response.py`` gives every *deliberate* API response one
shape (``api_ok`` / ``api_error``). Uncaught errors bypassed it entirely:
``oneirodex/__init__.py`` registered a handler for 413 and nothing else, so any
other ``HTTPException`` (404, 403, a raised ``abort``) and every unhandled
``Exception`` in an ``/api/`` route came back as Flask's stock **HTML** page —
the exact "the SPA has no error state" problem the envelope was built to fix,
still open at the crash path. ``PageStatus`` on the frontend has nothing to key
on when the body is ``<!doctype html>``.

``create_app`` now registers catch-all ``HTTPException`` / ``Exception``
handlers that use the two helpers here. HTML routes are left on Flask's default
pages — the switch is ``wants_json_error``.
"""

from __future__ import annotations

from oneirodex.utils.api_contract import ERROR_CODES


def wants_json_error(request) -> bool:
    """True when the caller expects a JSON body for an error response.

    This is the same test the 413 handler has used since it was written, lifted
    here so every error path agrees on it: an ``/api/`` path, an explicit
    ``Accept: application/json``, or a legacy ``X-Requested-With`` XHR.
    """
    return (
        request.path.startswith('/api/')
        or request.accept_mimetypes.best == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


# werkzeug HTTP status -> stable ``ERROR_CODES`` token. Anything unlisted falls
# back by class: a 4xx becomes ``bad_request`` (status is still preserved
# verbatim, e.g. 405), everything else becomes ``internal``.
_STATUS_TO_CODE = {
    400: 'bad_request',
    401: 'unauthorized',
    403: 'forbidden',
    404: 'not_found',
    409: 'conflict',
    413: 'payload_too_large',
    422: 'unprocessable',
    429: 'rate_limited',
    500: 'internal',
    502: 'bad_gateway',
    503: 'unavailable',
}

# Fail loudly at import time if a code is ever renamed in api_response.py.
assert set(_STATUS_TO_CODE.values()) <= set(ERROR_CODES), (
    'error_envelope._STATUS_TO_CODE references a code not in ERROR_CODES'
)


def http_error_code(status: int | None) -> str:
    """Map a werkzeug HTTP status onto an ``ERROR_CODES`` token."""
    if status in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status]
    if status is not None and 400 <= status < 500:
        return 'bad_request'
    return 'internal'
