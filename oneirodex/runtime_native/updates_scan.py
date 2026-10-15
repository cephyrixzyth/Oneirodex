"""Native FastAPI endpoint for the bounded member freshness scan."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

_logger = logging.getLogger(__name__)

UPDATES_SCAN_DEFAULT = 25
UPDATES_SCAN_MAX = 50
UPDATES_SCAN_STALE_SECONDS = 86400


class UpdateScanData:
    uses_explicit_app = True

    flask_app = None

    def scan(self, user, *, limit: int, library_uuid: str | None, only_stale: bool):
        from sqlalchemy import func, or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.freshness import check_and_store_freshness
        from oneirodex.utils.library_acl import apply_game_access_filters

        cutoff = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(seconds=UPDATES_SCAN_STALE_SECONDS)
            if only_stale else None
        )
        due = apply_game_access_filters(select(Game), user)
        if library_uuid:
            due = due.filter(Game.library_uuid == library_uuid)
        if cutoff is not None:
            due = due.filter(or_(
                Game.freshness_checked_at.is_(None),
                Game.freshness_checked_at < cutoff,
            ))
        total_due = db.session.execute(
            select(func.count()).select_from(due.subquery())
        ).scalar() or 0
        games = db.session.execute(due.order_by(
            Game.freshness_checked_at.asc().nullsfirst(), Game.name.asc(),
        ).limit(limit)).scalars().all()
        checked = 0
        behind = []
        errors = []
        for game in games:
            try:
                _ = list(game.updates or [])
                _ = list(game.extras or [])
                _ = list(game.urls or [])
                public = check_and_store_freshness(
                    game, commit=False, db_session=db.session, app=self.flask_app,
                )
                checked += 1
                if public.get('status') in ('behind', 'heuristic_behind'):
                    behind.append({
                        'uuid': game.uuid,
                        'name': game.name,
                        'status': public.get('status'),
                    })
            except Exception as exc:  # a failed title does not abort the bounded batch
                _logger.warning('updates scan failed for %s: %s', game.uuid, exc)
                errors.append({
                    'uuid': game.uuid,
                    'name': game.name,
                    'error': 'Could not check this title',
                })
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _logger.warning('updates scan commit failed: %s', exc)
            return None
        return {
            'requested': len(games),
            'checked': checked,
            'behind': behind,
            'behind_count': len(behind),
            'errors': errors,
            'remaining': max(0, total_due - len(games)),
            'limit': limit,
            'only_stale': only_stale,
        }


def create_update_scan_router(
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
    data = data_access if data_access is not None else UpdateScanData()
    if getattr(data, 'uses_explicit_app', False):
        data.flask_app = flask_app

    @router.post('/api/updates/scan')
    async def updates_scan(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.token is not None and not auth.has_scope('write:library'):
                response = _error('Bearer token requires write:library scope', 'forbidden')
            else:
                response = (
                    None if auth.token is not None
                    else csrf_error_response(request, auth.session_data, flask_app.config)
                )
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                body = _json_object(await request.body())
                try:
                    limit = int(body.get('limit') or UPDATES_SCAN_DEFAULT)
                except (TypeError, ValueError):
                    limit = UPDATES_SCAN_DEFAULT
                limit = max(1, min(limit, UPDATES_SCAN_MAX))
                library_uuid = (body.get('library_uuid') or '').strip() or None
                only_stale = bool(body.get('only_stale', True))
                payload = data.scan(
                    auth.user, limit=limit,
                    library_uuid=library_uuid, only_stale=only_stale,
                )
                if payload is None:
                    response = _error('Could not save the scan results', 'internal')
                else:
                    response = _json_response(payload)
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_update_scan_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_update_scan_router(flask_app, **kwargs))
    return app


def _json_object(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_response(payload):
    from oneirodex.utils.api_contract import api_ok_payload
    from starlette.responses import JSONResponse

    return JSONResponse(api_ok_payload(payload))


def _error(message, code):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
