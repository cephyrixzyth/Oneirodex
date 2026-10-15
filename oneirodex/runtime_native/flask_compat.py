"""Narrow compatibility bridge for FastAPI routes using Flask-owned sessions.

This lets opt-in native route pilots reuse Flask's request hooks, signed
session, CSRF and response processing while the application is migrated in
bounded steps. It is transitional infrastructure, not a replacement runtime.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response
from werkzeug.test import EnvironBuilder


def dispatch_flask_request(flask_app, request: Request, handler) -> Response:
    """Run a synchronous handler in Flask's existing request/session context."""
    builder = EnvironBuilder(
        path=request.url.path,
        query_string=request.url.query,
        base_url=f'{request.url.scheme}://{request.url.netloc}/',
        method=request.method,
        headers=list(request.headers.items()),
        environ_base={'REMOTE_ADDR': request.client.host if request.client else ''},
    )
    try:
        environ = builder.get_environ()
        # request_context skips app.wsgi_app. Apply ProxyFix only after the
        # immediate ASGI peer has matched the configured proxy CIDRs.
        from oneirodex.utils.proxy import parse_trusted_proxy_count
        from oneirodex.utils.trusted_proxy import trusted_proxy_peer
        from werkzeug.middleware.proxy_fix import ProxyFix

        count = parse_trusted_proxy_count(flask_app.config.get('TRUSTED_PROXIES', 0))
        if count and trusted_proxy_peer(request, flask_app.config):
            ProxyFix(
                lambda env, start: (),
                x_for=count,
                x_proto=count,
                x_host=count,
                x_prefix=count,
            )(environ, lambda *args: None)

        with flask_app.request_context(environ):
            finalized = False
            try:
                try:
                    early = flask_app.preprocess_request()
                    value = early if early is not None else handler()
                except Exception as error:
                    value = flask_app.handle_user_exception(error)
                response = flask_app.make_response(value)
            except Exception as error:
                # handle_exception runs Flask's 500 handler and finalizes hooks.
                response = flask_app.handle_exception(error)
                finalized = True
            if not finalized:
                response = flask_app.process_response(response)
            response.headers['Cache-Control'] = 'no-store'
            result = Response(response.get_data(), status_code=response.status_code)
            # Preserve repeated Set-Cookie headers and existing security/Vary
            # headers while adapting the WSGI response to Starlette.
            result.raw_headers = [
                (key.lower().encode('latin-1'), value.encode('latin-1'))
                for key, value in response.headers.to_wsgi_list()
            ]
            return result
    finally:
        builder.close()
