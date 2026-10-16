"""FastAPI public-demo sign-in using the existing signed member session."""
from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import PlainTextResponse, RedirectResponse


class PublicDemoData:
    def demo_user(self):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        return db.session.execute(
            select(User).filter_by(name='demo-visitor', role='user', state=True)
        ).scalar_one_or_none()


def create_public_demo_router(
    flask_app: FastAPI,
    *,
    data_access=None,
    database_scope=None,
):
    router = APIRouter()
    data = data_access or PublicDemoData()

    @router.api_route('/demo', methods=['GET', 'HEAD'], include_in_schema=False)
    def public_demo_login(request: Request):
        if os.getenv('ONEIRODEX_PUBLIC_DEMO', '').strip().lower() not in {
            '1', 'true', 'yes', 'on',
        }:
            return _secure_error(flask_app, 'Not found.', 404)

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                demo_user = data.demo_user()
            except Exception:  # noqa: BLE001 — do not expose demo account lookup failures
                return _secure_error(flask_app, 'Demo sign-in is unavailable.', 503)
        if demo_user is None:
            return _secure_error(flask_app, 'Demo sign-in is unavailable.', 503)

        from oneirodex.runtime_native.auth_login import _session_data
        from oneirodex.runtime_native.auth_resolver import session_identifier
        from oneirodex.runtime_native.oidc_status import _set_session_cookie
        from oneirodex.utils.security_headers import security_header_values
        from oneirodex.utils.trusted_proxy import trusted_forwarded_for

        session_data = _session_data(request, flask_app.config)
        session_data['_user_id'] = str(demo_user.get_id())
        session_data['_fresh'] = True
        session_data['_id'] = session_identifier(
            request.client.host if request.client else None,
            request.headers.get('user-agent'),
            trusted_forwarded_for(request, flask_app.config),
        )
        session_data.pop('_remember', None)
        response = RedirectResponse('/discover', status_code=302)
        _set_session_cookie(response, flask_app, SimpleNamespace(session_data=session_data))
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_public_demo_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_public_demo_router(flask_app, **kwargs))
    return app


def _secure_error(flask_app, message: str, status: int):
    from oneirodex.utils.security_headers import security_header_values

    response = PlainTextResponse(message, status_code=status)
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response
