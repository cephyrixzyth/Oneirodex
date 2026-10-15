"""FastAPI read for checking whether an IGDB id is already in the library."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


class IgdbAvailabilityData:
    def exists(self, igdb_id: int) -> bool:
        from oneirodex.utils.game_core import check_existing_game_by_igdb_id

        return check_existing_game_by_igdb_id(igdb_id) is not None

    def cover_url(self, igdb_id: int):
        from oneirodex.utils.igdb_api import get_cover_thumbnail_url

        return get_cover_thumbnail_url(igdb_id)


def create_igdb_availability_router(
    flask_app, *, find_user, find_token, commit_token_touch,
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
):
    from .acquire_status import _login_redirect

    router = APIRouter()
    data = data_access or IgdbAvailabilityData()

    @router.api_route('/api/check_igdb_id', methods=['GET', 'HEAD'])
    def check_igdb_id(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                raw = request.query_params.get('igdb_id')
                try:
                    igdb_id = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    igdb_id = None
                if igdb_id is None:
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'Invalid request', code='bad_request', available=False,
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        response = JSONResponse({'available': not data.exists(igdb_id)})
                    except Exception:  # noqa: BLE001 — keep database details private
                        from oneirodex.utils.api_contract import api_error_payload

                        payload, status = api_error_payload(
                            'Could not check the IGDB id.', code='internal',
                        )
                        response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                headers = dict(response.headers)
                headers.setdefault('content-length', str(len(getattr(response, 'body', b''))))
                return Response(content=b'', status_code=response.status_code, headers=headers)
            return response

    @router.api_route('/api/get_cover_thumbnail', methods=['GET', 'HEAD'])
    def get_cover_thumbnail(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                raw = request.query_params.get('igdb_id')
                try:
                    igdb_id = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    igdb_id = None
                if igdb_id is None or igdb_id < 0:
                    response = _api_error('Invalid input. The ID must be numeric.', 'bad_request', 400)
                else:
                    try:
                        cover_url = data.cover_url(igdb_id)
                    except Exception:  # noqa: BLE001 — no provider internals in client error
                        cover_url = None
                    if cover_url:
                        response = JSONResponse({'cover_url': cover_url})
                    else:
                        response = _api_error('Cover URL could not be retrieved.', 'not_found', 404)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                headers = dict(response.headers)
                headers.setdefault('content-length', str(len(getattr(response, 'body', b''))))
                return Response(content=b'', status_code=response.status_code, headers=headers)
            return response

    return router


def _api_error(message, code, status):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def mount_igdb_availability_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_igdb_availability_router(flask_app, **kwargs))
    return app
