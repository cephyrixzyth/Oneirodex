"""Native FastAPI notification inbox and preference APIs."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

_PREFERENCE_FIELDS = (
    'notify_friend_requests', 'notify_activity', 'notify_mentions',
    'notify_chat', 'notify_free_games', 'email_notify_social',
    'email_digest_daily', 'share_activity',
)


class NotificationData:
    """Adapter around the existing notification helpers and preference row."""

    def list(self, user_id: int, *, limit: int, unread_only: bool) -> dict:
        from oneirodex.utils.notifications import list_notifications, unread_count

        rows = list_notifications(user_id, limit=limit, unread_only=unread_only)
        return {
            'notifications': rows,
            'unread_count': unread_count(user_id),
            'empty': len(rows) == 0,
        }

    def mark_read(self, user_id: int, ids: list[int], *, all_read: bool) -> dict:
        from oneirodex.utils.notifications import mark_read, unread_count

        count = mark_read(user_id, ids, all_read=all_read)
        return {'marked': count, 'unread_count': unread_count(user_id)}

    def preferences(self, user):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserPreference

        prefs = user.preferences
        if prefs is None:
            prefs = UserPreference(user_id=user.id)
            db.session.add(prefs)
            db.session.commit()
        return prefs

    def update_preferences(self, user, payload: dict):
        from oneirodex.runtime_native.db_session import native_db as db

        prefs = self.preferences(user)
        for key in _PREFERENCE_FIELDS:
            if key in payload:
                setattr(prefs, key, bool(payload[key]))
        db.session.commit()

    def bus_status(self):
        from oneirodex.utils.notification_bus import status_summary

        return status_summary()

    def emit_test(self):
        from oneirodex.utils.notification_bus import emit

        return emit(
            kind='test', title='Oneirodex test notification',
            body='If you can read this, the notification bus reaches your device.',
        )

    def publish_test_event(self, user):
        from oneirodex.utils.event_bus import event_bus

        event = event_bus.publish('test', message='ping', user=user.name)
        return event.to_dict()


def create_notifications_router(
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
    data = data_access or NotificationData()

    @router.api_route('/api/notifications', methods=['GET', 'HEAD'])
    def list_notifications(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                scope_response = _require_scope(auth, 'read:social')
                if scope_response is not None:
                    response = scope_response
                else:
                    unread_values = request.query_params.getlist('unread')
                    limit_values = request.query_params.getlist('limit')
                    unread = (unread_values[0] if unread_values else '').lower() in ('1', 'true', 'yes')
                    try:
                        limit = int(limit_values[0]) if limit_values and limit_values[0] else 40
                    except (TypeError, ValueError):
                        limit = 40
                    limit = min(100, max(1, limit))
                    response = JSONResponse(data.list(
                        auth.user.id, limit=limit, unread_only=unread
                    ))
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/notifications/read')
    async def mark_notifications_read(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf_for_browser(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                scope_response = _require_scope(auth, 'write:social')
                if scope_response is not None:
                    response = scope_response
                else:
                    payload = _json_object(await request.body())
                    all_read = bool(payload.get('all'))
                    ids = payload.get('ids') if isinstance(payload.get('ids'), list) else []
                    cleaned = []
                    for value in ids:
                        try:
                            cleaned.append(int(value))
                        except (TypeError, ValueError, OverflowError):
                            continue
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.mark_read(
                        auth.user.id, cleaned, all_read=all_read
                    )))
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/notifications/preferences', methods=['GET', 'HEAD', 'POST'])
    async def notification_preferences(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if request.method == 'POST':
                response = _csrf_for_browser(request, auth, flask_app)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                scope_name = 'write:social' if request.method == 'POST' else 'read:social'
                scope_response = _require_scope(auth, scope_name)
                if scope_response is not None:
                    response = scope_response
                elif request.method == 'POST':
                    payload = _json_object(await request.body())
                    data.update_preferences(auth.user, payload)
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload())
                else:
                    prefs = data.preferences(auth.user)
                    response = JSONResponse({
                        key: bool(getattr(prefs, key, True if key != 'email_digest_daily' else False))
                        for key in _PREFERENCE_FIELDS
                    })
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/admin/notify-bus/test')
    async def notify_bus_test(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf_for_browser(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
                if not is_admin:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    response = _api_error('This token does not have the admin scope', 'forbidden')
                else:
                    status = data.bus_status()
                    if not status.get('configured'):
                        response = _api_error(
                            'No notification endpoint configured (NOTIFY_APPRISE_URLS / NOTIFY_NTFY_URL).',
                            'bad_request', **status,
                        )
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'sent': data.emit_test(), **status,
                        }))
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/events/publish_test')
    async def publish_test_event(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf_for_browser(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
                if not is_admin or (auth.token is not None and not auth.has_scope('admin')):
                    response = _api_error('Admin required', 'forbidden')
                else:
                    response = JSONResponse(data.publish_test_event(auth.user))
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_notifications_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_notifications_router(flask_app, **kwargs))
    return app


def _require_scope(auth, scope: str):
    if auth.has_scope(scope):
        return None
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(
        f'Missing scope: {scope}', code='forbidden',
        detail={'required_scope': scope},
    )
    return JSONResponse(payload, status_code=status)


def _api_error(message: str, code: str, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, **fields)
    return JSONResponse(payload, status_code=status)


def _csrf_for_browser(request, auth, flask_app):
    # Bearer credentials do not ride ambient browser cookies. The legacy
    # scope-guarded notification APIs therefore rely on write:social for token
    # writes while browser sessions continue to require Flask-WTF CSRF.
    if auth.token is not None:
        return None
    return csrf_error_response(request, auth.session_data, flask_app.config)


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _json_object(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
