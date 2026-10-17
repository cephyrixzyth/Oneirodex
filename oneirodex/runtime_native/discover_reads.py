"""Native FastAPI read routes for Discover sections and row windows."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response
from werkzeug.datastructures import MultiDict

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class DiscoverReadsData:
    """Adapter around the existing Discover feed and row builders."""

    def sections(self, user) -> dict:
        from oneirodex.utils.discover_builder import build_discover_feed

        return build_discover_feed(user)

    def row(self, user, identifier: str, *, offset: int, feed_token: str | None, limit=None):
        from oneirodex.utils.discover_builder import build_discover_row

        kwargs = {'offset': offset, 'feed_token': feed_token}
        if limit:
            kwargs['limit'] = limit
        return build_discover_row(user, identifier, **kwargs)

    def zone(self, user, slug: str):
        from oneirodex.utils.discover_builder import build_discover_zone

        return build_discover_zone(user, slug)

    def genre_hub(self, user, genre: str):
        from oneirodex.utils.discover_hubs import build_genre_hub

        return build_genre_hub(user, genre)

    def genre_by_id(self, genre_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Genre

        return db.session.get(Genre, genre_id)

    def surprise(self, user, genre, exclude: list[str]) -> dict:
        from oneirodex.utils.discover_ml.surprise import pick_surprise, taste_genres
        from oneirodex.utils.discover_hydrate import DiscoverHydration
        from oneirodex.utils.discover_projections import serialize_discover_game

        pick = pick_surprise(user, genre=genre, exclude=exclude)
        card = None
        if pick.game is not None:
            hydration = DiscoverHydration(user)
            hydration.prime([pick.game])
            card = serialize_discover_game(
                pick.game,
                hydration.cover_for(pick.game),
                **hydration.serializer_kwargs(pick.game),
            )
        return {
            'game': card,
            'reason': pick.reason,
            'genre': {'id': genre.id, 'name': genre.name} if genre is not None else None,
            'genres': [
                {'id': taste.id, 'name': taste.name}
                for taste in taste_genres(user.id)
            ],
        }

    def pins(self, user) -> dict:
        from oneirodex.utils.discover_feed import MAX_MEMBER_PINS
        from oneirodex.utils.discover_pins import hidden_rows, member_pins
        from oneirodex.utils.discover_providers import resolve_feed

        available = [row.identifier for row in resolve_feed(user)]
        return {
            'pins': member_pins(user, available=available),
            'hidden': hidden_rows(user, available=available),
            'max_pins': MAX_MEMBER_PINS,
            'available': available,
        }

    def save_pins(self, user, payload: dict) -> dict:
        from oneirodex.utils.discover_feed import MAX_MEMBER_PINS
        from oneirodex.utils.discover_pins import (
            PinnedByAdmin, hidden_rows, member_pins, set_hidden_rows, set_member_pins,
        )
        from oneirodex.utils.discover_providers import resolve_feed

        available = [row.identifier for row in resolve_feed(user)]
        requested = payload.get('pins')
        requested_hidden = payload.get('hidden')
        if requested is None and requested_hidden is None:
            return {'error': ('Send pins, hidden, or both as lists of row identifiers.', 'bad_request')}
        if requested is not None and not isinstance(requested, list):
            return {'error': ('Send pins as a list of row identifiers.', 'bad_request')}
        if requested_hidden is not None and not isinstance(requested_hidden, list):
            return {'error': ('Send hidden as a list of row identifiers.', 'bad_request')}
        if requested is not None and len(requested) > MAX_MEMBER_PINS:
            return {'error': (f'You can pin up to {MAX_MEMBER_PINS} rows.', 'unprocessable')}
        try:
            if requested is not None:
                set_member_pins(user, requested, available=available)
            if requested_hidden is not None:
                set_hidden_rows(user, requested_hidden, available=available)
        except PinnedByAdmin as forced:
            return {'error': ('That row was pinned by an admin and cannot be hidden.', 'forbidden', str(forced))}
        except ValueError as unknown:
            return {'error': ('That row is not on your Discover feed.', 'not_found', str(unknown))}
        return {
            'pins': member_pins(user, available=available),
            'hidden': hidden_rows(user, available=available),
            'max_pins': MAX_MEMBER_PINS,
        }


def create_discover_reads_router(
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
    """Build native GET/HEAD handlers with Flask-compatible member sessions."""
    router = APIRouter()
    data = data_access or DiscoverReadsData()

    def request_scope():
        return database_scope(flask_app) if database_scope else nullcontext()

    def authenticate(request: Request):
        return request_auth_context(
            request,
            flask_app.config,
            find_user=find_user,
            find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id,
            login_manager=login_manager,
        )

    def secure(response: Response, request: Request, auth=None):
        if auth is not None and auth.should_set_session_cookie:
            from .acquire_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def anonymous(request: Request, auth):
        return _login_redirect(flask_app, request, login_manager, auth)

    @router.api_route('/api/discover/sections', methods=['GET', 'HEAD'])
    def discover_sections(request: Request):
        with request_scope():
            auth = authenticate(request)
            if auth.user is None:
                response = anonymous(request, auth)
            else:
                response = _native_json_response(flask_app, data.sections(auth.user))
            return secure(response, request)

    @router.api_route('/api/discover/rows/{identifier}', methods=['GET', 'HEAD'])
    def discover_row(identifier: str, request: Request):
        with request_scope():
            auth = authenticate(request)
            if auth.user is None:
                response = anonymous(request, auth)
                return secure(response, request)

            args = MultiDict(request.query_params.multi_items())
            try:
                offset = int(args.get('offset', 0))
                limit = int(args.get('limit', 0)) or None
            except (TypeError, ValueError):
                return secure(_api_error_response(
                    flask_app, 'Row offset and limit must be whole numbers.', 'bad_request',
                ), request)

            feed_token = args.get('feed_token') or None
            payload = data.row(
                auth.user,
                identifier,
                offset=offset,
                feed_token=feed_token,
                **({'limit': limit} if limit else {}),
            )
            if payload is None:
                response = _api_error_response(
                    flask_app, 'That Discover row is not available.', 'not_found', detail=identifier,
                )
            else:
                response = _api_ok_response(flask_app, payload)
            return secure(response, request)

    @router.api_route('/api/discover/zones/{slug}', methods=['GET', 'HEAD'])
    def discover_zone(slug: str, request: Request):
        with request_scope():
            auth = authenticate(request)
            if auth.user is None:
                response = anonymous(request, auth)
                return secure(response, request)

            payload = data.zone(auth.user, slug)
            if payload is None:
                response = _api_error_response(
                    flask_app, 'That Discover zone is not available.', 'not_found', detail=slug,
                )
            else:
                response = _api_ok_response(flask_app, payload)
            return secure(response, request)

    @router.api_route('/api/discover/hubs/genre/{genre:path}', methods=['GET', 'HEAD'])
    def discover_genre_hub(genre: str, request: Request):
        with request_scope():
            auth = authenticate(request)
            if auth.user is None:
                response = anonymous(request, auth)
                return secure(response, request)

            payload = data.genre_hub(auth.user, genre)
            if payload is None:
                response = _api_error_response(
                    flask_app, 'That genre is not in this library.', 'not_found',
                )
            else:
                response = _api_ok_response(flask_app, payload)
            return secure(response, request)

    @router.api_route('/api/discover/surprise', methods=['GET', 'HEAD'])
    def discover_surprise(request: Request):
        with request_scope():
            auth = authenticate(request)
            if auth.user is None:
                response = anonymous(request, auth)
                return secure(response, request)

            args = MultiDict(request.query_params.multi_items())
            genre = None
            raw_genre = (args.get('genre') or '').strip()
            if raw_genre:
                try:
                    genre_id = int(raw_genre)
                except ValueError:
                    return secure(_api_error_response(
                        flask_app, 'Genre must be a genre id.', 'bad_request',
                    ), request)
                genre = data.genre_by_id(genre_id)
                if genre is None:
                    return secure(_api_error_response(
                        flask_app, 'That genre is not in this library.', 'not_found',
                    ), request)

            exclude = [part for part in (args.get('exclude') or '').split(',') if part]
            return secure(_api_ok_response(
                flask_app, data.surprise(auth.user, genre, exclude),
            ), request)

    @router.api_route('/api/discover/pins', methods=['GET', 'HEAD', 'PUT'])
    async def discover_pins(request: Request):
        with request_scope():
            auth = authenticate(request)
            if (
                request.method == 'PUT'
                and auth.token is not None
                and not auth.has_scope('write:library')
            ):
                return secure(_api_error_response(
                    flask_app, 'Forbidden', 'forbidden',
                ), request, auth)
            if request.method == 'PUT' and auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
                if response is not None:
                    return secure(response, request, auth)
            if auth.user is None:
                response = anonymous(request, auth)
            elif request.method == 'HEAD':
                from oneirodex.utils.api_contract import api_error_payload
                from .runtime_context import native_json_response

                payload, status = api_error_payload(
                    'Send pins, hidden, or both as lists of row identifiers.',
                    code='bad_request',
                )
                response = native_json_response(
                    payload, config=flask_app.config, status=status,
                )
            elif request.method == 'PUT':
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                result = data.save_pins(auth.user, payload)
                error = result.get('error')
                if error:
                    response = _api_error_response(
                        flask_app, error[0], error[1],
                        **({'detail': error[2]} if len(error) > 2 else {}),
                    )
                else:
                    response = _api_ok_response(flask_app, result)
            else:
                response = _api_ok_response(flask_app, data.pins(auth.user))
            return secure(response, request, auth)

    return router


def mount_discover_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_discover_reads_router(flask_app, **kwargs))
    return app


def _native_json_response(flask_app, payload, status: int = 200) -> Response:
    return Response(
        content=flask_app.json.dumps(payload),
        status_code=status,
        media_type='application/json',
    )


def _api_ok_response(flask_app, payload, status: int = 200) -> Response:
    from oneirodex.utils.api_contract import api_ok_payload

    return _native_json_response(flask_app, api_ok_payload(payload), status)


def _api_error_response(flask_app, message: str, code: str, *, detail=None) -> Response:
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return _native_json_response(flask_app, payload, status)
