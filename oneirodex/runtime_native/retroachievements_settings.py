"""Native session routes for RetroAchievements settings and member handle."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class RetroAchievementsSettingsBody(BaseModel, extra='forbid'):
    username: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False


class MemberRetroAchievementsBody(BaseModel, extra='forbid'):
    ra_username: str = Field(default='', max_length=64)


class RetroAchievementsMatchBody(BaseModel, extra='forbid'):
    platform: str = Field(min_length=1, max_length=32)
    rehash: bool = False


class RetroAchievementsSettingsData:
    def settings(self):
        from oneirodex.utils.retroachievements import settings_summary
        return settings_summary()

    def save_settings(self, *, username, api_key, clear_api_key):
        from oneirodex.utils.retroachievements import save_settings
        return save_settings(username=username, api_key=api_key, clear_api_key=clear_api_key)

    def status(self):
        from oneirodex.utils.retroachievements import status_summary
        return status_summary()

    def configured(self):
        from oneirodex.utils.retroachievements import configured
        return configured()

    def member(self, user):
        prefs = getattr(user, 'preferences', None)
        return {'ra_username': (getattr(prefs, 'ra_username', None) or '') or None,
                'configured': self.configured()}

    def save_member(self, user, name):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserPreference

        prefs = getattr(user, 'preferences', None)
        if prefs is None:
            prefs = UserPreference(user_id=user.id)
            db.session.add(prefs)
        prefs.ra_username = name or None
        db.session.commit()
        return {'ra_username': prefs.ra_username, 'configured': self.configured()}

    def game(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def can_access_game(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game
        return user_can_access_game(user, game)

    def achievement_fields(self, game):
        from oneirodex.utils.retroachievements import achievement_fields
        return achievement_fields(game)

    def progress(self, username, game_id):
        from oneirodex.utils.retroachievements import fetch_member_progress
        return fetch_member_progress(username, game_id)

    def supported_platforms(self):
        from oneirodex.utils.retroachievements import supported_platforms
        return supported_platforms()

    def match_platform(self, platform, *, rehash):
        from oneirodex.utils.retroachievements import match_platform
        return match_platform(platform, rehash=rehash)


def create_retroachievements_settings_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or RetroAchievementsSettingsData()
    routes = {
        '/api/admin/integrations/retroachievements': ('settings', True),
        '/api/retroachievements/status': ('status', True),
        '/api/retroachievements/match': ('match', True),
        '/api/me/retroachievements': ('member', False),
    }

    @router.api_route('/api/admin/integrations/retroachievements', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/retroachievements/status', methods=['GET', 'HEAD'])
    @router.post('/api/retroachievements/match')
    @router.api_route('/api/me/retroachievements', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/games/{game_uuid}/achievements', methods=['GET', 'HEAD'])
    async def retroachievements(request: Request, game_uuid: str | None = None):
        if game_uuid is not None:
            return _game_achievements(request, flask_app, data, find_user,
                                      find_token, commit_token_touch,
                                      load_user_id, login_manager, database_scope,
                                      game_uuid)
        operation, admin_only = routes[request.url.path]
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method in {'POST', 'PUT'}:
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie
                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            if csrf_response is not None:
                response = csrf_response
            else:
                user = auth.user
                is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                if user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
                elif admin_only and not is_admin:
                    response = _login_redirect(flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.', category='danger', include_next=False)
                elif admin_only and auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                elif request.method == 'PUT':
                    body = await _read_json(request)
                    try:
                        if body is None:
                            raise ValueError('Request body must be a JSON object')
                        if operation == 'settings':
                            model = RetroAchievementsSettingsBody.model_validate(body)
                            username = model.username.strip() if model.username is not None else None
                            if username and not all(ch.isalnum() or ch in '_-.' for ch in username):
                                raise ValueError('Username may only contain letters, digits, _ - .')
                            api_key = model.api_key.strip() if model.api_key is not None else None
                            result = data.save_settings(username=username, api_key=api_key,
                                                        clear_api_key=model.clear_api_key)
                        else:
                            model = MemberRetroAchievementsBody.model_validate(body)
                            name = model.ra_username.strip()
                            if name and not all(ch.isalnum() or ch in '_-.' for ch in name):
                                raise ValueError('Username may only contain letters, digits, _ - .')
                            result = data.save_member(user, name)
                        response = JSONResponse(api_ok_payload(result))
                        if auth.should_set_session_cookie:
                            _set_session_cookie(response, flask_app, auth)
                    except (ValidationError, ValueError) as exc:
                        message = str(exc) if isinstance(exc, ValueError) else 'Invalid RetroAchievements settings.'
                        payload, status = api_error_payload(message, code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        db.session.rollback()
                        payload, status = api_error_payload('Could not save RetroAchievements settings.', code='internal')
                        response = JSONResponse(payload, status_code=status)
                elif operation == 'match':
                    media_type = str(request.headers.get('content-type') or '').partition(';')[0].strip().lower()
                    is_json = media_type == 'application/json' or (
                        media_type.startswith('application/') and media_type.endswith('+json')
                    )
                    body = await _read_json(request) if is_json else None
                    try:
                        # Match the legacy validate_body contract: absent,
                        # malformed, and non-object JSON validate as an empty
                        # object and return a safe 422 field-error envelope.
                        model = RetroAchievementsMatchBody.model_validate(
                            body if isinstance(body, dict) else {}
                        )
                        if not data.configured():
                            payload, status = api_error_payload(
                                'RetroAchievements is not configured — save the household username and web API key under Admin → Integrations.',
                                code='forbidden',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            platform = model.platform.strip().upper()
                            supported = data.supported_platforms()
                            if platform not in supported:
                                payload, status = api_error_payload(
                                    f'{platform} is not a system this build can hash for RetroAchievements',
                                    code='bad_request', supported=supported,
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                response = JSONResponse(api_ok_payload(
                                    data.match_platform(platform, rehash=model.rehash)
                                ))
                    except ValidationError as exc:
                        from oneirodex.utils.validation import format_validation_errors
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except RuntimeError as exc:
                        payload, status = api_error_payload(str(exc), code='forbidden')
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        db.session.rollback()
                        import logging
                        logging.getLogger(__name__).warning('RetroAchievements lookup failed')
                        payload, status = api_error_payload(
                            'RetroAchievements lookup failed. Try again later.', code='upstream'
                        )
                        response = JSONResponse(payload, status_code=status)
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
                else:
                    try:
                        result = data.settings() if operation == 'settings' else data.status() if operation == 'status' else data.member(user)
                        response = JSONResponse(api_ok_payload(result))
                        if auth.should_set_session_cookie:
                            _set_session_cookie(response, flask_app, auth)
                    except Exception:
                        payload, status = api_error_payload('Could not load RetroAchievements settings.', code='internal')
                        response = JSONResponse(payload, status_code=status)
        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def _game_achievements(request, flask_app, data, find_user, find_token,
                       commit_token_touch, load_user_id, login_manager,
                       database_scope, game_uuid):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
        )
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        if auth.user is None:
            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'),
                include_next=True,
            )
        else:
            game = data.game(game_uuid)
            if game is None:
                payload, status = api_error_payload('Game not found', code='not_found')
                response = JSONResponse(payload, status_code=status)
            elif not data.can_access_game(auth.user, game):
                payload, status = api_error_payload('Forbidden', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            else:
                fields = data.achievement_fields(game)
                prefs = getattr(auth.user, 'preferences', None)
                username = (getattr(prefs, 'ra_username', None) or '').strip()
                progress = None
                if fields['supports_achievements'] and username:
                    progress = data.progress(username, fields['ra_game_id'])
                payload, status = api_ok_payload({
                    **fields, 'configured': data.configured(),
                    'ra_username': username or None, 'unlocks_here': False,
                    'me': progress,
                }), 200
                response = JSONResponse(payload, status_code=status)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


async def _read_json(request):
    import json
    try:
        length = int(request.headers.get('content-length') or '0')
        if length > 8 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 8 * 1024:
                return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def mount_retroachievements_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_retroachievements_settings_router(flask_app, **kwargs))
    return app
