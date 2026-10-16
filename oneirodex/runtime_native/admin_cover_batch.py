"""FastAPI batch cover application and auto-pick compatibility actions."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class CoverBatchData:
    def path_status(self, config):
        from oneirodex.utils.cover_selection import image_save_path_status
        return image_save_path_status(config)

    def apply(self, app, **kwargs):
        from oneirodex.utils.cover_selection import batch_apply_covers
        from oneirodex.utils.cover_art_studio import apply_pack_to_game, save_pack

        def generate(game):
            system = game.library.platform.value if game.library and game.library.platform else None
            manifest = save_pack(
                game.name or 'Untitled', system=system, package_root=app.root_path,
            )
            return apply_pack_to_game(
                manifest['pack_id'], game.uuid, package_root=app.root_path,
                image_save_path=app.config['IMAGE_SAVE_PATH'],
                static_url_path=app.config.get('STATIC_URL_PATH') or '/static',
            )

        return batch_apply_covers(
            generate_fn=generate, config=app.config, **kwargs,
        )


def create_admin_cover_batch_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or CoverBatchData()

    @router.post('/admin/api/covers/batch/apply')
    async def batch_apply(request: Request):
        auth, scope, denied = _auth(request, flask_app, find_user, find_token,
                                    commit_token_touch, load_user_id, login_manager,
                                    database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        body = await _json_object(request)
        try:
            limit = min(int(body.get('limit_games') or body.get('limit') or 25), 100)
        except (TypeError, ValueError):
            limit = 25
        kwargs = _filters(body, default_policy='sgdb_then_igdb_then_generate')
        kwargs['limit_games'] = limit
        result = data.apply(flask_app, **kwargs)
        return _finish(JSONResponse(result), flask_app, auth, scope)

    @router.post('/admin/api/artwork/auto-pick')
    async def auto_pick(request: Request):
        auth, scope, denied = _auth(request, flask_app, find_user, find_token,
                                    commit_token_touch, load_user_id, login_manager,
                                    database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.cover_selection import resolve_policy
        body = await _json_object(request)
        policy = (body.get('policy') or 'best_available').strip() or 'best_available'
        try:
            limit = min(int(body.get('limit_games') or body.get('limit') or 25), 100)
        except (TypeError, ValueError):
            limit = 25
        status = (body.get('status') or '').strip().lower()
        missing_cover = bool(body.get('missing_cover', True))
        if status == 'downloaded':
            missing_cover = False
        path_status = data.path_status(flask_app.config)
        if not path_status.get('writable'):
            message = path_status.get('error') or 'IMAGE_SAVE_PATH is not writable'
            payload, code = api_error_payload(
                message, code='unavailable', applied=0, failed=0, results=[],
                policy=list(resolve_policy(policy)), image_save_path=path_status,
            )
            return _finish(JSONResponse(payload, status_code=code), flask_app, auth, scope)
        kwargs = _filters(body, default_policy=policy)
        kwargs['missing_cover'] = missing_cover
        kwargs['limit_games'] = limit
        result = data.apply(flask_app, **kwargs)
        payload = api_ok_payload({
            'message': (
                f"Auto-pick finished: applied={result.get('applied', 0)} "
                f"failed={result.get('failed', 0)}"
            ),
            **result,
        })
        return _finish(JSONResponse(payload), flask_app, auth, scope)

    return router


def _filters(body, *, default_policy):
    uuids = body.get('game_uuids')
    if isinstance(uuids, str):
        uuids = [value.strip() for value in uuids.split(',') if value.strip()]
    elif isinstance(uuids, list):
        uuids = [str(value).strip() for value in uuids if str(value).strip()]
    else:
        uuids = None
    return {
        'game_uuids': uuids,
        'library_uuid': (body.get('library_uuid') or '').strip() or None,
        'platform': (body.get('platform') or body.get('system') or '').strip() or None,
        'service': (body.get('service') or '').strip() or None,
        'missing_cover': bool(body.get('missing_cover', True)),
        'policy': (body.get('policy') or default_policy).strip(),
    }


async def _json_object(request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _auth(request, app, find_user, find_token, commit_token_touch,
          load_user_id, login_manager, database_scope):
    scope = database_scope(app) if database_scope else nullcontext()
    scope.__enter__()
    try:
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
    except Exception:
        import sys
        scope.__exit__(*sys.exc_info())
        raise
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.role_catalog import normalize_role
    if auth.user is None:
        return auth, scope, _login_redirect(app, request, login_manager, auth)
    if normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
        payload, status = api_error_payload('Admin access required', code='forbidden')
        return auth, scope, JSONResponse(payload, status_code=status)
    if auth.token is not None and not auth.has_scope('admin'):
        payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
        return auth, scope, JSONResponse(payload, status_code=status)
    return auth, scope, None


def _finish(response, app, auth, scope):
    try:
        if auth.should_set_session_cookie:
            _set_session_cookie(response, app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(app.config).items():
            response.headers.setdefault(key, value)
        return response
    finally:
        scope.__exit__(None, None, None)


def mount_admin_cover_batch_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_cover_batch_router(flask_app, **kwargs))
    return app
