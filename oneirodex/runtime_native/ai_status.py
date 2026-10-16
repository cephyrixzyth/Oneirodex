"""Native FastAPI read endpoint for the admin Ollama readiness status."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse
from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class AiStatusData:
    """Adapter for the legacy status report, which may contact Ollama."""

    def status(self, *, config=None) -> dict:
        from oneirodex.utils.ai_assist import ollama_status

        return ollama_status(config=config)

    def read_config(self, *, config=None) -> dict:
        from oneirodex.utils.ai_assist import get_ai_config

        return get_ai_config(config=config)

    def save_config(self, payload: dict, *, config=None) -> dict:
        from oneirodex.utils.ai_assist import save_ai_config

        return save_ai_config(payload, config=config)

    def enabled(self, *, config=None) -> bool:
        from oneirodex.utils.ai_assist import ai_enabled

        return ai_enabled(config=config)

    def unmatched_folder(self, folder_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        return db.session.get(UnmatchedFolder, folder_id)

    def folder_platform(self, library_uuid: str | None):
        if not library_uuid:
            return None
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
        return str(library.platform) if library and library.platform is not None else None

    def triage(self, name: str, platform: str | None, *, config=None):
        from oneirodex.utils.ai_assist import triage_folder

        return triage_folder(name, platform, config=config)

    def game_name_and_summary(self, game_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        return (game.name, game.summary) if game else None

    def notes(self, context: dict, *, config=None):
        from oneirodex.utils.ai_assist import doctor_notes

        return doctor_notes(context, config=config)

    def auto_apply_enabled(self, *, config=None) -> bool:
        from oneirodex.utils.ai_assist import ai_auto_apply_enabled

        return ai_auto_apply_enabled(config=config)

    def apply(self, game_uuid: str, title: str, *, config=None):
        from oneirodex.utils.ai_assist import apply_triage_title

        return apply_triage_title(game_uuid, title, config=config)


def create_ai_status_router(
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
    """Create native GET/HEAD routes matching login_required/admin_required."""
    router = APIRouter()
    data = data_access or AiStatusData()

    @router.api_route('/api/ai/status', methods=['GET', 'HEAD'])
    def ai_status(request: Request):
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
            user = auth.user
            if user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = (
                    bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if is_admin and auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif not is_admin:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger',
                        include_next=False,
                    )
                else:
                    from starlette.responses import JSONResponse

                    # The report intentionally has a bare jsonify contract: its
                    # ``error`` field may explain an unreachable Ollama on 200.
                    response = JSONResponse(data.status(config=flask_app.config))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/ai/config', methods=['GET', 'HEAD', 'PUT'])
    async def ai_config(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if request.method == 'PUT' and auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            is_admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if response is None:
                if user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif not is_admin:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                elif request.method in ('GET', 'HEAD'):
                    response = JSONResponse(data.read_config(config=flask_app.config))
                else:
                    try:
                        payload = await request.json()
                    except Exception:
                        payload = {}
                    if not isinstance(payload, dict) or not any(
                        key in payload for key in (
                            'enabled', 'enable_ai_assist', 'ollama_base_url', 'ollama_model',
                        )
                    ):
                        payload, status = api_error_payload(
                            'No recognized fields to update', code='bad_request',
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        saved = data.save_config(payload, config=flask_app.config)
                        response = JSONResponse(api_ok_payload({'status': 'saved', **saved}))

            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/ai/triage')
    async def ai_triage(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = await _admin_post_precheck(
                request, auth, flask_app, login_manager,
            )
            if response is None:
                if not data.enabled(config=flask_app.config):
                    response = _api_error('AI assist is disabled', 'forbidden')
                else:
                    payload = await _json_object(request)
                    name = str(payload.get('name') or payload.get('folder_name') or '').strip()
                    platform = payload.get('platform')
                    folder_id = payload.get('unmatched_folder_id') or payload.get('folder_id')
                    if folder_id and not name:
                        row = data.unmatched_folder(folder_id)
                        if row is None:
                            response = _api_error('Unmatched folder not found', 'not_found')
                        else:
                            name = (getattr(row, 'search_name', None) or '').strip()
                            if not name:
                                import os

                                name = os.path.basename((getattr(row, 'folder_path', None) or '').rstrip('/\\'))
                            if not platform:
                                platform = data.folder_platform(getattr(row, 'library_uuid', None))
                    if not name and payload.get('folder_path'):
                        import os

                        name = os.path.basename(str(payload['folder_path']).rstrip('/\\'))
                    if response is None:
                        try:
                            response = JSONResponse(data.triage(name, platform, config=flask_app.config))
                        except ValueError as exc:
                            response = _api_error(str(exc), 'bad_request')
                        except PermissionError as exc:
                            response = _api_error(str(exc), 'forbidden')
                        except ConnectionError as exc:
                            response = _api_error(str(exc), 'unavailable')
            _finish(response, request, flask_app, auth)
            return response

    @router.post('/api/ai/doctor-notes')
    async def ai_doctor_notes(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = await _admin_post_precheck(
                request, auth, flask_app, login_manager,
            )
            if response is None:
                if not data.enabled(config=flask_app.config):
                    response = _api_error('AI assist is disabled', 'forbidden')
                else:
                    payload = await _json_object(request)
                    context = {
                        'issues': payload.get('issues') or payload.get('issue_codes') or [],
                        'summary': payload.get('summary') or payload.get('extra'),
                        'game_name': payload.get('game_name') or payload.get('name'),
                    }
                    game_uuid = str(payload.get('game_uuid') or '').strip()
                    if game_uuid:
                        game = data.game_name_and_summary(game_uuid)
                        if game is None:
                            response = _api_error('Game not found', 'not_found')
                        else:
                            context['game_name'] = game[0]
                            context['summary'] = context.get('summary') or (game[1] or '')[:500]
                    if response is None:
                        try:
                            response = JSONResponse(data.notes(context, config=flask_app.config))
                        except ValueError as exc:
                            response = _api_error(str(exc), 'bad_request')
                        except PermissionError as exc:
                            response = _api_error(str(exc), 'forbidden')
                        except ConnectionError as exc:
                            response = _api_error(str(exc), 'unavailable')
            _finish(response, request, flask_app, auth)
            return response

    @router.post('/api/ai/apply-triage')
    async def ai_apply_triage(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = await _admin_post_precheck(
                request, auth, flask_app, login_manager,
            )
            if response is None:
                if not data.auto_apply_enabled(config=flask_app.config):
                    response = _api_error(
                        'AI auto-apply is disabled. Set ENABLE_AI_AUTO_APPLY=true.',
                        'forbidden', auto_apply_enabled=False,
                    )
                else:
                    from pydantic import ValidationError
                    from oneirodex.schemas.ai_assist import ApplyTriageBody
                    from oneirodex.utils.validation import format_validation_errors

                    payload = await _json_object(request)
                    try:
                        body = ApplyTriageBody.model_validate(payload)
                    except ValidationError as exc:
                        error_payload, status = _api_error_payload(
                            'Invalid request.', 'unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(error_payload, status_code=status)
                    else:
                        try:
                            result = data.apply(
                                body.game_uuid, body.title or body.name or '',
                                config=flask_app.config,
                            )
                            response = JSONResponse(result, status_code=(
                                200 if result.get('unchanged') else 201
                            ))
                        except ValueError as exc:
                            response = _api_error(str(exc), 'bad_request')
                        except LookupError as exc:
                            response = _api_error(str(exc), 'not_found')
                        except PermissionError as exc:
                            response = _api_error(str(exc), 'forbidden')
            _finish(response, request, flask_app, auth)
            return response

    return router


async def _admin_post_precheck(request, auth, flask_app, login_manager):
    if auth.token is None:
        from .csrf_compat import csrf_error_response

        response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is not None:
            return response
    if auth.user is None:
        return _login_redirect(
            flask_app, request, login_manager, auth,
            message=getattr(login_manager, 'login_message', None),
            category=getattr(login_manager, 'login_message_category', 'message'),
            include_next=True,
        )
    from oneirodex.utils.role_catalog import normalize_role

    if normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
        return _login_redirect(
            flask_app, request, login_manager, auth,
            message='You must be an admin to access this page.',
            category='danger', include_next=False,
        )
    if auth.token is not None and not auth.has_scope('admin'):
        return _api_error('This token does not have the admin scope', 'forbidden')
    return None


async def _json_object(request: Request) -> dict:
    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json' and not (
        content_type.startswith('application/') and content_type.endswith('+json')
    ):
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _api_error_payload(message: str, code: str, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    return api_error_payload(message, code=code, **fields)


def _api_error(message: str, code: str, **fields):
    payload, status = _api_error_payload(message, code, **fields)
    return JSONResponse(payload, status_code=status)


def _finish(response, request, flask_app, auth):
    if auth.should_set_session_cookie:
        from .oidc_status import _set_session_cookie

        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def mount_ai_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_ai_status_router(flask_app, **kwargs))
    return app
