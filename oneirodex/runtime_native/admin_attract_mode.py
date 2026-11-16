"""Native admin read/write API for attract-mode settings."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import json
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

_DEFAULT_IDLE_TIMEOUT = 60
_BOUNDS = {
    'idle_timeout': {'min': 10, 'max': 300},
    'skipFirst': {'min': 0, 'max': 300},
    'skipAfter': {'min': 0, 'max': 600},
    'year': {'min': 1, 'max': 9999},
}


class AdminAttractModeData:
    def state(self, settings):
        from oneirodex.utils.attract_mode_defaults import DEFAULT_ATTRACT_MODE_SETTINGS

        config = deepcopy(DEFAULT_ATTRACT_MODE_SETTINGS)
        saved = getattr(settings, 'attract_mode_settings', None) if settings else None
        if isinstance(saved, dict):
            for key in ('filters', 'autoplay'):
                if isinstance(saved.get(key), dict):
                    config[key].update(saved[key])
        return {
            'enabled': bool(settings and settings.attract_mode_enabled),
            'idle_timeout': (settings.attract_mode_idle_timeout or _DEFAULT_IDLE_TIMEOUT) if settings else _DEFAULT_IDLE_TIMEOUT,
            'filters': config['filters'], 'autoplay': config['autoplay'],
        }

    def read_settings(self):
        from oneirodex.utils.global_settings import global_settings_row
        return global_settings_row()

    def filter_options(self):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Genre, Library, Theme

        libraries = db.session.execute(select(Library).order_by(Library.display_order, Library.name)).scalars().all()
        genres = db.session.execute(select(Genre).order_by(Genre.name)).scalars().all()
        themes = db.session.execute(select(Theme).order_by(Theme.name)).scalars().all()
        dates = db.session.execute(select(func.min(Game.first_release_date), func.max(Game.first_release_date)).filter(
            Game.video_urls.isnot(None), Game.video_urls != '', Game.first_release_date.isnot(None),
        )).first()
        return {
            'libraries': [{'uuid': str(row.uuid), 'name': row.name} for row in libraries],
            'genres': [{'id': row.id, 'name': row.name} for row in genres],
            'themes': [{'id': row.id, 'name': row.name} for row in themes],
            'date_range': {
                'min_year': dates[0].year if dates and dates[0] else None,
                'max_year': dates[1].year if dates and dates[1] else None,
            },
        }

    def save(self, user, body):
        from datetime import datetime, timezone
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.global_settings import global_settings_row_or_create
        from oneirodex.utils.attract_mode_defaults import DEFAULT_ATTRACT_MODE_SETTINGS

        settings = global_settings_row_or_create()
        settings.attract_mode_enabled = body.get('enabled', False)
        settings.attract_mode_idle_timeout = int(body.get('idle_timeout', _DEFAULT_IDLE_TIMEOUT))
        settings.attract_mode_settings = {
            'filters': body.get('filters', DEFAULT_ATTRACT_MODE_SETTINGS['filters']),
            'autoplay': body.get('autoplay', DEFAULT_ATTRACT_MODE_SETTINGS['autoplay']),
        }
        settings.last_updated = datetime.now(timezone.utc)
        db.session.commit()
        cache.clear()
        log_system_event(
            f'Attract mode settings updated by {getattr(user, "name", "administrator")}',
            event_type='configuration', event_level='information', audit_user=user.id,
        )
        return settings


def create_admin_attract_mode_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminAttractModeData()

    @router.api_route('/admin/attract_mode_settings', methods=['POST'])
    @router.api_route('/api/admin/attract-mode/settings', methods=['GET', 'HEAD', 'PUT'])
    async def settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf = None
            if request.method in ('PUT', 'POST'):
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie
                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf = csrf_error_response(request, session, flask_app.config)
            auth = None
            if csrf is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            if csrf is not None:
                response = csrf
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif request.method in ('PUT', 'POST'):
                body = await _read_json(request)
                try:
                    from oneirodex.schemas.attract_mode import AttractModeBody
                    model = AttractModeBody.model_validate(body)
                    settings_row = data.save(auth.user, model.model_dump())
                    response = JSONResponse(api_ok_payload({
                        'settings': data.state(settings_row),
                        'message': 'Attract mode settings saved successfully',
                    }))
                except ValidationError as exc:
                    fields = [
                        {'field': '.'.join(str(part) for part in error['loc']), 'message': error['msg']}
                        for error in exc.errors(include_input=False, include_context=False, include_url=False)
                    ]
                    payload, status = api_error_payload(
                        'Check attract mode settings and try again', code='bad_request', detail=fields,
                    )
                    response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    logging.getLogger(__name__).warning('Could not save admin attract mode settings')
                    payload, status = api_error_payload('Could not save attract mode settings', code='internal')
                    response = JSONResponse(payload, status_code=status)
            else:
                try:
                    response = JSONResponse(api_ok_payload({
                        'settings': data.state(data.read_settings()),
                        'filter_options': data.filter_options(),
                        'bounds': _BOUNDS,
                    }))
                except Exception:
                    logging.getLogger(__name__).warning('Could not load admin attract mode settings')
                    payload, status = api_error_payload('Could not load attract mode settings', code='internal')
                    response = JSONResponse(payload, status_code=status)
            if auth is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_admin_attract_mode_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_attract_mode_router(flask_app, **kwargs))
    return app


async def _read_json(request: Request):
    try:
        if int(request.headers.get('content-length') or '0') > 16 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16 * 1024:
                return None
        value = json.loads(raw) if raw else None
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None
