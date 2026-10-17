"""Native FastAPI APIs for a member's private saved-filter trees."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class SavedFilterData:
    def list(self, user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SavedFilter

        return db.session.execute(
            select(SavedFilter).filter_by(user_id=user.id).order_by(SavedFilter.name)
        ).scalars().all()

    def get(self, user, filter_id):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SavedFilter

        return db.session.execute(
            select(SavedFilter).filter_by(id=filter_id, user_id=user.id)
        ).scalars().first()

    def name_exists(self, user, name, *, excluding=None):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SavedFilter

        query = select(SavedFilter).filter_by(user_id=user.id, name=name)
        if excluding is not None:
            query = query.filter(SavedFilter.id != excluding)
        return db.session.execute(query).scalars().first() is not None

    def create(self, user, *, name, tree, is_collection):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SavedFilter

        row = SavedFilter(
            user_id=user.id, name=name, tree=tree, is_collection=is_collection,
        )
        db.session.add(row)
        db.session.commit()
        # PostgreSQL stores these DateTime columns without a timezone. Flask's
        # legacy session expires ORM instances on commit, so its response
        # serializes the reloaded naive timestamps. The native session keeps
        # committed instances alive; refresh them to preserve that response
        # contract and match a subsequent GET.
        db.session.refresh(row)
        return row

    def save(self, row=None):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()
        if row is not None:
            db.session.refresh(row)

    def delete(self, row):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.delete(row)
        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def preview(self, user, tree, limit):
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.filter_tree import compile_filter_tree
        from oneirodex.utils.library_acl import apply_game_access_filters

        clause = compile_filter_tree(tree, user=user)
        base = apply_game_access_filters(select(Game).filter(clause), user)
        count = db.session.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()
        sample = []
        if limit:
            rows = db.session.execute(base.order_by(Game.name).limit(limit)).scalars().all()
            sample = [{'uuid': game.uuid, 'name': game.name} for game in rows]
        return {'count': int(count), 'sample': sample}


def create_saved_filter_router(
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
    data = data_access or SavedFilterData()

    @router.api_route('/api/filters/fields', methods=['GET', 'HEAD'])
    def filter_fields(request: Request):
        from oneirodex.utils.filter_tree import describe_fields

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _success({'fields': describe_fields()})
            return _finish(response, flask_app, request, auth)

    @router.api_route('/api/filters/saved', methods=['GET', 'HEAD'])
    def list_saved_filters(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _success({'filters': [row.to_dict() for row in data.list(auth.user)]})
            return _finish(response, flask_app, request, auth)

    @router.post('/api/filters/saved')
    async def create_saved_filter(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    from oneirodex.schemas.saved_filters import SavedFilterCreateBody

                    body = SavedFilterCreateBody.model_validate(await _json_body(request))
                except ValidationError as exc:
                    response = _validation_error(exc)
                if response is None:
                    from oneirodex.utils.filter_tree import FilterTreeError, parse_filter_tree

                    try:
                        tree = parse_filter_tree(body.tree)
                    except FilterTreeError as exc:
                        response = _bad_tree(exc)
                    if response is None and data.name_exists(auth.user, body.name):
                        response = _error(
                            f'You already have a filter called "{body.name}".', 'conflict',
                        )
                    if response is None:
                        try:
                            row = data.create(
                                auth.user, name=body.name, tree=tree,
                                is_collection=body.is_collection,
                            )
                            response = _success({'filter': row.to_dict()}, status=201)
                        except Exception:  # noqa: BLE001 — retain generic persistence error
                            data.rollback()
                            flask_app.logger.warning('saved filter create failed')
                            response = _error("Couldn't save that filter.", 'internal')
            return _finish(response, flask_app, request, auth)

    @router.put('/api/filters/saved/{filter_id:int}')
    async def update_saved_filter(filter_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    from oneirodex.schemas.saved_filters import SavedFilterUpdateBody

                    body = SavedFilterUpdateBody.model_validate(await _json_body(request))
                except ValidationError as exc:
                    response = _validation_error(exc)
                if response is None:
                    row = data.get(auth.user, filter_id)
                    if row is None:
                        response = _error('Filter not found', 'not_found')
                    else:
                        from oneirodex.utils.filter_tree import FilterTreeError, parse_filter_tree

                        if body.tree is not None:
                            try:
                                row.tree = parse_filter_tree(body.tree)
                            except FilterTreeError as exc:
                                response = _bad_tree(exc)
                        if response is None and body.name is not None and body.name != row.name:
                            if data.name_exists(auth.user, body.name, excluding=filter_id):
                                response = _error(
                                    f'You already have a filter called "{body.name}".', 'conflict',
                                )
                            else:
                                row.name = body.name
                        if response is None:
                            if body.is_collection is not None:
                                row.is_collection = body.is_collection
                            try:
                                data.save(row)
                                response = _success({'filter': row.to_dict()})
                            except Exception:  # noqa: BLE001 — retain generic persistence error
                                data.rollback()
                                flask_app.logger.warning(
                                    'saved filter update failed for id %s', filter_id,
                                )
                                response = _error("Couldn't save that filter.", 'internal')
            return _finish(response, flask_app, request, auth)

    @router.delete('/api/filters/saved/{filter_id:int}')
    def delete_saved_filter(filter_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                row = data.get(auth.user, filter_id)
                if row is None:
                    response = _error('Filter not found', 'not_found')
                else:
                    try:
                        data.delete(row)
                        response = _success({'deleted': filter_id})
                    except Exception:  # noqa: BLE001 — retain generic persistence error
                        data.rollback()
                        flask_app.logger.warning(
                            'saved filter delete failed for id %s', filter_id,
                        )
                        response = _error("Couldn't delete that filter.", 'internal')
            return _finish(response, flask_app, request, auth)

    @router.post('/api/filters/preview')
    async def preview_filter(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    from oneirodex.schemas.saved_filters import FilterPreviewBody

                    body = FilterPreviewBody.model_validate(await _json_body(request))
                except ValidationError as exc:
                    response = _validation_error(exc)
                if response is None:
                    from oneirodex.utils.filter_tree import FilterTreeError

                    try:
                        payload = data.preview(auth.user, body.tree, body.limit)
                    except FilterTreeError as exc:
                        response = _bad_tree(exc)
                    else:
                        response = _success(payload)
            return _finish(response, flask_app, request, auth)

    return router


def mount_saved_filter_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_saved_filter_router(flask_app, **kwargs))
    return app


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _csrf(request, auth, flask_app):
    if auth.token is not None:
        return None
    from .csrf_compat import csrf_error_response

    return csrf_error_response(request, auth.session_data, flask_app.config)


def _write_scope_error(auth):
    if auth.token is not None and not auth.has_scope('write:library'):
        return _error('Missing scope: write:library', 'forbidden')
    return None


async def _json_body(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        return await request.json()
    except Exception:  # noqa: BLE001 — Flask's silent JSON parsing returns empty body
        return {}


def _validation_error(exc):
    from oneirodex.utils.validation import format_validation_errors

    return _error('Invalid request.', 'unprocessable', detail=format_validation_errors(exc))


def _bad_tree(exc):
    return _error(str(exc), 'bad_request', detail={'path': exc.path})


def _error(message, code, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return JSONResponse(payload, status_code=status)


def _success(payload, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload 

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response
