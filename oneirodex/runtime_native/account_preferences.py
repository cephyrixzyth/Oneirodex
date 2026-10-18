"""Native FastAPI routes for the member preferences API."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import nullcontext
import logging
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .csrf_compat import (
    csrf_error_response as _csrf_error_response,
    csrf_html_error_response as _csrf_html_error_response,
)
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class AccountPreferencesData:
    """Adapter for the established preferences projection and persistence."""

    def __init__(self, app=None):
        self.app = app

    def choices(self, user) -> dict:
        from oneirodex.forms_native import UserPreferencesForm, stored_preference_formdata
        from oneirodex.utils.browser_player import play_engine_fields
        from oneirodex.utils.icon_themes import list_icon_packs
        from oneirodex.utils.preset_themes import theme_picker_groups

        form = UserPreferencesForm(formdata=None, app=self.app)
        return {
            'preferences': stored_preference_formdata(user.preferences),
            'choices': {
                'items_per_page': [
                    {'value': value, 'label': label}
                    for value, label in form.items_per_page.choices
                ],
                'default_sort': [
                    {'value': value, 'label': label}
                    for value, label in form.default_sort.choices
                ],
                'default_sort_order': [
                    {'value': value, 'label': label}
                    for value, label in form.default_sort_order.choices
                ],
                'themes': theme_picker_groups(form.theme.choices),
                'icon_packs': list_icon_packs(),
                'fonts': [
                    {'value': value, 'label': label}
                    for value, label in form.font.choices
                ],
                'browser_player_engines': [
                    {'value': value, 'label': label}
                    for value, label in form.browser_player_engine.choices
                ],
                'game_locales': [
                    {'value': value, 'label': label}
                    for value, label in form.preferred_game_locale.choices
                ],
            },
            'member_engine_choice': play_engine_fields()['browser_player_member_choice'],
            'is_admin': user.role == 'admin',
        }

    def update(self, user, payload: Mapping[str, Any]) -> tuple[dict, int]:
        from werkzeug.datastructures import MultiDict

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.forms_native import (
            UserPreferencesForm, normalize_tile_percent, stored_preference_formdata,
        )
        from oneirodex.models import UserPreference

        prefs = user.preferences
        values = stored_preference_formdata(prefs)
        for key in values:
            if key in payload:
                raw = payload[key]
                values[key] = 'true' if raw is True else 'false' if raw is False else str(raw)
        form = UserPreferencesForm(formdata=MultiDict(values), app=self.app)
        if not form.validate():
            return {'error': 'Preferences validation failed', 'errors': form.errors}, 400

        if prefs is None:
            prefs = UserPreference(user_id=user.id)
            user.preferences = prefs
        prefs.items_per_page = form.items_per_page.data
        prefs.default_sort = form.default_sort.data
        prefs.default_sort_order = form.default_sort_order.data
        prefs.theme = form.theme.data or 'default'
        prefs.icon_pack = form.icon_pack.data or 'outline'
        prefs.font = form.font.data or 'system-ui'
        prefs.tile_size = normalize_tile_percent(form.tile_size.data)
        prefs.show_tile_titles = bool(form.show_tile_titles.data)
        prefs.browser_player_engine = form.browser_player_engine.data or None
        prefs.preferred_game_locale = form.preferred_game_locale.data or 'en-US'
        try:
            db.session.add(prefs)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logging.getLogger(__name__).exception('Failed to save member preferences')
            return {'error': 'Preferences could not be saved'}, 500
        return {'preferences': stored_preference_formdata(prefs)}, 200


def create_account_preferences_router(
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
    data = data_access or AccountPreferencesData(flask_app)

    @router.api_route('/api/account/preferences', methods=['GET', 'HEAD', 'PUT'])
    async def account_preferences(request: Request):
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
            if request.method == 'PUT':
                if auth.token is not None and not auth.has_scope('write:library'):
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Missing scope: write:library', code='forbidden',
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    csrf_response = (
                        _csrf_error_response(request, auth.session_data, flask_app.config)
                        if auth.token is None else None
                    )
                    response = csrf_response
                if response is None and auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                elif response is None:
                    from pydantic import ValidationError

                    from oneirodex.schemas.preferences import MemberPreferencesBody
                    from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                    from oneirodex.utils.validation import format_validation_errors

                    try:
                        body = MemberPreferencesBody.model_validate(
                            _json_object(await request.body())
                        )
                    except ValidationError as exc:
                        response_payload, status = api_error_payload(
                            'Invalid request.',
                            code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                    else:
                        payload, status = data.update(
                            auth.user, body.model_dump(exclude_unset=True)
                        )
                        if 'error' in payload:
                            response_payload, status = api_error_payload(
                                payload['error'],
                                code='bad_request' if status == 400 else 'internal',
                                **({'errors': payload['errors']} if 'errors' in payload else {}),
                            )
                        else:
                            response_payload = api_ok_payload(payload)
                    response = JSONResponse(response_payload, status_code=status)
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.choices(auth.user)))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/settings_panel')
    async def legacy_preferences_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            form, body_error = await _legacy_form(request)
            response = body_error
            if response is None:
                response = _csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')),
                )
                if response is not None:
                    response = _csrf_html_error_response(response)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                payload = dict(form)
                full_form = bool(payload.pop('_full_form', None))
                payload.pop(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'), None)
                if full_form and 'show_tile_titles' not in payload:
                    payload['show_tile_titles'] = False
                result, status = data.update(auth.user, payload)
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

                if 'error' in result:
                    code = 'bad_request' if status == 400 else 'internal'
                    response_payload, status = api_error_payload(
                        'Form validation failed' if status == 400 else 'Could not update preferences',
                        code=code,
                        **({'errors': result.get('errors', {})} if status == 400 else {}),
                    )
                else:
                    preferences = result.get('preferences', {})
                    response_payload = api_ok_payload({
                        'message': 'Preferences updated successfully!',
                        'icon_pack': preferences.get('icon_pack') or 'outline',
                        'font': preferences.get('font') or 'system-ui',
                        'theme': preferences.get('theme') or 'default',
                    })
                response = JSONResponse(response_payload, status_code=status)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            return response

    return router


def mount_account_preferences_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_preferences_router(flask_app, **kwargs))
    return app


def _json_object(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


async def _legacy_form(request: Request):
    from urllib.parse import parse_qs

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024:
            return {}, Response(status_code=413)
    try:
        fields = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}, Response(status_code=400)
    return {name: values[-1] for name, values in fields.items() if values}, None
