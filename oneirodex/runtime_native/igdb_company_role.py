"""Native authenticated IGDB company-role lookup."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class IGDBCompanyRoleData:
    def lookup(self, game_igdb_id: str, company_id: str):
        from oneirodex.utils.igdb_api import make_igdb_api_request

        return make_igdb_api_request(
            'https://api.igdb.com/v4/involved_companies',
            f'fields company.name, developer, publisher, game; '
            f'where game={game_igdb_id} & id=({company_id});',
        )

    def search_game_by_id(self, igdb_id: str):
        from oneirodex.utils.igdb_api import make_igdb_api_request

        return make_igdb_api_request(
            'https://api.igdb.com/v4/games',
            f'''fields id, name, cover, summary, url, release_dates.date, platforms.name,
                genres.name, themes.name, game_modes.name, screenshots, videos.video_id,
                first_release_date, aggregated_rating, involved_companies,
                player_perspectives.name, aggregated_rating_count, rating, rating_count,
                slug, status, category, total_rating, total_rating_count, storyline;
                where id = {igdb_id};''',
        )

    def search_games_by_name(self, game_name: str, platform_id: str | None):
        from oneirodex.utils.igdb_api import make_igdb_api_request

        query_fields = '''fields id, name, cover, summary, url, release_dates.date, platforms.name, genres.name, themes.name, game_modes.name,
                          screenshots, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
                          aggregated_rating_count, rating, rating_count, slug, status, category, total_rating, 
                          total_rating_count, storyline;'''
        query_filter = f'search "{game_name}";'
        if platform_id and platform_id.isdigit():
            query_filter += f' where platforms = ({platform_id});'
        query_filter += ' limit 10;'
        return make_igdb_api_request(
            'https://api.igdb.com/v4/games', query_fields + query_filter,
        )


def create_igdb_company_role_router(
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
    data = data_access or IGDBCompanyRoleData()

    @router.api_route('/api/get_company_role', methods=['GET', 'HEAD'])
    def get_company_role(request: Request):
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
                game_id = request.query_params.get('game_igdb_id')
                company_id = request.query_params.get('company_id')
                if not game_id or not company_id or not game_id.isdigit() or not company_id.isdigit():
                    response = _api_error(
                        'Invalid input. Both game_igdb_id and company_id must be provided and numeric.',
                        'bad_request', 400, config=flask_app.config,
                    )
                else:
                    try:
                        rows = data.lookup(game_id, company_id)
                    except Exception:
                        response = _api_error(
                            'An error occurred processing your request.', 'internal', 500,
                            config=flask_app.config,
                        )
                    else:
                        if not rows or (isinstance(rows, dict) and 'error' in rows):
                            response = _api_error(
                                'No data found or error in response.', 'not_found', 404,
                                config=flask_app.config,
                            )
                        else:
                            response = None
                            for row in rows:
                                company = row.get('company') if isinstance(row, dict) else None
                                if not isinstance(company, dict):
                                    continue
                                role = (
                                    'Developer' if row.get('developer', False)
                                    else 'Publisher' if row.get('publisher', False)
                                    else 'Not Found'
                                )
                                response = JSONResponse({
                                    'game_igdb_id': game_id,
                                    'company_id': company_id,
                                    'company_name': company.get('name', 'Unknown Company'),
                                    'role': role,
                                })
                                break
                            if response is None:
                                response = _api_error(
                                    'Company with given ID not found in the specified game.',
                                    'not_found', 404, config=flask_app.config,
                                )
            from oneirodex.utils.security_headers import security_header_values

            response.headers.setdefault('Cache-Control', 'no-store')
            response.headers.setdefault('Vary', 'Cookie')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/search_igdb_by_id', methods=['GET', 'HEAD'])
    def search_igdb_by_id(request: Request):
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
                igdb_id = request.query_params.get('igdb_id')
                if not igdb_id:
                    response = _api_error(
                        'IGDB ID is required', 'bad_request', 400, config=flask_app.config,
                    )
                elif not igdb_id.isascii() or not igdb_id.isdigit():
                    response = _api_error(
                        'IGDB ID must be numeric', 'bad_request', 400, config=flask_app.config,
                    )
                else:
                    try:
                        result = data.search_game_by_id(igdb_id)
                    except Exception:
                        response = _api_error(
                            'Request failed', 'internal', 500, config=flask_app.config,
                        )
                    else:
                        if isinstance(result, dict) and 'error' in result:
                            response = _api_error(
                                str(result['error']), 'internal', 500, config=flask_app.config,
                            )
                        elif result:
                            response = JSONResponse(result[0])
                        else:
                            response = _api_error(
                                'Game not found', 'not_found', 404, config=flask_app.config,
                            )
            from oneirodex.utils.security_headers import security_header_values

            response.headers.setdefault('Cache-Control', 'no-store')
            response.headers.setdefault('Vary', 'Cookie')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/search_igdb_by_name', methods=['GET', 'HEAD'])
    def search_igdb_by_name(request: Request):
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
                names = request.query_params.getlist('name')
                game_name = names[0] if names else None
                platforms = request.query_params.getlist('platform_id')
                platform_id = platforms[0] if platforms else None
                if not game_name:
                    response = _api_error(
                        'No game name provided', 'bad_request', 400, config=flask_app.config,
                    )
                else:
                    try:
                        results = data.search_games_by_name(game_name, platform_id)
                    except Exception:
                        response = _api_error(
                            'Request failed', 'internal', 500, config=flask_app.config,
                        )
                    else:
                        if isinstance(results, dict) and 'error' in results:
                            response = _api_error(
                                str(results['error']), 'bad_gateway', 502,
                                config=flask_app.config,
                            )
                        else:
                            response = JSONResponse({'results': results})
            from oneirodex.utils.security_headers import security_header_values

            response.headers.setdefault('Cache-Control', 'no-store')
            response.headers.setdefault('Vary', 'Cookie')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def _api_error(message: str, code: str, status: int, *, config) -> Response:
    from oneirodex.utils.api_contract import api_error_payload
    from .runtime_context import native_json_response

    payload, _ = api_error_payload(message, code=code, status=status)
    return native_json_response(payload, config=config, status=status)


def mount_igdb_company_role_routes(app: FastAPI, flask_app, **kwargs):
    from .igdb_company_role import create_igdb_company_role_router

    app.include_router(create_igdb_company_role_router(flask_app, **kwargs))
    return app
