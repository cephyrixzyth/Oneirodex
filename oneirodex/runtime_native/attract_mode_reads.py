"""Native public Attract Mode settings read, including signed-session overrides."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from copy import deepcopy
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _set_session_cookie
from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .request_auth import request_auth_context

_logger = logging.getLogger(__name__)
_FALLBACK = {'enabled': False, 'idle_timeout': 0, 'settings': None}


class AttractModeData:
    def __init__(self, *, global_reader=None, user_reader=None):
        self.global_reader = global_reader or self._global_reader
        self.user_reader = user_reader or self._user_reader

    @staticmethod
    def _global_reader():
        from oneirodex.utils.global_settings import global_settings_row

        return global_settings_row()

    @staticmethod
    def _user_reader(user_id):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserAttractModeSettings

        return db.session.execute(
            select(UserAttractModeSettings).filter_by(user_id=user_id)
        ).scalar_one_or_none()

    def payload(self, user: Any | None) -> dict:
        global_settings = self.global_reader()
        if not global_settings or not global_settings.attract_mode_enabled:
            return dict(_FALLBACK)

        settings = deepcopy(
            global_settings.attract_mode_settings
            or self._default_settings()
        )
        result = {
            'enabled': True,
            'idle_timeout': global_settings.attract_mode_idle_timeout,
            'settings': settings,
        }
        if user is not None:
            user_settings = self.user_reader(getattr(user, 'user_id', None))
            if user_settings and user_settings.has_customized:
                if user_settings.filter_settings:
                    result['settings']['filters'] = user_settings.filter_settings
                if user_settings.autoplay_settings:
                    result['settings']['autoplay'] = user_settings.autoplay_settings
        return result

    def save_override(self, user: Any, data: dict) -> None:
        from datetime import datetime, timezone

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserAttractModeSettings
        from oneirodex.utils.event_logging import log_system_event

        user_settings = self.user_reader(getattr(user, 'user_id', None))
        if not user_settings:
            user_settings = UserAttractModeSettings(user_id=user.user_id)
            db.session.add(user_settings)

        user_settings.has_customized = True
        if 'filters' in data:
            user_settings.filter_settings = data['filters']
        if 'autoplay' in data:
            user_settings.autoplay_settings = data['autoplay']
        user_settings.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        log_system_event(
            f'User {user.name} customized attract mode settings',
            event_type='user_preference',
            event_level='information',
            audit_user=user.id,
        )

    @staticmethod
    def rollback():
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    @staticmethod
    def _default_settings():
        from oneirodex.utils.attract_mode_defaults import DEFAULT_ATTRACT_MODE_SETTINGS

        return DEFAULT_ATTRACT_MODE_SETTINGS


def create_attract_mode_router(
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
    data = data_access or AttractModeData()

    def finish(response: Response, request: Request, auth=None):
        if auth is not None and auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.api_route('/api/attract-mode/settings', methods=['GET', 'HEAD'])
    def public_attract_mode_settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            try:
                payload = data.payload(auth.user)
            except Exception as exc:  # noqa: BLE001 — the legacy public route degrades safely
                _logger.error('Error fetching public Attract Mode settings: %s', type(exc).__name__)
                payload = dict(_FALLBACK)

            return finish(JSONResponse(payload), request, auth)

    @router.post('/api/attract-mode/user-override')
    async def save_user_override(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie

            session_data = load_session_cookie(
                request.cookies.get(cookie_name),
                flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(
                    flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                ),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(request, session_data, flask_app.config)
            if response is not None:
                return finish(response, request)

            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                return finish(
                    _login_redirect(flask_app, request, login_manager, auth), request, auth,
                )

            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 — mirrors Flask get_json failure handling
                body = None
            if not isinstance(body, dict) or not body:
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload('No data provided', code='bad_request')
                return finish(JSONResponse(payload, status_code=status), request, auth)

            try:
                data.save_override(auth.user, body)
            except Exception:  # noqa: BLE001 — don't expose settings or DB details
                rollback = getattr(data, 'rollback', None)
                if callable(rollback):
                    rollback()
                _logger.exception('Could not save Attract Mode user preferences')
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload(
                    'Could not save your attract mode preferences', code='internal',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'message': 'Your attract mode preferences have been saved',
                }))
            return finish(response, request, auth)

    return router


def mount_attract_mode_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_attract_mode_router(flask_app, **kwargs))
    return app
