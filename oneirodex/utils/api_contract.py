"""Framework-independent API error envelope contract."""
from __future__ import annotations

from typing import Any


ERROR_CODES = {
    'bad_request': 400,
    'unauthorized': 401,
    'forbidden': 403,
    'not_found': 404,
    'conflict': 409,
    'unprocessable': 422,
    'payload_too_large': 413,
    'rate_limited': 429,
    'internal': 500,
    'bad_gateway': 502,
    'unavailable': 503,
}


def api_ok_payload(payload=None, **extra) -> dict[str, Any]:
    """Build the shared success body without requiring Flask's request globals."""
    body: dict[str, Any] = {}
    if payload:
        body.update(payload)
    if extra:
        body.update(extra)
    for reserved in ('ok', 'error', 'error_code'):
        body.pop(reserved, None)
    body['ok'] = True
    body['error'] = None
    body['error_code'] = None
    body.setdefault('success', True)
    return body


def api_error_payload(
    message: str,
    *,
    code: str = 'bad_request',
    status: int | None = None,
    detail: Any = None,
    body_status: str | None = None,
    body_code: str | None = None,
    body_error: str | None = None,
    **extra,
) -> tuple[dict[str, Any], int]:
    """Build the shared failure body and resolved HTTP status without Flask."""
    resolved_status = status if status is not None else ERROR_CODES.get(code, 400)
    text = str(message or '').strip() or 'Request failed'
    body: dict[str, Any] = dict(extra)
    body.update({
        'ok': False,
        'error': body_error if body_error is not None else text,
        'error_code': code,
        'message': text,
        'success': False,
    })
    if detail is not None:
        body['detail'] = detail
    if body_status is not None:
        body['status'] = body_status
    if body_code is not None:
        body['code'] = body_code
    return body, resolved_status
