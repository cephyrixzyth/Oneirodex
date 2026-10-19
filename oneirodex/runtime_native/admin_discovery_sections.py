"""FastAPI routes for admin discovery section reads and mutations."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminDiscoverySectionsData:
    """Database adapter for shelf CRUD, schedule, pin, and visibility actions."""

    def state(self):
        from oneirodex.utils.discovery_sections import (
            discovery_section_public, discovery_sections_data,
        )

        data = discovery_sections_data()
        return {
            'sections': [discovery_section_public(row, data) for row in data['sections']],
            'libraries': [{'uuid': row.uuid, 'name': row.name} for row in data['libraries']],
            'platforms': [{'id': row.name, 'label': row.value} for row in data['platforms']],
            'genres': [{'name': row.name} for row in data['genres']],
            'max_games': 60,
        }

    def create(self, body, actor_id):
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection
        from oneirodex.utils.discovery_shelves import (
            count_custom_shelf_games, describe_shelf_config, validate_shelf_config,
        )

        if len(body.name) > 50:
            return None, ('Shelf name must be 50 characters or fewer', 'bad_request', 400)
        config, error = validate_shelf_config(
            body.mode, game_uuids=body.game_uuids,
            filter_type=body.filter_type, filter_value=body.filter_value,
        )
        if error:
            return None, (error, 'bad_request', 400)
        max_order = db.session.execute(select(func.max(DiscoverySection.display_order))).scalar() or 0
        import uuid

        section = DiscoverySection(
            name=body.name, identifier=f'custom_{uuid.uuid4().hex[:12]}',
            is_visible=True, display_order=max_order + 1,
            section_type='custom', config=config,
        )
        db.session.add(section)
        db.session.commit()
        _audit(f"Created custom discovery shelf '{body.name}'", actor_id)
        return {
            'section': {
                'id': section.id, 'name': section.name,
                'identifier': section.identifier, 'is_visible': section.is_visible,
                'section_type': section.section_type,
                'description': describe_shelf_config(section.config),
                'count': count_custom_shelf_games(section.config),
            },
        }, None

    def update(self, section_id, body, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection
        from oneirodex.utils.discovery_shelves import (
            count_custom_shelf_games, describe_shelf_config, validate_shelf_config,
        )

        section = db.session.get(DiscoverySection, section_id)
        if section is None:
            return None, ('Shelf not found', 'not_found', 404)
        if section.section_type != 'custom':
            return None, ('Only custom shelves can be edited', 'bad_request', 400)
        if len(body.name) > 50:
            return None, ('Shelf name must be 50 characters or fewer', 'bad_request', 400)
        config, error = validate_shelf_config(
            body.mode, game_uuids=body.game_uuids,
            filter_type=body.filter_type, filter_value=body.filter_value,
        )
        if error:
            return None, (error, 'bad_request', 400)
        section.name, section.config = body.name, config
        db.session.commit()
        _audit(f"Updated custom discovery shelf '{body.name}'", actor_id)
        return {
            'section': {
                'id': section.id, 'name': section.name,
                'identifier': section.identifier, 'is_visible': section.is_visible,
                'section_type': section.section_type,
                'description': describe_shelf_config(section.config),
                'count': count_custom_shelf_games(section.config),
            },
        }, None

    def schedule(self, section_id, payload, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection
        from oneirodex.utils.discovery_sections import utc_naive

        section = db.session.get(DiscoverySection, section_id)
        if section is None:
            return None, ('Shelf not found', 'not_found', 404)
        if (not isinstance(payload, dict) or not payload
                or set(payload) - {'layout', 'starts_at', 'ends_at'}):
            return None, ('Provide only layout and schedule fields', 'bad_request', 400)
        layout = section.layout
        starts = utc_naive(section.starts_at) if section.starts_at else None
        ends = utc_naive(section.ends_at) if section.ends_at else None
        if 'layout' in payload:
            raw_layout = payload.get('layout')
            if not isinstance(raw_layout, str):
                return None, ('layout must be shelf, hero, or carousel', 'bad_request', 400)
            layout = (raw_layout or 'shelf').strip().lower()
            if layout not in ('shelf', 'hero', 'carousel'):
                return None, ('layout must be shelf, hero, or carousel', 'bad_request', 400)
        for key in ('starts_at', 'ends_at'):
            if key not in payload:
                continue
            raw = payload.get(key)
            if raw in (None, ''):
                value = None
            else:
                try:
                    if not isinstance(raw, str):
                        raise ValueError
                    value = utc_naive(datetime.fromisoformat(raw.replace('Z', '+00:00')))
                except (ValueError, TypeError):
                    return None, (f'{key} must be an ISO timestamp', 'bad_request', 400)
            if key == 'starts_at':
                starts = value
            else:
                ends = value
        if starts and ends and ends <= starts:
            return None, ('ends_at must be after starts_at', 'bad_request', 400)
        section.layout, section.starts_at, section.ends_at = layout, starts, ends
        db.session.commit()
        _audit(f'Updated shelf schedule {section_id}', actor_id)
        return {
            'section': {
                'id': section.id, 'name': section.name, 'identifier': section.identifier,
                'layout': section.layout,
                'starts_at': section.starts_at.isoformat() if section.starts_at else None,
                'ends_at': section.ends_at.isoformat() if section.ends_at else None,
                'is_live': section.is_live(),
            },
        }, None

    def pin(self, section_id, payload, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection

        section = db.session.get(DiscoverySection, section_id)
        if section is None:
            return None, ('Shelf not found', 'not_found', 404)
        if not isinstance(payload, dict) or set(payload) != {'pin_rank'}:
            return None, ('Provide a pin rank or null', 'bad_request', 400)
        value = payload.get('pin_rank')
        if value in (None, ''):
            section.pin_rank = None
        elif type(value) is not int or not -(2 ** 31) <= value < 2 ** 31:
            return None, ('pin_rank must be a whole number or null', 'bad_request', 400)
        else:
            section.pin_rank = value
        db.session.commit()
        if section.pin_rank is None:
            message = f"Released shelf '{section.name}' from the top block"
        else:
            message = f"Forced shelf '{section.name}' to the top block at rank {section.pin_rank}"
        _audit(message, actor_id)
        return {'section': {
            'id': section.id, 'identifier': section.identifier,
            'name': section.name, 'pin_rank': section.pin_rank,
        }}, None

    def delete(self, section_id, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection

        section = db.session.get(DiscoverySection, section_id)
        if section is None:
            return None, ('Shelf not found', 'not_found', 404)
        if section.section_type != 'custom':
            return None, ('Only custom shelves can be deleted', 'bad_request', 400)
        name = section.name
        db.session.delete(section)
        db.session.commit()
        _audit(f"Deleted custom discovery shelf '{name}'", actor_id)
        return {'message': f"Shelf '{name}' deleted"}, None

    def reorder(self, body, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection

        updated, staged, ids = [], [], set()
        for item in body.sections:
            if item.id in ids:
                return None, ('Section IDs must be unique', 'bad_request', 400)
            ids.add(item.id)
            if item.order < 0:
                return None, ('Display order must be non-negative', 'bad_request', 400)
            section = db.session.get(DiscoverySection, item.id)
            if section is None:
                return None, (f'Section with ID {item.id} not found', 'not_found', 404)
            staged.append((section, item.order))
            updated.append(section.name)
        for section, order in staged:
            section.display_order = order
        db.session.commit()
        _audit(
            f"Updated display order for {len(updated)} discovery sections: {', '.join(updated)}",
            actor_id,
        )
        return {
            'message': f'Updated order for {len(updated)} sections',
            'updated_sections': updated,
        }, None

    def visibility(self, body, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DiscoverySection

        section = db.session.get(DiscoverySection, body.section_id)
        if section is None:
            return None, (f'Section with ID {body.section_id} not found', 'not_found', 404)
        old_visibility = section.is_visible
        section.is_visible = body.is_visible
        db.session.commit()
        state = 'visible' if body.is_visible else 'hidden'
        _audit(f"Changed discovery section '{section.name}' visibility to {state}", actor_id)
        return {
            'message': f"Section '{section.name}' is now {state}",
            'section_name': section.name,
            'old_visibility': old_visibility,
            'new_visibility': body.is_visible,
        }, None

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()


def create_admin_discovery_sections_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminDiscoverySectionsData()

    @router.api_route('/admin/api/discovery_sections', methods=['GET', 'HEAD', 'POST'])
    @router.api_route('/admin/api/discovery_sections/{section_id:int}', methods=['PUT', 'DELETE'])
    @router.put('/admin/api/discovery_sections/{section_id:int}/schedule')
    @router.put('/admin/api/discovery_sections/{section_id:int}/pin')
    @router.post('/admin/api/discovery_sections/order')
    @router.post('/admin/api/discovery_sections/visibility')
    async def discovery_sections(request: Request, section_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if request.method not in ('GET', 'HEAD') and auth.token is None:
                from .csrf_compat import csrf_error_response

                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                csrf_response = None
            user = auth.user
            is_admin = (
                user is not None and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden')
            else:
                try:
                    response = await _dispatch_action(request, data, user, section_id)
                except Exception:  # noqa: BLE001 — don't expose database/SQL diagnostics
                    data.rollback()
                    # Keep an audit trail for failed privileged writes without
                    # persisting request bodies or database exception details.
                    _audit('Discovery sections admin API action failed', user.id)
                    response = _error('Internal server error', 'internal')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method in ('GET', 'HEAD'):
                response.headers.setdefault('Cache-Control', 'no-store')
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


async def _dispatch_action(request, data, user, section_id):
    from oneirodex.schemas.admin_system import (
        DiscoveryShelfBody, UpdateSectionOrderBody, UpdateSectionVisibilityBody,
    )

    method, path = request.method, request.url.path
    if path == '/admin/api/discovery_sections' and method in ('GET', 'HEAD'):
        return _ok(data.state())
    if path == '/admin/api/discovery_sections' and method == 'POST':
        body = await _model_body(request, DiscoveryShelfBody)
        if isinstance(body, Response):
            return body
        payload, error = data.create(body, user.id)
        return _result(payload, error, create=True)
    if section_id is not None and method == 'PUT' and path.endswith('/schedule'):
        payload, error = data.schedule(section_id, await _json_body(request), user.id)
        return _result(payload, error)
    if section_id is not None and method == 'PUT' and path.endswith('/pin'):
        payload, error = data.pin(section_id, await _json_body(request), user.id)
        return _result(payload, error)
    if section_id is not None and method == 'PUT':
        body = await _model_body(request, DiscoveryShelfBody)
        if isinstance(body, Response):
            return body
        payload, error = data.update(section_id, body, user.id)
        return _result(payload, error)
    if section_id is not None and method == 'DELETE':
        payload, error = data.delete(section_id, user.id)
        return _result(payload, error)
    if path == '/admin/api/discovery_sections/order' and method == 'POST':
        body = await _model_body(request, UpdateSectionOrderBody)
        if isinstance(body, Response):
            return body
        payload, error = data.reorder(body, user.id)
        return _result(payload, error)
    if path == '/admin/api/discovery_sections/visibility' and method == 'POST':
        body = await _model_body(request, UpdateSectionVisibilityBody)
        if isinstance(body, Response):
            return body
        payload, error = data.visibility(body, user.id)
        return _result(payload, error)
    return Response(status_code=405)


async def _model_body(request, model_type):
    from pydantic import ValidationError
    from oneirodex.utils.validation import format_validation_errors

    # Match the legacy @validate_body contract: missing, malformed, or JSON
    # null bodies validate as an empty object, while non-object JSON values
    # retain their root-level model error.
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload is None:
        payload = {}
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        return _error(
            'Invalid request.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )


async def _json_body(request):
    import json

    try:
        payload = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _result(payload, error, *, create=False):
    if error is not None:
        return _error(error[0], error[1], error[2])
    return _ok(payload, status=201 if create else 200)


def _ok(payload, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(message, code, status=None, **fields):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=status)


def _audit(message, actor_id):
    from oneirodex.utils.event_logging import log_system_event
    log_system_event(
        message, event_type='admin_action', event_level='information', audit_user=actor_id,
    )


def mount_admin_discovery_sections_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_discovery_sections_router(flask_app, **kwargs))
    return app
