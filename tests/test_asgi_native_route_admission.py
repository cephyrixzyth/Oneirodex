"""The dispatcher admits native requests from the native app's own route table.

``LazyASGIApp._is_native_read_api_request`` decides whether a request goes to
the native FastAPI app ahead of the shell, admin-pilot and method-not-allowed
branches. It used to be an 830-line chain of hand-written path predicates that
every feature had to extend; it now asks the app's routes. These tests pin
the contract: every mounted route and method is admitted, while unknown paths
and unsupported methods are not (so those later branches still answer them).

The route walk also guards a FastAPI upgrade: if route matching changes shape
(``_IncludedRouter`` arrived in 0.16x), the first test fails instead of every
native request quietly falling through.
"""
from __future__ import annotations

import re

from fastapi.routing import APIRoute

_PARAM = re.compile(r'\{([^}:]+)(?::([^}]+))?\}')


def _sample_path(template: str) -> str:
    def value(match):
        kind = match.group(2)
        if kind == 'int':
            return '1'
        if kind == 'path':
            return 'sample/one'
        if kind == 'uuid':
            return '123e4567-e89b-12d3-a456-426614174000'
        if kind == 'float':
            return '1.5'
        return 'sample-1'
    return _PARAM.sub(value, template)


def _api_routes(routes, prefix=''):
    """Yield (full path template, route), unwrapping included routers."""
    for route in routes:
        original = getattr(route, 'original_router', None)
        if original is not None:
            context = getattr(route, 'include_context', None)
            yield from _api_routes(original.routes, prefix + getattr(context, 'prefix', ''))
        elif isinstance(route, APIRoute):
            yield prefix + route.path, route


def _runtime(client):
    client.get('/api/chat/channels')
    runtime = client._app
    assert runtime._native_read_api_app is not None
    return runtime


def test_every_native_route_and_method_is_admitted(client):
    runtime = _runtime(client)
    routes = list(_api_routes(runtime._native_read_api_app.routes))
    assert len(routes) > 500
    refused = sorted(
        (method, template)
        for template, route in routes
        for method in route.methods or ()
        if not runtime._is_native_read_api_request(_sample_path(template), {'method': method})
    )
    assert refused == []


def test_unknown_paths_and_unsupported_methods_are_left_to_later_branches(client):
    runtime = _runtime(client)
    admitted = runtime._is_native_read_api_request
    assert not admitted('/api/not-a-real-route', {'method': 'GET'})
    assert not admitted('/library-not-a-route', {'method': 'POST'})
    # Room-game progress exists for GET/HEAD/PUT/DELETE only.
    assert admitted('/api/room-games/moonfall-pinball/progress', {'method': 'PUT'})
    assert not admitted('/api/room-games/moonfall-pinball/progress', {'method': 'POST'})
