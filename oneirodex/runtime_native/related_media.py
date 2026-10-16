"""Native FastAPI routes for related media on member game details."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

MEDIA_KINDS = {
    'film': 'Film', 'series': 'TV series', 'anime': 'Anime', 'book': 'Book',
    'comic': 'Comic', 'music': 'Soundtrack / music', 'podcast': 'Podcast',
}
RELATIONS = {
    'adaptation': 'Adaptation of this game', 'tie_in': 'Tie-in',
    'soundtrack': 'Soundtrack', 'novelisation': 'Novelisation',
    'documentary': 'Documentary', 'inspired_by': 'Inspired by this game',
}
_DOWNLOADISH = ('download', 'torrent', 'magnet:', '.iso', '.mkv', '.mp4', 'warez')


class RelatedMediaData:
    def game(self, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def items(self, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRelatedMedia

        rows = db.session.execute(
            select(GameRelatedMedia).filter_by(game_uuid=game_uuid)
            .order_by(GameRelatedMedia.display_order.asc(), GameRelatedMedia.id.asc())
        ).scalars().all()
        return [row.to_dict() for row in rows]

    def create(self, game_uuid, user, payload):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRelatedMedia

        row = GameRelatedMedia(
            game_uuid=game_uuid,
            media_kind=payload['media_kind'],
            relation=payload['relation'],
            title=payload['title'][:240],
            creator=payload['creator'],
            year=payload['year'],
            summary=payload['summary'],
            external_url=payload['external_url'],
            cover_url=payload['cover_url'],
            display_order=payload['display_order'],
            created_by_user_id=getattr(user, 'id', None),
        )
        db.session.add(row)
        db.session.commit()
        return row.to_dict()

    def delete(self, game_uuid, item_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRelatedMedia

        row = db.session.get(GameRelatedMedia, item_id)
        if row is None or row.game_uuid != game_uuid:
            return False
        db.session.delete(row)
        db.session.commit()
        return True


def create_related_media_router(
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
    data = data_access or RelatedMediaData()

    @router.api_route('/api/games/{game_uuid}/related_media', methods=['GET', 'HEAD'])
    def related_media_list(game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                game = data.game(game_uuid)
                if game is None:
                    response = _error('Game not found', 'not_found')
                elif not data.can_access(auth.user, game):
                    response = _error('Forbidden', 'forbidden')
                else:
                    items = data.items(game_uuid)
                    counts = {}
                    for item in items:
                        kind = item['media_kind']
                        counts[kind] = counts.get(kind, 0) + 1
                    response = _success({
                        'game_uuid': game_uuid,
                        'items': items,
                        'available_kinds': [kind for kind in MEDIA_KINDS if counts.get(kind)],
                        'counts': counts,
                        'kinds': [{'id': key, 'label': label} for key, label in MEDIA_KINDS.items()],
                        'relations': [{'id': key, 'label': label} for key, label in RELATIONS.items()],
                    })
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/games/{game_uuid}/related_media')
    async def related_media_create(game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and not _is_librarian(auth):
                response = _error('Librarian or admin required', 'forbidden')
            if response is None:
                try:
                    from oneirodex.schemas.related_media import CreateRelatedMediaBody
                    from oneirodex.utils.validation import format_validation_errors

                    body = CreateRelatedMediaBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                if response is None:
                    game = data.game(game_uuid)
                    if game is None:
                        response = _error('Game not found', 'not_found')
                    else:
                        values, refusal = _create_values(body)
                        if refusal is not None:
                            response = refusal
                        else:
                            response = _success(
                                {'item': data.create(game_uuid, auth.user, values)}, status=201,
                            )
            _finish(response, flask_app, request, auth)
            return response

    @router.delete('/api/games/{game_uuid}/related_media/{item_id:int}')
    def related_media_delete(game_uuid: str, item_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and not _is_librarian(auth):
                response = _error('Librarian or admin required', 'forbidden')
            if response is None:
                response = (
                    _success({'removed': item_id})
                    if data.delete(game_uuid, item_id)
                    else _error('Item not found', 'not_found')
                )
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_related_media_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_related_media_router(flask_app, **kwargs))
    return app


def _create_values(body):
    kind = (body.media_kind or '').strip().lower()
    if kind not in MEDIA_KINDS:
        return None, _error(
            f"media_kind must be one of: {', '.join(sorted(MEDIA_KINDS))}", 'bad_request',
        )
    relation = (body.relation or 'tie_in').strip().lower()
    if relation not in RELATIONS:
        return None, _error(
            f"relation must be one of: {', '.join(sorted(RELATIONS))}", 'bad_request',
        )
    try:
        external_url = _clean_url(body.external_url)
        cover_url = _clean_url(body.cover_url)
    except ValueError as exc:
        return None, _error(str(exc), 'bad_request')
    try:
        year = int(body.year) if body.year not in (None, '') else None
    except (TypeError, ValueError):
        return None, _error('year must be a number', 'bad_request')
    return {
        'media_kind': kind,
        'relation': relation,
        'title': body.title,
        'creator': (body.creator or '').strip()[:160] or None,
        'year': year,
        'summary': (body.summary or '').strip()[:1000] or None,
        'external_url': external_url,
        'cover_url': cover_url,
        'display_order': int(body.display_order or 0),
    }, None


def _clean_url(raw):
    url = (raw or '').strip()
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        raise ValueError('Link must be an http(s) URL')
    if any(token in url.lower() for token in _DOWNLOADISH):
        raise ValueError('Link must point at a store or stream page, not a download')
    return url[:500]


async def _json_object(request):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — malformed JSON becomes an empty object
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_librarian(auth):
    from oneirodex.utils.role_catalog import role_at_least

    if not role_at_least(getattr(auth.user, 'role', None), 'librarian'):
        return False
    return auth.token is None or auth.has_scope('admin')


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
