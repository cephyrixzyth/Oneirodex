"""Native admin feature and challenge-solver configuration APIs."""
from __future__ import annotations

from contextlib import nullcontext
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

_FEATURE_DB_FIELDS = (
    'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
    'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
    'allow_children_in_household_lobby',
)
_CHALLENGE_PROVIDERS = {'flaresolverr_compat', 'trawl', 'token_api'}


class AdminFeaturesData:
    def read(self, config):
        from oneirodex.utils.feature_catalog import FEATURE_ENV_TOGGLES
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.challenge_solver import get_challenge_config
        from oneirodex.utils.malware_scan import module_status

        settings = global_settings_row()
        prefs = {
            key: bool(getattr(settings, key, key != 'allow_children_in_household_lobby'))
            for key in _FEATURE_DB_FIELDS
        }
        process = []
        def env_bool(key, default=True):
            raw = os.getenv(key)
            if raw is None or raw == '':
                return bool(config.get(key, default))
            return raw.lower() in ('1', 'true', 'yes', 'on')
        for _form_name, key, label, help_text, _lock in FEATURE_ENV_TOGGLES:
            value = env_bool(key, key not in ('ENABLE_REMOTE_PLAY', 'ENABLE_AMBIENT_LIGHTING'))
            process.append({'key': key, 'label': label, 'help': help_text, 'on': value, 'opt_in': key in {
                'OIDC_ENABLED', 'ENABLE_AI_AUTO_APPLY', 'ALLOW_HARDLINK_APPLY',
                'ENABLE_CHALLENGE_SOLVER', 'ENABLE_AMBIENT_LIGHTING', 'ENABLE_REMOTE_PLAY',
            }})
        process.extend([
            {'key': 'OIDC_ENABLED', 'label': 'OIDC authentication', 'on': env_bool('OIDC_ENABLED', False) or bool(getattr(settings, 'oidc_enabled', False)), 'opt_in': True},
            {'key': 'ENABLE_AI_AUTO_APPLY', 'label': 'AI automatic apply', 'on': env_bool('ENABLE_AI_AUTO_APPLY', False), 'opt_in': True},
            {'key': 'ALLOW_HARDLINK_APPLY', 'label': 'Hardlink apply', 'on': env_bool('ALLOW_HARDLINK_APPLY', False), 'opt_in': True},
            {'key': 'ENABLE_CHALLENGE_SOLVER', 'label': 'Challenge solver', 'on': env_bool('ENABLE_CHALLENGE_SOLVER', False), 'opt_in': True},
        ])
        challenge = get_challenge_config()
        scan = module_status(config=config)
        clamav = scan.get('clamav') or {}
        scan_settings = scan.get('settings') or {}
        scanner = {
            'enabled': bool(scan.get('enabled')),
            'block_on_hit': bool(scan.get('block_on_hit')),
            'heuristics': {
                'enabled': bool((scan.get('heuristics') or {}).get('enabled')),
                'block_on_match': bool((scan.get('heuristics') or {}).get('block_on_match')),
            },
            'clamav': {
                'reachable': bool(clamav.get('reachable')),
                'version': str(clamav.get('version') or '')[:200] if clamav.get('reachable') else '',
                'error': 'Scanner unavailable. Check its connection settings.' if clamav.get('error') else None,
            },
            'settings': {
                'host': scan_settings.get('host'), 'port': scan_settings.get('port'),
                'socket_configured': bool(scan_settings.get('socket')),
            },
        }
        return {
            'preferences': prefs, 'process': process,
            'challenge': {key: challenge.get(key) for key in (
                'enabled', 'env_enabled', 'db_enabled', 'url', 'provider', 'max_tier',
            )},
            'scanner': scanner,
        }

    def save_preferences(self, body):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.global_settings import global_settings_row_or_create

        settings = global_settings_row_or_create()
        for key, value in body.items():
            setattr(settings, key, value)
        db.session.commit()
        return {key: bool(getattr(settings, key, key != 'allow_children_in_household_lobby')) for key in _FEATURE_DB_FIELDS}

    def save_challenge(self, body):
        from oneirodex.utils.challenge_solver import save_challenge_config
        return save_challenge_config(body)

    def test_challenge(self):
        from oneirodex.utils.challenge_solver import challenge_solver_status
        return challenge_solver_status(probe=True)


def create_admin_features_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminFeaturesData()
    opts = dict(flask_app=flask_app, data=data, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
                database_scope=database_scope)

    @router.api_route('/api/admin/features/settings', methods=['GET', 'HEAD', 'PUT'])
    async def feature_settings(request: Request):
        return await _handle(request, **opts, action='settings')

    @router.put('/api/admin/features/challenge')
    async def challenge_save(request: Request):
        return await _handle(request, **opts, action='challenge_save')

    @router.post('/api/admin/features/challenge/test')
    async def challenge_test(request: Request):
        return await _handle(request, **opts, action='challenge_test')

    @router.post('/admin/features')
    async def legacy_feature_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            form, body_error = await _read_form(request)
            response = body_error
            auth = None
            if response is None:
                from .csrf_compat import csrf_error_response
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
                response = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')),
                )
            from oneirodex.utils.role_catalog import normalize_role
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif response is None and auth.token is not None and not auth.has_scope('admin'):
                from oneirodex.utils.api_contract import api_error_payload
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif response is None:
                from .account_avatar_upload import _flash
                body = {
                    key: form.get('db_' + key) == 'on'
                    for key in _FEATURE_DB_FIELDS
                }
                try:
                    data.save_preferences(body)
                    _flash(auth.session_data, 'success', 'Feature preferences saved. Env flags (docker/.env) still override process defaults until restart.')
                    response = RedirectResponse('/admin/features', status_code=302)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    _flash(auth.session_data, 'error', 'Could not save feature preferences.')
                    response = RedirectResponse('/admin/features', status_code=302)
            if auth is not None and (auth.should_set_session_cookie or auth.session_data.get('_flashes')):
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_admin_features_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_features_router(flask_app, **kwargs))
    return app


async def _read_form(request: Request):
    from urllib.parse import parse_qs

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024:
            return {}, Response(status_code=413)
    try:
        fields = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}, Response(status_code=400)
    return {name: values[-1] for name, values in fields.items() if values}, None


async def _handle(request, *, flask_app, data, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager,
                  database_scope, action):
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
            response = _login_redirect(flask_app, request, login_manager, auth,
                message='You must be an admin to access this page.', category='danger', include_next=False)
        elif auth.token is not None and not auth.has_scope('admin'):
            payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        elif action == 'settings' and request.method == 'PUT':
            body = await _read_json(request)
            if (not isinstance(body, dict) or set(body) != set(_FEATURE_DB_FIELDS)
                    or any(type(body[key]) is not bool for key in _FEATURE_DB_FIELDS)):
                payload, status = api_error_payload(
                    'Provide all seven feature preferences as booleans. Process flags cannot be changed here.',
                    code='bad_request',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                try:
                    response = JSONResponse(api_ok_payload({'preferences': data.save_preferences(body)}))
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    payload, status = api_error_payload('Could not save feature preferences', code='internal')
                    response = JSONResponse(payload, status_code=status)
        elif action == 'challenge_save':
            body = await _read_json(request)
            if (not isinstance(body, dict) or set(body) != {'enabled', 'url', 'provider', 'max_tier'}
                    or type(body.get('enabled')) is not bool or not isinstance(body.get('url'), str)
                    or len(body['url']) > 2048 or any(ord(c) < 32 for c in body['url'])
                    or body.get('provider') not in _CHALLENGE_PROVIDERS
                    or type(body.get('max_tier')) is not int or body['max_tier'] < 1):
                payload, status = api_error_payload(
                    'Provide a boolean enable preference, URL, supported provider, and positive integer tier.',
                    code='bad_request',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                try:
                    config = data.save_challenge(body)
                    public = {key: config.get(key) for key in (
                        'enabled', 'env_enabled', 'db_enabled', 'url', 'provider', 'max_tier',
                    )}
                    response = JSONResponse(api_ok_payload({'challenge': public}))
                except ValueError:
                    payload, status = api_error_payload('Check the solver URL, provider, and tier.', code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    payload, status = api_error_payload('Could not save solver settings', code='internal')
                    response = JSONResponse(payload, status_code=status)
        elif action == 'challenge_test':
            try:
                status_data = data.test_challenge()
                result = {
                    'enabled': bool(status_data.get('enabled')),
                    'reachable': bool(status_data.get('reachable')),
                    'probe_ok': bool(status_data.get('probe_ok')),
                    'error': 'Solver test failed. Check the saved connection settings.' if status_data.get('last_error') else None,
                }
                response = JSONResponse(api_ok_payload({'result': result}))
            except Exception:
                logging.getLogger(__name__).warning('Challenge solver probe failed')
                payload, status = api_error_payload('Could not test the solver connection', code='bad_gateway')
                response = JSONResponse(payload, status_code=status)
        else:
            try:
                response = JSONResponse(api_ok_payload(data.read(flask_app.config)))
            except Exception:
                logging.getLogger(__name__).warning('Could not load feature settings')
                payload, status = api_error_payload('Could not load feature settings', code='internal')
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


async def _read_json(request):
    import json
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
