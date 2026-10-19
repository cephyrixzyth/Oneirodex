"""FastAPI adapters for classic manual game add/edit form submissions."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.datastructures import FormData
from starlette.requests import Request as StarletteRequest
from starlette.responses import RedirectResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context
from .manual_identify_mutations import ManualIdentifyMutationData

_PROVIDER_KEYS = {
    'steam', 'gog', 'epicgames', 'itch', 'rawg', 'mobygames',
    'thegamesdb', 'official', 'wikipedia',
}
_TAXONOMY_FIELDS = {
    'genres': 'genre_ids',
    'game_modes': 'game_mode_ids',
    'themes': 'theme_ids',
    'platforms': 'platform_ids',
    'player_perspectives': 'player_perspective_ids',
}


def create_legacy_manual_identify_router(
    app, *, find_user: Callable[[int], Any | None], find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None], load_user_id=None, login_manager=None,
    data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ManualIdentifyMutationData()

    @router.post('/add_game_manual')
    async def add_game_manual(request: Request):
        return await _handle(request, app, data, action='create', game_uuid=None,
                             find_user=find_user, find_token=find_token,
                             commit_token_touch=commit_token_touch,
                             load_user_id=load_user_id, login_manager=login_manager,
                             database_scope=database_scope)

    @router.post('/game_edit/{game_uuid}')
    async def edit_game(game_uuid: str, request: Request):
        return await _handle(request, app, data, action='update', game_uuid=game_uuid,
                             find_user=find_user, find_token=find_token,
                             commit_token_touch=commit_token_touch,
                             load_user_id=load_user_id, login_manager=login_manager,
                             database_scope=database_scope)

    return router


async def _handle(request, app, data, *, action, game_uuid, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager, database_scope):
    from .csrf_compat import csrf_error_response
    from oneirodex.utils.role_catalog import normalize_role

    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        form, too_large = await _bounded_form(request, app.config)
        if too_large:
            from starlette.responses import Response

            return _finish(Response(status_code=413), app, None, request)
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        token_name = str(app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
        csrf = csrf_error_response(
            request, auth.session_data, app.config,
            token=str(form.get(token_name) or ''),
        ) if auth.token is None else None
        if csrf is not None:
            response = _csrf_html_response(csrf)
        elif auth.user is None:
            response = _login_redirect(app, request, login_manager, auth)
        elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
            response = _login_redirect(
                app, request, login_manager, auth,
                message='You must be an admin to access this page.',
                category='danger', include_next=False,
            )
        elif auth.token is not None and not auth.has_scope('admin'):
            from oneirodex.utils.api_contract import api_error_payload
            from starlette.responses import JSONResponse

            payload, status = api_error_payload(
                'This token does not have the admin scope', code='forbidden',
            )
            response = JSONResponse(payload, status_code=status)
        else:
            try:
                from oneirodex.schemas.manual_identify import ManualIdentifyBody
                from pydantic import ValidationError

                payload = _form_payload(form, request)
                body = ManualIdentifyBody.model_validate(payload)
                if action == 'create':
                    outcome = data.create(
                        app, body, auth.user,
                        from_unmatched=request.query_params.get('from_unmatched') == 'true',
                    )
                else:
                    outcome = data.update(app, game_uuid, body, auth.user)
            except (ValidationError, TypeError, ValueError):
                outcome = {'error': 'Please correct the game details and try again.', 'code': 'bad_request'}
            except Exception:
                app.logger.exception('Legacy manual-identify form adapter failed')
                outcome = {'error': 'The game could not be saved. Please try again.', 'code': 'internal'}

            if outcome.get('error'):
                _flash(auth, 'error', outcome['error'])
                response = RedirectResponse(_return_to_form(request, action), status_code=303)
            else:
                if action == 'create':
                    _flash(auth, 'success', 'Game added successfully.')
                    destination = (
                        '/scan_management?active_tab=unmatched'
                        if request.query_params.get('from_unmatched') == 'true'
                        else '/libraries'
                    )
                else:
                    _flash(auth, 'image-refresh' if outcome.get('image_refresh_started') else 'success',
                           'Game updated successfully.' if not outcome.get('image_refresh_started')
                           else 'Game updated, downloading images')
                    destination = '/library'
                response = RedirectResponse(destination, status_code=303)
        return _finish(response, app, auth, request)


def _csrf_html_response(csrf):
    import json

    from werkzeug.exceptions import BadRequest

    try:
        error_payload = json.loads(csrf.body or b'{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        error_payload = {}
    bad_request = BadRequest(
        description=error_payload.get('message') or 'The CSRF token is invalid.',
    ).get_response()
    return Response(
        content=bad_request.get_data(),
        status_code=bad_request.status_code,
        media_type='text/html',
    )


async def _bounded_form(request, config):
    limit = min(int(config.get('MAX_CONTENT_LENGTH') or 512 * 1024), 512 * 1024)
    try:
        too_large = int(request.headers.get('content-length') or 0) > limit
    except (TypeError, ValueError):
        too_large = True
    chunks = []
    size = 0
    if not too_large:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                too_large = True
                chunks = []
                break
            chunks.append(chunk)
    if too_large:
        return FormData(), True
    replay = StarletteRequest(request.scope, receive=_body_receive(b''.join(chunks)))
    try:
        form = await replay.form(max_files=0, max_fields=256, max_part_size=64 * 1024)
        return form, False
    except Exception:
        return FormData(), False


def _form_payload(form, request):
    payload = {
        'igdb_id': form.get('igdb_id'),
        'name': form.get('name'),
        'full_disk_path': form.get('full_disk_path'),
        'library_uuid': form.get('library_uuid') or request.query_params.get('library_uuid'),
        'summary': form.get('summary') or '',
        'storyline': form.get('storyline') or '',
        'url': form.get('url') or '',
        'video_urls': form.get('video_urls') or '',
        'aggregated_rating': form.get('aggregated_rating') or None,
        'first_release_date': form.get('first_release_date') or None,
        'status': str(form.get('status') or '').replace('Status.', '').strip(),
        'category': str(form.get('category') or '').replace('Category.', '').strip(),
        'developer': form.get('developer') or '',
        'publisher': form.get('publisher') or '',
        'item_kind': form.get('item_kind') or request.query_params.get('item_kind') or '',
        'provider_urls': {
            key: str(form.get(f'provider_url_{key}') or '').strip()
            for key in _PROVIDER_KEYS if f'provider_url_{key}' in form
        },
    }
    for field, model_key in _TAXONOMY_FIELDS.items():
        values = form.getlist(field)
        # Legacy QuerySelectMultipleField submits database identifiers.
        payload[model_key] = [int(value) for value in values if str(value).isdigit()]
    return payload


def _return_to_form(request, action):
    if action == 'update':
        return f'/game_edit/{request.path_params.get("game_uuid", "")}'
    from urllib.parse import urlencode

    allowed = ('full_disk_path', 'library_uuid', 'from_unmatched', 'igdb_id', 'item_kind')
    query = [(key, request.query_params.get(key)) for key in allowed if request.query_params.get(key)]
    return '/add_game_manual' + ('?' + urlencode(query) if query else '')


def _flash(auth, category, message):
    if auth is None:
        return
    auth.session_data.setdefault('_flashes', []).append((category, message))


def _finish(response, app, auth, request):
    if auth is not None and (auth.should_set_session_cookie or auth.session_data.get('_flashes')):
        _set_session_cookie(response, app, auth)
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(app.config).items():
        response.headers.setdefault(key, value)
    return response


def _body_receive(raw):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        sent = True
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    return receive


def mount_legacy_manual_identify_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_legacy_manual_identify_router(flask_app, **kwargs))
    return app
