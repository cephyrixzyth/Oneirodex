"""Preserve configured cookie flags on Python 3.12 and newer runtimes."""
from __future__ import annotations

from typing import Any

from starlette.responses import Response


def _mark_partitioned(response: Response) -> None:
    # Starlette appends one Set-Cookie header synchronously. Its stdlib-backed
    # Partitioned argument requires Python 3.14, although the HTTP flag does not.
    # Keep Starlette's value escaping and append only this fixed attribute.
    name, value = response.raw_headers[-1]
    response.raw_headers[-1] = (name, value + b'; Partitioned')


def set_cookie(
    response: Response, key: str, value: str = '', *, partitioned: bool = False,
    **kwargs: Any,
) -> None:
    if partitioned:
        # Match Flask/Werkzeug: partitioned cookies always require Secure.
        kwargs['secure'] = True
    response.set_cookie(key, value, **kwargs)
    if partitioned:
        _mark_partitioned(response)


def delete_cookie(
    response: Response, key: str, *, partitioned: bool = False, **kwargs: Any,
) -> None:
    if partitioned:
        kwargs['secure'] = True
    response.delete_cookie(key, **kwargs)
    if partitioned:
        _mark_partitioned(response)
