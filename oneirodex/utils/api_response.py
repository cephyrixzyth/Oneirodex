"""One JSON envelope for every API response (GT-B1).

Why this exists
---------------
Before this module there were ~699 ``jsonify`` call sites across ~72 route
files using at least five competing shapes for the same idea::

    jsonify({'error': 'Admin required'}), 403
    jsonify({'message': 'Saved'})
    jsonify({'status': 'ok'})
    jsonify({'success': True})
    jsonify({'ok': False, ...})

``oneirodex/routes.py`` alone used four of them. The cost landed on the
frontend: a shared error component is impossible when every call site reports
failure differently, which is why the SPA had no error state at all and each
page improvised its own.

Compatibility contract
----------------------
This is deliberately **additive**. The envelope keeps ``error`` as a plain
human-readable string — the dominant legacy shape — and mirrors ``message`` and
``success`` alongside it. Any existing caller reading ``data.error``,
``data.message`` or ``data.success`` keeps working unchanged, so routes can be
migrated one at a time instead of in a single risky sweep.

New clients should read:

``ok``
    Boolean. The only field guaranteed present on every response.
``error``
    Human-readable sentence, safe to show a household member. ``None`` on success.
``error_code``
    Stable machine token (``snake_case``) for branching. Never shown to users.
``detail``
    Optional structured extra for operators (field errors, upstream status).
    Never rendered as the headline.

Security
--------
``detail`` is passed through as given, so callers must not put secrets, tokens,
raw ``.env`` values or full filesystem paths in it — the same rule the rest of
the codebase follows for scrubbed logging.
"""

from __future__ import annotations

from typing import Any, Mapping

from oneirodex.utils.api_contract import ERROR_CODES, api_error_payload, api_ok_payload

__all__ = ['api_ok', 'api_error', 'ERROR_CODES']


def api_ok(payload: Mapping[str, Any] | None = None, *, status: int = 200, **extra):
    """Success envelope.

    ``payload`` is merged at the top level so existing response bodies keep
    their current field names — callers migrating a route do not have to move
    their data under a new ``data`` key.

    Reserved keys (``ok``, ``error``, ``error_code``) are not overridable; a
    payload carrying them would defeat the point of a stable envelope.
    """
    from flask import jsonify

    return jsonify(api_ok_payload(payload, **extra)), status


def api_error(
    message: str,
    *,
    code: str = 'bad_request',
    status: int | None = None,
    detail: Any = None,
    body_status: str | None = None,
    body_code: str | None = None,
    body_error: str | None = None,
    **extra,
):
    """Failure envelope.

    ``status`` defaults to the HTTP status mapped from ``code``, so the common
    case is a single argument::

        return api_error('Admin required', code='forbidden')

    An explicit ``status`` still wins, for routes that must keep a specific code
    for backwards compatibility (there are existing 403-vs-503 contracts in the
    AI triage tests that must not shift silently).

    Classic admin JS still branches on a body ``status`` (``error`` /
    ``rejected`` / ``not_found``) and, in a few honesty paths, on body ``code``
    (``path_missing``). Those keys collide with this function's HTTP ``status``
    and envelope ``code`` (``error_code``), so they go through ``body_status``
    / ``body_code``. ``body_error`` is for the handful of callers that put a
    machine token in ``error`` and a human sentence in ``message``.
    """
    body, resolved_status = api_error_payload(
        message,
        code=code,
        status=status,
        detail=detail,
        body_status=body_status,
        body_code=body_code,
        body_error=body_error,
        **extra,
    )
    from flask import jsonify

    return jsonify(body), resolved_status
