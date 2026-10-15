"""FastAPI admin image queue read preserving Flask response projection."""
from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ImageQueueData:
    def list_queue(self, config, params):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image
        from oneirodex.utils.cover_selection import image_save_path_status
        from oneirodex.utils.image_kinds import IMAGE_KIND_ORDER, parse_image_kind

        page = _int_param(params.get('page'), 1)
        per_page = _int_param(params.get('per_page'), 20)
        page = max(page, 1)
        per_page = max(per_page, 1)
        status_filter = params.get('status', 'all')
        raw_kind = params.get('kind') or params.get('type') or 'all'
        kind = parse_image_kind(raw_kind, default=None, allow_all=True)
        query = select(Image).join(Game).options(joinedload(Image.game))
        count_query = select(func.count(Image.id)).join(Game)
        filters = []
        if status_filter == 'pending':
            filters.extend((Image.is_downloaded.is_(False), Image.last_error.is_(None)))
        elif status_filter == 'failed':
            filters.extend((Image.is_downloaded.is_(False), Image.last_error.isnot(None)))
        elif status_filter == 'downloaded':
            filters.append(Image.is_downloaded.is_(True))
        if kind != 'all':
            filters.append(Image.image_type == kind)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
        query = query.order_by(Image.is_downloaded.asc(), Image.created_at.desc())
        total = db.session.execute(count_query).scalar_one()
        rows = db.session.execute(
            query.limit(per_page).offset((page - 1) * per_page)
        ).scalars().unique().all()
        image_save_path = config.get('IMAGE_SAVE_PATH')
        path_status = image_save_path_status(config)
        output = []
        for image in rows:
            file_exists = bool(
                image.is_downloaded and image.url and image_save_path
                and os.path.isfile(os.path.join(image_save_path, image.url))
            )
            failure_reason = None
            if not image.is_downloaded and image.last_error:
                failure_reason = image.last_error
            elif image.is_downloaded and not file_exists:
                failure_reason = 'Marked downloaded but file missing under IMAGE_SAVE_PATH'
                if path_status.get('error'):
                    failure_reason = f"{failure_reason} ({path_status['error']})"
            output.append({
                'id': image.id,
                'game_uuid': image.game_uuid,
                'game_name': image.game.name if image.game else 'Unknown',
                'image_type': image.image_type,
                'kind': image.image_type,
                'download_url': image.download_url,
                'is_downloaded': image.is_downloaded,
                'status': _image_status(image),
                'last_error': image.last_error,
                'failure_reason': failure_reason,
                'last_attempt_at': image.last_attempt_at.strftime('%Y-%m-%d %H:%M:%S') if image.last_attempt_at else None,
                'created_at': image.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'local_url': f'/static/library/images/{image.url}' if file_exists else None,
                'file_missing': bool(image.is_downloaded and not file_exists),
            })
        pages = (total + per_page - 1) // per_page
        return {
            'images': output,
            'image_save_path': path_status,
            'allowed_kinds': list(IMAGE_KIND_ORDER),
            'kind_filter': kind,
            'pagination': {
                'page': page, 'pages': pages, 'per_page': per_page, 'total': total,
                'has_next': page < pages, 'has_prev': page > 1,
            },
        }


def _int_param(raw, default):
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _image_status(image):
    if image.is_downloaded:
        return 'downloaded'
    if image.last_error:
        return 'failed'
    return 'pending'


def create_admin_image_queue_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ImageQueueData()

    @router.api_route('/admin/api/image_queue_list', methods=['GET', 'HEAD'])
    async def image_queue(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.role_catalog import normalize_role
                if normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
                    from oneirodex.utils.api_contract import api_error_payload
                    payload, status = api_error_payload('Admin access required', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                elif auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        response = JSONResponse(
                            data.list_queue(flask_app.config, request.query_params),
                        )
                    except ValueError as exc:
                        from oneirodex.utils.api_contract import api_error_payload
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_admin_image_queue_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_image_queue_read_router(flask_app, **kwargs))
    return app
