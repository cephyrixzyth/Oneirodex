"""Small request-query compatibility helpers for Flask-to-ASGI routes."""
from __future__ import annotations


def first_query_value(query_params, key, default=None):
    """Match Flask MultiDict.get(), which selects the first repeated value."""
    values = query_params.getlist(key)
    return values[0] if values else default
