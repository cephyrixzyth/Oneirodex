"""Declarative JSON request validation for API routes (wave A2.4).

Why this exists
---------------
324 API routes hand-roll the same three lines::

    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return api_error('A name is required', code='bad_request')

Every one picks its own message, its own ``error_code`` and its own idea of
what "missing" means (``None``? ``''``? whitespace? wrong type?). The SPA
cannot render a shared field-error state against that.

``@validate_body(Model)`` replaces the boilerplate with a pydantic model. On a
bad body it returns **one** shape — ``api_error('Invalid request.',
code='unprocessable', detail={field: message})`` (HTTP 422) — and on a good
body it hands the parsed, typed model to the view as the ``body`` keyword
argument::

    @apis_bp.route('/collections', methods=['POST'])
    @login_required
    @validate_body(CreateCollectionBody)
    def create_collection(body: CreateCollectionBody):
        name = body.name[:120]
        ...

Partial-success batch routes use ``@validate_batch_body`` instead, which is
the same 422 plus ``updated`` / ``skipped`` / ``errors`` (and optional
``limit``) so the SPA's batch envelope does not go blank.

Decorator order
---------------
``@validate_body`` must sit **innermost** — directly above ``def`` and below
every auth decorator (``@login_required`` / ``@librarian_required`` / ...).
Decorators apply bottom-up, so at call time auth runs first and validation
second: an unauthenticated caller is refused before the body is even looked at.
A ``@validate_body`` route with no auth decorator above it is a bug.

Malformed / absent body
-----------------------
``request.get_json(silent=True)`` returns ``None`` for a missing body, a body
that is not JSON, or a syntactically broken body. All three are treated the
same: validate ``{}`` against the model. A model with required fields then
yields a 422 naming those fields; a model whose fields are all optional
accepts it. A body that parses to JSON but is not an object (``[]``, ``"x"``,
``5``) also lands as a 422, not a 500.

Security
--------
``detail`` carries only ``{field: message}`` built from pydantic's own short
messages ("Field required", "Input should be a valid string", "Extra inputs
are not permitted", ...). The offending ``input`` value, pydantic's help
``url`` and any ``ctx`` object are dropped, so no request data, stack frame or
filesystem path can ride out in the envelope — the same rule
``oneirodex/utils/api_response.py`` documents for ``detail``.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from oneirodex.utils.api_response import api_error

__all__ = [
    'validate_body', 'validate_batch_body', 'format_validation_errors', 'read_json_body'
]


def _loc_to_field(loc: tuple[Any, ...]) -> str:
    """Turn a pydantic error ``loc`` tuple into a dotted field name.

    ``('name',)`` -> ``'name'``
    ``('items', 0, 'id')`` -> ``'items[0].id'``
    ``()`` (whole-body error) -> ``'__root__'``
    """
    parts: list[str] = []
    for entry in loc:
        if isinstance(entry, int):
            parts.append(f'[{entry}]')
        elif parts:
            parts.append(f'.{entry}')
        else:
            parts.append(str(entry))
    field = ''.join(parts).lstrip('.')
    return field or '__root__'


def format_validation_errors(exc: ValidationError) -> dict[str, Any]:
    """Compact ``{field: message}`` (or ``{field: [messages]}``) for the client.

    Deliberately omits ``input``, ``url`` and ``ctx`` from every entry: those
    are the parts that can echo request data or environment detail back to the
    browser.
    """
    out: dict[str, Any] = {}
    for err in exc.errors():
        field = _loc_to_field(tuple(err.get('loc') or ()))
        message = str(err.get('msg') or 'Invalid value')
        if field in out:
            existing = out[field]
            if isinstance(existing, list):
                existing.append(message)
            else:
                out[field] = [existing, message]
        else:
            out[field] = message
    return out


def _json_object(*, empty_if_missing: bool = True) -> Any:
    """Read JSON, optionally normalizing a missing or malformed body to ``{}``."""
    try:
        from flask import request
    except ImportError:  # Native routes parse their ASGI request explicitly.
        request = None
    payload = request.get_json(silent=True) if request is not None else None
    return payload if payload is not None or not empty_if_missing else {}


def read_json_body() -> Any:
    """Read raw JSON for authenticated routes that also accept multipart forms.

    These mixed-content routes keep their existing business validation in the
    view because a JSON-only model decorator cannot validate their form branch.
    New JSON-only endpoints should use :func:`validate_body` instead.
    """
    return _json_object(empty_if_missing=False)


def _refuse_unprocessable(
    exc: ValidationError, extra: Mapping[str, Any] | None = None
):
    kwargs: dict[str, Any] = dict(extra) if extra else {}
    return api_error(
        'Invalid request.',
        code='unprocessable',
        detail=format_validation_errors(exc),
        **kwargs,
    )


def validate_body(
    model: type[BaseModel], *,
    methods: set[str] | frozenset[str] | None = None,
    on_error: Callable[[ValidationError], Any] | None = None,
) -> Callable:
    """Validate the JSON request body against ``model`` before the view runs.

    On success the parsed model instance is injected as the ``body`` keyword
    argument. By default, a :class:`pydantic.ValidationError` returns
    ``api_error('Invalid request.', code='unprocessable', detail=...)`` with
    HTTP 422. ``on_error`` can preserve a route's established error contract;
    ``methods`` can limit validation to selected methods on a multi-method view.
    """

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            if methods is not None:
                from flask import request

                if request.method.upper() not in methods:
                    return view(*args, **kwargs)
            try:
                validated = model.model_validate(_json_object())
            except ValidationError as exc:
                if on_error is not None:
                    return on_error(exc)
                return _refuse_unprocessable(exc)
            kwargs['body'] = validated
            return view(*args, **kwargs)

        return wrapper

    return decorator


def validate_batch_body(
    model: type[BaseModel],
    *,
    limit: int | None = None,
    extra_on_error: Mapping[str, Any] | None = None,
) -> Callable:
    """Like :func:`validate_body`, but a 422 keeps partial-success keys.

    Batch routes (``/api/games/batch/*``, unmatched ``batch/*``, …) put
    ``updated`` / ``skipped`` / ``errors`` (and usually ``limit``) on *every*
    response, including a malformed-body refusal. ``member-app``
    ``api/batchActions.ts`` reads those keys. The flat ``@validate_body`` 422
    would drop them.

    Do **not** use this on ordinary named-field routes — those stay on
    ``validate_body``. Do **not** wrap a skip-list partial-success route with
    ``validate_body``.

    ``limit`` is stamped on the 422 when the route has a documented cap.
    ``extra_on_error`` merges extra keys (``cap``, ``requested``, …) onto that
    same refusal. Semantic / over-limit checks stay in the view.
    """

    extras: dict[str, Any] = {
        'updated': [],
        'skipped': [],
        'errors': [],
    }
    if limit is not None:
        extras['limit'] = limit
    if extra_on_error:
        extras.update(dict(extra_on_error))

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            try:
                validated = model.model_validate(_json_object())
            except ValidationError as exc:
                return _refuse_unprocessable(exc, extras)
            kwargs['body'] = validated
            return view(*args, **kwargs)

        return wrapper

    return decorator
