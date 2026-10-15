"""Native FastAPI routes for the member UI locale preference."""
from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from oneirodex.utils.locale_core import SUPPORTED_LOCALES, normalize_locale

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


_logger = logging.getLogger(__name__)


class LocaleData:
    """Read and persist a member's locale using the established ORM model."""

    def get(self, user) -> str:
        preferences = getattr(user, 'preferences', None)
        return normalize_locale(getattr(preferences, 'locale', None))

    def set(self, user, locale: str) -> None:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserPreference

        preferences = db.session.execute(
            select(UserPreference).filter_by(user_id=user.id),
        ).scalars().first()
        if preferences is None:
            preferences = UserPreference(user_id=user.id, locale=locale)
            db.session.add(preferences)
        else:
            preferences.locale = locale
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def create_locale_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access if data_access is not None else LocaleData()

    @router.api_route('/api/locale', methods=['GET', 'HEAD', 'POST'])
    async def locale(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if request.method == 'POST':
                csrf_response = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                )
                if csrf_response is not None:
                    response = csrf_response
                elif auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                else:
                    chosen = normalize_locale(await _locale_from_request(request))
                    try:
                        data.set(auth.user, chosen)
                    except Exception:
                        _logger.exception('Failed to save UI locale')
                        from oneirodex.utils.api_contract import api_error_payload

                        payload, status = api_error_payload(
                            'Locale could not be saved.', code='internal',
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        auth.session_data['locale'] = chosen
                        response = JSONResponse(_payload(chosen))
                        response.set_cookie(
                            'gt_locale', chosen,
                            max_age=365 * 24 * 3600,
                            samesite='Lax',
                        )
                        _set_session_cookie(response, flask_app, auth)
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                response = JSONResponse(_payload(data.get(auth.user)))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_locale_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_locale_router(flask_app, **kwargs))
    return app


async def _locale_from_request(request: Request) -> str | None:
    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type == 'multipart/form-data':
        try:
            form = await request.form()
        except (ValueError, RuntimeError):
            return None
        return form.get('locale')

    raw = await request.body()
    if content_type == 'application/json':
        try:
            payload = json.loads(raw or b'{}')
        except (TypeError, ValueError):
            payload = {}
        return payload.get('locale') if isinstance(payload, Mapping) else None

    values = parse_qs(raw.decode('utf-8', 'replace'), keep_blank_values=True)
    return values.get('locale', [None])[0]


def _payload(locale: str) -> dict[str, Any]:
    return {'locale': locale, 'supported': list(SUPPORTED_LOCALES)}
