"""Native FastAPI mutation for selecting a shipped account avatar."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response as _csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class StockAvatarData:
    """Adapter for the existing stock-avatar setter and transaction."""

    def set_stock(self, avatar_id: str, user, flask_app) -> tuple[str | None, str | None]:
        from oneirodex.utils.avatar import set_stock_avatar

        return set_stock_avatar(avatar_id, user, flask_app)

    def avatar_url(self, path: str | None) -> str:
        from oneirodex.utils.avatar import avatar_url

        return avatar_url(path)

    def commit(self) -> None:
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self) -> None:
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_account_stock_avatar_router(
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
    """Create POST `/api/account/avatar/stock` with Flask auth/CSRF parity."""
    router = APIRouter()
    data = data_access or StockAvatarData()

    @router.post('/api/account/avatar/stock')
    async def account_stock_avatar(request: Request):
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

            csrf_response = _csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                from oneirodex.utils.validation import format_validation_errors
                from oneirodex.schemas.account import StockAvatarBody

                body = _json_mapping(await request.body())
                try:
                    parsed = StockAvatarBody.model_validate(body)
                except ValidationError as exc:
                    payload, status = api_error_payload(
                        'Invalid request.',
                        code='unprocessable',
                        detail=format_validation_errors(exc),
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    path, error = data.set_stock(parsed.id, auth.user, flask_app)
                    if error:
                        payload, status = api_error_payload(error, code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            data.commit()
                        except Exception as exc:
                            data.rollback()
                            flask_app.logger.warning('stock avatar commit failed: %s', exc)
                            payload, status = api_error_payload(
                                "Couldn't save that avatar. Try a different image.",
                                code='internal',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload({
                                'avatar_path': path,
                                'avatar_url': data.avatar_url(path),
                            }))

            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_account_stock_avatar_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_stock_avatar_router(flask_app, **kwargs))
    return app


def _json_mapping(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


