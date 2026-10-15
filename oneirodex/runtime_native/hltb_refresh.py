"""Native admin action for refreshing one game's HLTB data."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class HltbRefreshData:
    def refresh(self, game_uuid: str) -> tuple[str, dict | None]:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.hltb import update_game_hltb_sync

        settings = global_settings_row()
        if not settings or not settings.enable_hltb_integration:
            return 'disabled', None
        game = db.session.execute(
            select(Game).where(Game.uuid == game_uuid)
        ).scalars().first()
        if game is None:
            return 'missing', None
        if not update_game_hltb_sync(game_uuid, game.name):
            return 'unmatched', None
        db.session.refresh(game)
        return 'updated', {
            'message': f'HLTB data updated for {game.name}',
            'data': {
                'hltb_id': game.hltb_id,
                'hltb_main_story': game.hltb_main_story,
                'hltb_main_extra': game.hltb_main_extra,
                'hltb_completionist': game.hltb_completionist,
                'hltb_all_styles': game.hltb_all_styles,
                'hltb_last_updated': game.hltb_last_updated.isoformat()
                if game.hltb_last_updated else None,
            },
        }

    def bulk_refresh(self, limit: int) -> tuple[str, dict | None]:
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.hltb import get_games_without_hltb, update_game_hltb_sync

        settings = global_settings_row()
        if not settings or not settings.enable_hltb_integration:
            return 'disabled', None
        games = get_games_without_hltb(limit=limit)
        if not games:
            return 'complete', {
                'message': 'No games need HLTB data update',
                'processed': 0, 'successful': 0, 'failed': 0,
            }
        processed = successful = failed = 0
        errors = []
        import logging
        logger = logging.getLogger(__name__)
        for game in games:
            processed += 1
            try:
                success = update_game_hltb_sync(game.uuid, game.name)
            except Exception:
                failed += 1
                errors.append(f'{game.name}: Update failed')
                logger.warning('HLTB bulk refresh failed for a game')
            else:
                if success:
                    successful += 1
                else:
                    failed += 1
                    errors.append(f'{game.name}: Not found on HLTB')
        return 'complete', {
            'message': f'Processed {processed} games: {successful} successful, {failed} failed',
            'processed': processed, 'successful': successful, 'failed': failed,
            'errors': errors[:10],
        }


def create_hltb_refresh_router(
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
    data = data_access or HltbRefreshData()

    @router.api_route('/api/hltb/refresh/{game_uuid}', methods=['POST'])
    def refresh_hltb(request: Request, game_uuid: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie

            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name),
                flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(
                    flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                ),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request, flask_app.config,
                    find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if csrf_response is not None:
                response = csrf_response
            else:
                assert auth is not None
                user = auth.user
                is_admin = (
                    user is not None
                    and bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
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
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        outcome, payload = data.refresh(game_uuid)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        import logging

                        db.session.rollback()
                        logging.getLogger(__name__).warning('HLTB refresh failed')
                        error, status = api_error_payload(
                            'Could not refresh HLTB data', code='internal'
                        )
                        response = JSONResponse(error, status_code=status)
                    else:
                        if outcome == 'disabled':
                            error, status = api_error_payload(
                                'HLTB integration is not enabled', code='bad_request'
                            )
                            response = JSONResponse(error, status_code=status)
                        elif outcome == 'missing':
                            error, status = api_error_payload('Game not found', code='not_found')
                            response = JSONResponse(error, status_code=status)
                        elif outcome == 'unmatched':
                            error, status = api_error_payload(
                                'Failed to fetch HLTB data. Game may not be found on HowLongToBeat.',
                                code='not_found',
                            )
                            response = JSONResponse(error, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload(payload or {}))

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    @router.api_route('/api/hltb/bulk-refresh', methods=['POST'])
    async def bulk_refresh_hltb(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie

            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user if auth is not None else None
            is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and (
                normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
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
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            else:
                try:
                    try:
                        body = await request.json()
                    except ValueError:
                        body = {}
                    limit = body.get('limit', 50) if isinstance(body, dict) else 50
                    try:
                        limit = min(max(int(limit), 1), 200)
                    except (TypeError, ValueError):
                        limit = 50
                    outcome, payload = data.bulk_refresh(limit)
                    if outcome == 'disabled':
                        error, status = api_error_payload('HLTB integration is not enabled', code='bad_request')
                        response = JSONResponse(error, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload(payload or {}))
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    import logging
                    logging.getLogger(__name__).warning('HLTB bulk refresh failed')
                    error, status = api_error_payload('Could not refresh HLTB data', code='internal')
                    response = JSONResponse(error, status_code=status)

        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    return router


def mount_hltb_refresh_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_hltb_refresh_router(flask_app, **kwargs))
    return app
