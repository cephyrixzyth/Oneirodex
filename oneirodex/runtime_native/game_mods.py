"""Native FastAPI routes for per-game mod tracking and profiles."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


_SCHEMAS = {
    'row': 'ModRowBody',
    'bulk': 'ModPackBulkBody',
    'profile': 'ModProfileBody',
    'import': 'ModProfileImportBody',
    'pack': 'ModPackBody',
}


class GameModsData:
    """Adapter for game ACL, mod pack storage, profiles, and catalogue calls."""

    def enabled(self, flask_app):
        return str(flask_app.config.get('ENABLE_MOD_TRACKING', 'true')).lower() in (
            '1', 'true', 'yes', 'on',
        )

    def _context(self, flask_app):
        from oneirodex.utils.game_mods import mod_config_scope

        return mod_config_scope(flask_app.config)

    def game(self, flask_app, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        with self._context(flask_app):
            return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def accessible_games(self, flask_app, user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import apply_game_access_filters

        with self._context(flask_app):
            return db.session.execute(
                apply_game_access_filters(select(Game), user)
            ).scalars().all()

    def can_access_game(self, flask_app, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        with self._context(flask_app):
            return user_can_access_game(user, game)

    def load_mods(self, flask_app, game_uuid):
        from oneirodex.utils.game_mods import load_mods

        with self._context(flask_app):
            return load_mods(game_uuid)

    def mods_summary(self, flask_app, game_uuids):
        from oneirodex.utils.game_mods import list_mods_summary

        with self._context(flask_app):
            return list_mods_summary(game_uuids)

    def loader_conflicts(self, flask_app, pack):
        from oneirodex.utils.game_mods import loader_conflicts

        with self._context(flask_app):
            return loader_conflicts(pack)

    def catalog_sources(self):
        from oneirodex.utils.mod_catalog import source_ids

        return source_ids()

    def catalog_search(self, flask_app, source, game_name, query, limit, tracked):
        from oneirodex.utils.mod_catalog import catalog_search

        with self._context(flask_app):
            return catalog_search(source, game_name, query=query, limit=limit, tracked=tracked)

    def create_mod(self, flask_app, game_uuid, payload):
        from oneirodex.utils.game_mods import create_mod

        with self._context(flask_app):
            return create_mod(game_uuid, payload)

    def update_mod(self, flask_app, game_uuid, mod_id, payload):
        from oneirodex.utils.game_mods import update_mod

        with self._context(flask_app):
            return update_mod(game_uuid, mod_id, payload)

    def delete_mod(self, flask_app, game_uuid, mod_id):
        from oneirodex.utils.game_mods import delete_mod

        with self._context(flask_app):
            return delete_mod(game_uuid, mod_id)

    def save_mods(self, flask_app, game_uuid, mods, default_loader):
        from oneirodex.utils.game_mods import save_mods

        with self._context(flask_app):
            return save_mods(game_uuid, mods, default_loader=default_loader)

    def set_default_loader(self, flask_app, game_uuid, loader):
        from oneirodex.utils.game_mods import set_default_loader

        with self._context(flask_app):
            return set_default_loader(game_uuid, loader)

    def list_profiles(self, flask_app, game_uuid):
        from oneirodex.utils.game_mod_profiles import list_profiles

        with self._context(flask_app):
            return list_profiles(game_uuid)

    def create_profile(self, flask_app, game_uuid, name, mod_ids):
        from oneirodex.utils.game_mod_profiles import create_profile

        with self._context(flask_app):
            return create_profile(game_uuid, name=name, mod_ids=mod_ids)

    def delete_profile(self, flask_app, game_uuid, profile_id):
        from oneirodex.utils.game_mod_profiles import delete_profile

        with self._context(flask_app):
            return delete_profile(game_uuid, profile_id)

    def activate_profile(self, flask_app, game_uuid, profile_id):
        from oneirodex.utils.game_mod_profiles import activate_profile

        with self._context(flask_app):
            return activate_profile(game_uuid, profile_id)

    def export_profile(self, flask_app, game_uuid, profile_id):
        from oneirodex.utils.game_mod_profiles import export_profile

        with self._context(flask_app):
            return export_profile(game_uuid, profile_id)

    def import_profile(self, flask_app, game_uuid, code, name):
        from oneirodex.utils.game_mod_profiles import import_profile

        with self._context(flask_app):
            return import_profile(game_uuid, code, name=name)


def create_game_mods_router(
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
    data = data_access if data_access is not None else GameModsData()
    opts = dict(
        flask_app=flask_app, data=data, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager, database_scope=database_scope,
    )

    @router.api_route('/api/mods/summary', methods=['GET', 'HEAD'])
    async def mods_summary(request: Request):
        return await _run(request, **opts, handler=_summary)

    @router.api_route('/api/games/{game_uuid:str}/mods/catalog', methods=['GET', 'HEAD'])
    async def mods_catalog(game_uuid: str, request: Request):
        return await _run(request, **opts, handler=_catalog, game_uuid=game_uuid)

    @router.api_route('/api/games/{game_uuid:str}/mods/profiles/import', methods=['POST'])
    async def import_profile(game_uuid: str, request: Request):
        return await _run(request, **opts, handler=_import_profile, game_uuid=game_uuid, schema='import')

    @router.api_route('/api/games/{game_uuid:str}/mods/profiles/{profile_id:str}/activate', methods=['POST'])
    async def activate_profile(game_uuid: str, profile_id: str, request: Request):
        return await _run(request, **opts, handler=_activate_profile, game_uuid=game_uuid, profile_id=profile_id)

    @router.api_route('/api/games/{game_uuid:str}/mods/profiles/{profile_id:str}/export', methods=['GET', 'HEAD'])
    async def export_profile(game_uuid: str, profile_id: str, request: Request):
        return await _run(request, **opts, handler=_export_profile, game_uuid=game_uuid, profile_id=profile_id)

    @router.api_route('/api/games/{game_uuid:str}/mods/profiles/{profile_id:str}', methods=['DELETE'])
    async def delete_profile(game_uuid: str, profile_id: str, request: Request):
        return await _run(request, **opts, handler=_delete_profile, game_uuid=game_uuid, profile_id=profile_id)

    @router.api_route('/api/games/{game_uuid:str}/mods/profiles', methods=['GET', 'POST', 'HEAD'])
    async def game_profiles(game_uuid: str, request: Request):
        return await _run(
            request, **opts, handler=_profiles, game_uuid=game_uuid,
            schema='profile' if request.method == 'POST' else None,
        )

    @router.api_route('/api/games/{game_uuid:str}/mods/pack', methods=['PATCH'])
    async def patch_pack(game_uuid: str, request: Request):
        return await _run(request, **opts, handler=_patch_pack, game_uuid=game_uuid, schema='pack')

    @router.api_route('/api/games/{game_uuid:str}/mods/{mod_id:str}', methods=['PUT', 'PATCH', 'DELETE'])
    async def game_mod_detail(game_uuid: str, mod_id: str, request: Request):
        return await _run(
            request, **opts, handler=_mod_detail, game_uuid=game_uuid, mod_id=mod_id,
            schema='row' if request.method in ('PUT', 'PATCH') else None,
        )

    @router.api_route('/api/games/{game_uuid:str}/mods', methods=['GET', 'POST', 'PUT', 'HEAD'])
    async def game_mods(game_uuid: str, request: Request):
        schema = 'row' if request.method == 'POST' else 'bulk' if request.method == 'PUT' else None
        return await _run(request, **opts, handler=_game_mods, game_uuid=game_uuid, schema=schema)

    return router


def mount_game_mods_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_game_mods_router(flask_app, **kwargs))
    return app


async def _run(
    request, *, flask_app, data, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, handler, game_uuid=None,
    mod_id=None, profile_id=None, schema=None,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            from .csrf_compat import csrf_error_response

            response = csrf_error_response(request, auth.session_data, flask_app.config)
        else:
            response = None
        body = None
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None and schema:
            body, response = await _validate_body(request, schema)
        if response is None:
            try:
                response = await handler(
                    request, flask_app, data, auth, game_uuid=game_uuid,
                    mod_id=mod_id, profile_id=profile_id, body=body,
                )
            except Exception:
                response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _summary(request, app, data, auth, **_):
    if not data.enabled(app):
        return JSONResponse({'enabled': False, 'games': []})
    games = data.accessible_games(app, auth.user)
    rows = data.mods_summary(app, [game.uuid for game in games])
    names = {game.uuid: game.name for game in games}
    return JSONResponse({'enabled': True, 'games': [{**row, 'game_name': names.get(row['game_uuid'])} for row in rows]})


async def _game_read(app, data, auth, game_uuid):
    game = data.game(app, game_uuid)
    if game is None:
        return None, _error(404, 'not_found', 'Game not found')
    if not data.can_access_game(app, auth.user, game):
        return None, _error(403, 'forbidden', 'Forbidden')
    return game, None


def _librarian_denial(auth):
    from oneirodex.utils.role_catalog import normalize_role

    if auth.user is None:
        return _error(403, 'forbidden', 'Librarian or admin required')
    role = normalize_role(getattr(auth.user, 'role', None))
    if role not in ('librarian', 'admin'):
        return _error(403, 'forbidden', 'Librarian or admin required')
    if auth.token is not None and not auth.has_scope('admin'):
        return _error(403, 'forbidden', 'Librarian or admin required')
    return None


async def _catalog(request, app, data, auth, *, game_uuid, **_):
    if not data.enabled(app):
        return _mods_disabled()
    denied = _librarian_denial(auth)
    if denied:
        return denied
    game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    sources = data.catalog_sources()
    source = (request.query_params.get('source') or '').strip().lower()
    if source not in sources:
        return _error(400, 'bad_request', 'Unknown catalogue source', sources=sources)
    try:
        pack = data.load_mods(app, game_uuid)
        try:
            limit = int(request.query_params.get('limit')) if request.query_params.get('limit') is not None else None
        except (TypeError, ValueError):
            limit = None
        result = data.catalog_search(
            app, source, game.name or '', (request.query_params.get('q') or '').strip(),
            limit, pack['mods'],
        )
    except Exception:
        return _internal_error()
    return _ok({'game_uuid': game_uuid, **result})


async def _game_mods(request, app, data, auth, *, game_uuid, body, **_):
    if not data.enabled(app):
        return JSONResponse({'enabled': False, 'mods': []}) if request.method in ('GET', 'HEAD') else _mods_disabled()
    if request.method in ('POST', 'PUT'):
        denied = _librarian_denial(auth)
        if denied:
            return denied
    game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    if request.method in ('GET', 'HEAD'):
        try:
            pack = data.load_mods(app, game_uuid)
            return JSONResponse({'enabled': True, **pack, 'loader_conflicts': data.loader_conflicts(app, pack)})
        except Exception:
            return _internal_error()
    try:
        if request.method == 'POST':
            created = data.create_mod(app, game_uuid, body.payload())
            return _ok({'mod': created}, status=201)
        return _ok(data.save_mods(app, game_uuid, body.mods, body.default_loader))
    except ValueError as exc:
        return _error(400, 'bad_request', str(exc))
    except Exception:
        return _internal_error()


async def _mod_detail(request, app, data, auth, *, game_uuid, mod_id, body, **_):
    if not data.enabled(app):
        return _mods_disabled()
    denied = _librarian_denial(auth)
    if denied:
        return denied
    _game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        if request.method == 'DELETE':
            if not data.delete_mod(app, game_uuid, mod_id):
                return _error(404, 'not_found', 'Mod not found')
            return _ok({'id': mod_id})
        updated = data.update_mod(app, game_uuid, mod_id, body.payload())
        return _ok({'mod': updated})
    except LookupError:
        return _error(404, 'not_found', 'Mod not found')
    except ValueError as exc:
        return _error(400, 'bad_request', str(exc))
    except Exception:
        return _internal_error()


async def _profiles(request, app, data, auth, *, game_uuid, body, **_):
    if not data.enabled(app):
        return _mods_disabled()
    denied = _librarian_denial(auth) if request.method == 'POST' else None
    if denied:
        return denied
    _game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        if request.method == 'GET':
            return _ok({'game_uuid': game_uuid, **data.list_profiles(app, game_uuid)})
        profile = data.create_profile(app, game_uuid, body.name, body.mod_ids)
        return _ok({'profile': profile, **data.list_profiles(app, game_uuid)}, status=201)
    except ValueError as exc:
        return _error(400, 'bad_request', str(exc))
    except Exception:
        return _internal_error()


async def _librarian_profile_preamble(app, data, auth, game_uuid):
    if not data.enabled(app):
        return None, _mods_disabled()
    denied = _librarian_denial(auth)
    if denied:
        return None, denied
    return await _game_read(app, data, auth, game_uuid)


async def _delete_profile(request, app, data, auth, *, game_uuid, profile_id, **_):
    _game, denied = await _librarian_profile_preamble(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        if not data.delete_profile(app, game_uuid, profile_id):
            return _error(404, 'not_found', 'Profile not found')
        return _ok({'id': profile_id, **data.list_profiles(app, game_uuid)})
    except Exception:
        return _internal_error()


async def _activate_profile(request, app, data, auth, *, game_uuid, profile_id, **_):
    _game, denied = await _librarian_profile_preamble(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        return _ok(data.activate_profile(app, game_uuid, profile_id))
    except LookupError:
        return _error(404, 'not_found', 'Profile not found')
    except Exception:
        return _internal_error()


async def _export_profile(request, app, data, auth, *, game_uuid, profile_id, **_):
    if not data.enabled(app):
        return _mods_disabled()
    _game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        code = data.export_profile(app, game_uuid, profile_id)
    except LookupError:
        return _error(404, 'not_found', 'Profile not found')
    except Exception:
        return _internal_error()
    return _ok({'profile_id': profile_id, 'code': code})


async def _import_profile(request, app, data, auth, *, game_uuid, body, **_):
    _game, denied = await _librarian_profile_preamble(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        result = data.import_profile(app, game_uuid, body.code, body.name)
        return _ok({**result, **data.list_profiles(app, game_uuid)}, status=201)
    except ValueError as exc:
        return _error(400, 'bad_request', str(exc))
    except Exception:
        return _internal_error()


async def _patch_pack(request, app, data, auth, *, game_uuid, body, **_):
    if not data.enabled(app):
        return _mods_disabled()
    denied = _librarian_denial(auth)
    if denied:
        return denied
    _game, denied = await _game_read(app, data, auth, game_uuid)
    if denied:
        return denied
    try:
        return _ok(data.set_default_loader(app, game_uuid, body.default_loader))
    except Exception:
        return _internal_error()


async def _validate_body(request, schema_key):
    from oneirodex.schemas import game_mods as schemas
    from oneirodex.utils.validation import format_validation_errors

    payload = {}
    if request.headers.get('content-type', '').lower().startswith('application/json'):
        try:
            value = await request.json()
            payload = value if isinstance(value, dict) else {}
        except Exception:
            payload = {}
    model = getattr(schemas, _SCHEMAS[schema_key])
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        return None, _error(
            422, 'unprocessable', 'Invalid request.',
            detail=format_validation_errors(exc),
        )


def _mods_disabled():
    return _error(403, 'forbidden', 'ENABLE_MOD_TRACKING is off', enabled=False)


def _internal_error():
    return _error(500, 'internal', 'An error occurred while processing your request')


def _ok(payload=None, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)


def _login_redirect(flask_app, request, login_manager, auth):
    from .acquire_status import _login_redirect as login_redirect

    return login_redirect(flask_app, request, login_manager, auth)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
