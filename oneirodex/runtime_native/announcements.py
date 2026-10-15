"""Native FastAPI announcement feed and authoring API."""
from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class AnnouncementData:
    def list(self, *, include_drafts: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Announcement

        query = select(Announcement).order_by(
            Announcement.created_at.desc()
        ).limit(50)
        if not include_drafts:
            query = query.filter_by(published=True)
        return [row.to_dict() for row in db.session.execute(query).scalars().all()]

    def create(self, *, title, body, published, author_user_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Announcement

        row = Announcement(
            title=title[:200],
            body=body[:20000],
            published=bool(published),
            author_user_id=author_user_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.to_dict()


def create_announcements_router(
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
    data = data_access or AnnouncementData()

    @router.api_route('/api/announcements', methods=['GET', 'HEAD'])
    def list_announcements(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                include_drafts = (
                    request.query_params.get('include_drafts') == '1'
                    and auth.has_scope('admin')
                )
                rows = data.list(include_drafts=include_drafts)
                response = JSONResponse({
                    'announcements': rows,
                    'empty': len(rows) == 0,
                })
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/announcements')
    async def create_announcement(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            csrf_response = csrf_error_response(
                request, auth.session_data, flask_app.config
            )
            if csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, validation_error = await _validated_body(request)
                if validation_error is not None:
                    response = validation_error
                else:
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    if not auth.has_scope('admin'):
                        payload, status = api_error_payload(
                            'Admin required', code='forbidden',
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        from starlette.responses import JSONResponse

                        try:
                            payload = data.create(
                                title=body.title,
                                body=body.body,
                                published=body.published,
                                author_user_id=auth.user.id,
                            )
                        except Exception:
                            flask_app.logger.exception('announcement create failed')
                            payload, status = api_error_payload(
                                'Could not create the announcement.', code='internal',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(payload, status_code=201)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    return router


def mount_announcements_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_announcements_router(flask_app, **kwargs))
    return app


async def _validated_body(request: Request):
    from oneirodex.schemas.collections import CreateAnnouncementBody
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors
    from starlette.responses import JSONResponse

    try:
        raw = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        raw = {}
    try:
        return CreateAnnouncementBody.model_validate(
            raw if isinstance(raw, dict) else {}
        ), None
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return None, JSONResponse(payload, status_code=status)


def _finalize(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
