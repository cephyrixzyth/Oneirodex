"""FastAPI art-studio pack generation and download operations."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ArtStudioActions:
    def generate(self, body, package_root):
        from oneirodex.utils.cover_art_studio import clamp_title_scale, save_pack
        return save_pack(
            body.title,
            system=(body.system or '').strip() or None,
            fmt=_format(body.format),
            package_root=package_root,
            headline_override=body.headline,
            subtitle_override=body.subtitle,
            title_scale=clamp_title_scale(body.title_scale),
        )

    def generate_stock(self, ids, fmt, package_root):
        from oneirodex.utils.cover_art_stock import generate_stock_packs
        return generate_stock_packs(ids, fmt=fmt, package_root=package_root)

    def generate_system_marks(self, **kwargs):
        from oneirodex.utils.system_marks import generate_system_marks
        return generate_system_marks(**kwargs)

    def download(self, pack_id, package_root):
        from oneirodex.utils.cover_art_studio import build_zip_bytes, safe_pack_dir
        safe_pack_dir(pack_id, package_root)
        return build_zip_bytes(pack_id, package_root)

    def apply(self, app, pack_id, mode, game_uuid, library_uuid, filename):
        from oneirodex.utils.cover_art_studio import (
            apply_pack_as_fallback, apply_pack_to_game,
        )
        from oneirodex.utils.cover_art_stock import apply_pack_to_library

        if mode == 'fallback':
            return {'mode': 'fallback', 'paths': apply_pack_as_fallback(
                pack_id, package_root=app.root_path,
            ), 'pack_id': pack_id}
        static_url_path = app.config.get('STATIC_URL_PATH') or '/static'
        if mode == 'library':
            return {'mode': 'library', **apply_pack_to_library(
                pack_id, library_uuid, package_root=app.root_path,
                static_url_path=static_url_path,
            )}
        return {'mode': 'game', **apply_pack_to_game(
            pack_id, game_uuid, filename=filename, package_root=app.root_path,
            image_save_path=app.config['IMAGE_SAVE_PATH'],
            static_url_path=static_url_path,
        )}

    def batch_generate(self, app, body):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.cover_art_studio import apply_pack_to_game, save_pack
        from oneirodex.utils.cover_selection import list_games_for_cover_batch

        try:
            limit = min(int(body.get('limit') or body.get('limit_games') or 25), 100)
        except (TypeError, ValueError):
            limit = 25
        game_uuids = _game_uuids(body.get('game_uuids'))
        system = (body.get('system') or body.get('platform') or '').strip() or None
        if game_uuids:
            games = list(db.session.execute(
                select(Game).options(joinedload(Game.library)).filter(Game.uuid.in_(game_uuids))
            ).scalars().unique().all())
        else:
            games = list_games_for_cover_batch(
                library_uuid=(body.get('library_uuid') or '').strip() or None,
                platform=system,
                service=(body.get('service') or '').strip() or None,
                missing_cover=bool(body.get('missing_cover', True)),
                limit=limit,
            )
        applied, errors = [], []
        for game in games:
            current_system = system or (
                game.library.platform.value if game.library and game.library.platform else None
            )
            try:
                manifest = save_pack(game.name or 'Untitled', system=current_system, package_root=app.root_path)
                result = apply_pack_to_game(
                    manifest['pack_id'], game.uuid, package_root=app.root_path,
                    image_save_path=app.config['IMAGE_SAVE_PATH'],
                    static_url_path=app.config.get('STATIC_URL_PATH') or '/static',
                )
                applied.append({
                    'game_uuid': game.uuid, 'name': game.name,
                    'system': current_system, 'pack_id': manifest['pack_id'], **result,
                })
            except Exception as exc:  # noqa: BLE001 — item failures remain isolated
                errors.append({
                    'game_uuid': game.uuid,
                    'name': game.name,
                    'error': 'Failed to generate or apply art pack',
                })
        return {
            'applied': len(applied), 'failed': len(errors),
            'results': applied, 'errors': errors,
        }


def create_admin_art_studio_action_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id=None,
    login_manager=None,
    database_scope=None,
    actions=None,
    event_logger=None,
) -> APIRouter:
    router = APIRouter()
    service = actions or ArtStudioActions()

    @router.post('/admin/api/art-studio/generate')
    async def generate(request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
                                         commit_token_touch, load_user_id, login_manager,
                                         database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        body_data = await _json_object(request)
        try:
            from oneirodex.schemas.admin_art_studio import ArtStudioGenerateBody
            body = ArtStudioGenerateBody.model_validate(body_data)
        except ValidationError as exc:
            return _finish(_validation_error(exc), flask_app, auth, scope)
        try:
            manifest = service.generate(body, flask_app.root_path)
            manifest = {**manifest, 'preview_url': (
                f"/static/library/generated/{manifest['pack_id']}/tile_400x600.webp"
            )}
            (event_logger or _event_logger)(
                f"Art studio generated pack {manifest['pack_id']} for {body.title!r}"
            )
            response = JSONResponse(manifest, status_code=201)
        except ValueError as exc:
            response = _api_error(str(exc), 'bad_request')
        except (PermissionError, OSError):
            response = _api_error('Failed to write generated art pack to disk', 'internal')
        return _finish(response, flask_app, auth, scope)

    @router.post('/admin/api/art-studio/stock/generate')
    async def generate_stock(request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
                                         commit_token_touch, load_user_id, login_manager,
                                         database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        body = await _json_object(request)
        ids = body.get('ids')
        if isinstance(ids, str):
            ids = [item.strip() for item in ids.split(',') if item.strip()]
        elif isinstance(ids, list):
            ids = [str(item).strip() for item in ids if str(item).strip()]
        else:
            ids = None
        fmt = _format(body.get('format'))
        try:
            result = service.generate_stock(ids, fmt, flask_app.root_path)
            (event_logger or _event_logger)(f"Art studio stock generate count={result['count']}")
            response = JSONResponse(result, status_code=201)
        except ValueError as exc:
            response = _api_error(str(exc), 'bad_request')
        except (PermissionError, OSError):
            response = _api_error('Failed to write stock packs', 'internal')
        return _finish(response, flask_app, auth, scope)

    @router.get('/admin/api/art-studio/download/{pack_id}')
    async def download(pack_id: str, request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
                                         commit_token_touch, load_user_id, login_manager,
                                         database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        try:
            payload = service.download(pack_id, flask_app.root_path)
            response = Response(
                payload, media_type='application/zip',
                headers={'Content-Disposition': f'attachment; filename="oneirodex-art-{pack_id}.zip"'},
            )
        except ValueError as exc:
            response = _api_error(str(exc), 'bad_request')
        except FileNotFoundError:
            response = _api_error('Pack not found', 'not_found')
        except (PermissionError, OSError):
            response = _api_error('Failed to read art pack from disk', 'internal')
        return _finish(response, flask_app, auth, scope)

    @router.post('/admin/api/art-studio/system-marks/generate')
    async def generate_system_marks(request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
                                         commit_token_touch, load_user_id, login_manager,
                                         database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        body = await _json_object(request)
        themes = _list_value(body.get('themes'))
        platforms = _list_value(body.get('platforms'))
        try:
            limit = int(body['limit']) if body.get('limit') is not None else None
        except (TypeError, ValueError):
            return _finish(_api_error('limit must be an integer', 'bad_request'), flask_app, auth, scope)
        prompt = str(body.get('prompt')).strip() if body.get('prompt') is not None else ''
        prompt = prompt or None
        if prompt and (not themes or not platforms or len(themes) != 1 or len(platforms) != 1):
            return _finish(_api_error(
                'prompt override requires exactly one theme and one platform', 'bad_request',
            ), flask_app, auth, scope)
        try:
            result = service.generate_system_marks(
                themes=themes, platforms=platforms, package_root=flask_app.root_path,
                force=bool(body.get('force')), limit=limit, prompt=prompt,
            )
            (event_logger or _event_logger)(
                f"Art studio system-marks generate generated={result['generated']} "
                f"skipped={result['skipped']} errors={len(result['errors'])}"
                + (f' lab={themes[0]}/{platforms[0]}' if prompt else '')
            )
            from oneirodex.utils.api_contract import api_ok_payload
            response = JSONResponse(api_ok_payload(result), status_code=201)
        except ValueError as exc:
            response = _api_error(str(exc), 'bad_request')
        except Exception as exc:
            from oneirodex.utils.ai_artwork import ArtworkGenerationError
            if isinstance(exc, ArtworkGenerationError):
                response = _api_error(str(exc), 'bad_gateway')
            elif isinstance(exc, OSError):
                response = _api_error('Failed to write system marks', 'internal')
            else:
                response = _api_error('System-mark generation failed', 'internal')
        return _finish(response, flask_app, auth, scope)

    @router.post('/admin/api/art-studio/apply')
    async def apply_pack(request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
                                         commit_token_touch, load_user_id, login_manager,
                                         database_scope)
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        try:
            from oneirodex.schemas.admin_art_studio import ArtStudioApplyBody
            body = ArtStudioApplyBody.model_validate(await _json_object(request))
        except ValidationError as exc:
            return _finish(_validation_error(exc), flask_app, auth, scope)
        pack_id = (body.pack_id or body.id or '').strip()
        mode = (body.mode or 'game').strip().lower()
        game_uuid = (body.game_uuid or '').strip()
        library_uuid = (body.library_uuid or '').strip()
        if mode == 'library' and not library_uuid:
            response = _api_error('library_uuid is required for library mode', 'bad_request')
        elif mode != 'library' and mode != 'fallback' and not game_uuid:
            response = _api_error('game_uuid is required for game mode', 'bad_request')
        else:
            try:
                result = service.apply(
                    flask_app, pack_id, mode, game_uuid, library_uuid,
                    (body.filename or '').strip() or None,
                )
                _log_art_studio(event_logger, f'Art studio applied pack {pack_id}')
                response = JSONResponse(result)
            except LookupError as exc:
                response = _api_error(str(exc), 'not_found')
            except (ValueError, FileNotFoundError) as exc:
                response = _api_error(str(exc), 'bad_request')
            except (PermissionError, OSError):
                response = _api_error('Failed to write cover art to disk', 'internal')
            except Exception:
                response = _api_error('Unexpected error applying pack', 'internal')
        return _finish(response, flask_app, auth, scope)

    @router.post('/admin/api/art-studio/batch-generate')
    @router.post('/admin/api/art-studio/apply-batch')
    async def batch_generate(request: Request):
        auth, denied, scope = _authorize(request, flask_app, find_user, find_token,
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
            result = service.batch_generate(flask_app, body)
            _log_art_studio(
                event_logger,
                f"Art studio apply-batch applied={result['applied']} failed={result['failed']}",
            )
            response = JSONResponse(result)
        except Exception:
            response = _api_error('Failed to apply generated art batch', 'internal')
        return _finish(response, flask_app, auth, scope)

    return router


def _authorize(request, app, find_user, find_token, commit_token_touch,
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
        return auth, _login_redirect(app, request, login_manager, auth), scope
    if normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
        payload, status = api_error_payload('Admin access required', code='forbidden')
        return auth, JSONResponse(payload, status_code=status), scope
    if auth.token is not None and not auth.has_scope('admin'):
        payload, status = api_error_payload(
            'This token does not have the admin scope', code='forbidden',
        )
        return auth, JSONResponse(payload, status_code=status), scope
    return auth, None, scope


async def _json_object(request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _validation_error(exc):
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors
    payload, status = api_error_payload(
        'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
    )
    return JSONResponse(payload, status_code=status)


def _api_error(message, code):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


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


def _event_logger(message):
    from oneirodex.utils.event_logging import log_system_event
    return log_system_event(message)


def _format(value):
    result = (value or 'webp').lower()
    return result if result in ('webp', 'png') else 'webp'


def _list_value(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return None


def _game_uuids(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return None


def _log_art_studio(event_logger, message):
    (event_logger or _event_logger)(message)


def mount_admin_art_studio_action_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_art_studio_action_router(flask_app, **kwargs))
    return app
