"""Permit bundled native webviews to call the authenticated HTTP API."""
from functools import wraps

from starlette.middleware.cors import CORSMiddleware


NATIVE_COMPANION_ORIGINS = (
    'tauri://localhost',
    'http://tauri.localhost',
    'https://tauri.localhost',
)


def native_companion_cors(handler):
    """Cover direct ASGI dispatch and errors; retain ordinary route auth/CSRF.

    Native callers supply a Bearer token. This policy never enables browser
    cookie credentials, arbitrary web origins, opaque ``null`` origins or
    development-server ports. CORS grants no authentication or route access.
    """
    @wraps(handler)
    async def wrapped(instance, scope, receive, send):
        async def dispatch(inner_scope, inner_receive, inner_send):
            await handler(instance, inner_scope, inner_receive, inner_send)

        middleware = CORSMiddleware(
            dispatch,
            allow_origins=NATIVE_COMPANION_ORIGINS,
            allow_methods=('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'),
            allow_headers=('Authorization', 'Content-Type', 'Range', 'If-Range', 'X-Oneirodex-Resume'),
            expose_headers=('ETag', 'Content-Range', 'Accept-Ranges'),
            allow_credentials=False,
        )
        await middleware(scope, receive, send)

    return wrapped
