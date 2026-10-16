"""Native FastAPI reads for administrator Operations panels."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


class AdminOpsReadData:
    def logs(self, limit):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SystemEvents

        rows = db.session.execute(
            select(SystemEvents).options(db.joinedload(SystemEvents.user))
            .order_by(SystemEvents.timestamp.desc()).limit(limit),
        ).scalars().all()
        return {'events': [
            {
                'id': row.id,
                'timestamp': row.timestamp.isoformat() if row.timestamp else None,
                'level': row.event_level,
                'type': row.event_type,
                'text': row.event_text,
                'user': row.user.name if row.user else None,
            }
            for row in rows
        ]}

    def summary(self, flask_app):
        from oneirodex import app_start_time
        from oneirodex.utils.ops_summary import build_ops_summary

        return build_ops_summary(
            app_start_time, app=flask_app, config=flask_app.config,
        )

    def system(self, flask_app):
        from oneirodex import app_start_time
        from oneirodex.runtime_native.db_session import current_native_engine
        from oneirodex.utils.status import (
            get_active_users, get_config_values, get_database_info, get_system_info,
        )
        from oneirodex.utils.uptime import get_formatted_app_uptime, get_formatted_system_uptime
        from oneirodex.utils.ops_projections import log_summary, theme_asset_panel
        from oneirodex.utils.status import get_log_info

        system_info = get_system_info()
        system_info['System Uptime'] = get_formatted_system_uptime()
        system_info['Application Uptime'] = get_formatted_app_uptime(app_start_time)
        return {
            'system': system_info,
            'database': get_database_info(engine=current_native_engine()),
            'active_users': get_active_users(),
            'logs': log_summary(get_log_info()),
            'config': get_config_values(config=flask_app.config),
            'theme_assets': theme_asset_panel(flask_app.root_path),
        }

    def devices(self, limit, flask_app):
        from oneirodex.utils.ops_summary import list_client_devices

        return list_client_devices(limit=limit)

    def library_health(self, flask_app):
        from oneirodex.utils.library_health import build_library_health_pulse

        return build_library_health_pulse()

    def image_refresh_progress(self, game_uuid):
        # Preserve the legacy progress payload verbatim. In particular, a
        # cached ``status: error`` describes the refresh job, not the API call.
        from oneirodex import cache

        return cache.get(f'image_refresh_progress_{game_uuid}')

    def library_delete_progress(self, job_id):
        from oneirodex.utils.library_deletion import deletion_progress

        return deletion_progress.get(job_id)

    def library_deletion_progress(self):
        from oneirodex.utils.library_deletion import deletion_progress

        return deletion_progress

    def clear_logs(self, actor):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SystemEvents
        from oneirodex.utils.event_logging import log_system_event

        count = db.session.execute(select(func.count(SystemEvents.id))).scalar() or 0
        db.session.execute(db.delete(SystemEvents))
        db.session.commit()
        log_system_event(
            f"System logs cleared by admin user '{actor.name}' (ID: {actor.id}). {count} logs were deleted.",
            event_type='admin_action', event_level='warning', audit_user=actor.id,
        )
        return {'message': f'Successfully cleared {count} system logs', 'deleted_count': count}

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()


def create_admin_ops_reads_router(
    flask_app, *, find_user, find_token, commit_token_touch,
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
):
    from .acquire_status import _login_redirect

    router = APIRouter()
    data = data_access or AdminOpsReadData()
    paths = {
        '/admin/api/ops/logs': 'logs',
        '/admin/api/ops/system': 'system',
        '/admin/api/ops/summary': 'summary',
        '/admin/api/ops/devices': 'devices',
        '/admin/api/library/health': 'library_health',
        '/check_image_refresh_progress': 'image_refresh_progress',
        '/check_deletion_progress': 'library_delete_progress',
        '/delete_library_progress': 'library_deletion_sse',
        '/admin/api/system_logs/clear': 'clear_logs',
        '/admin/clear_permission_errors': 'clear_permission_errors',
    }

    @router.api_route('/admin/api/ops/logs', methods=['GET', 'HEAD'])
    @router.api_route('/admin/api/ops/system', methods=['GET', 'HEAD'])
    @router.api_route('/admin/api/ops/summary', methods=['GET', 'HEAD'])
    @router.api_route('/admin/api/ops/devices', methods=['GET', 'HEAD'])
    @router.api_route('/admin/api/library/health', methods=['GET', 'HEAD'])
    @router.api_route('/check_image_refresh_progress/{game_uuid}', methods=['GET', 'HEAD'])
    @router.api_route('/check_deletion_progress/{job_id}', methods=['GET', 'HEAD'])
    @router.api_route('/delete_library_progress/{job_id}', methods=['GET', 'HEAD'])
    @router.delete('/admin/api/system_logs/clear')
    @router.post('/admin/clear_permission_errors')
    def admin_ops_read(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if request.method in ('DELETE', 'POST') and auth.token is None:
                from .csrf_compat import csrf_error_response

                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                csrf_response = None
            if csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.role_catalog import normalize_role

                if normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    response = _error('This token does not have the admin scope', 'forbidden', 403)
                else:
                    handler = (
                        'image_refresh_progress'
                        if request.url.path.startswith('/check_image_refresh_progress/')
                            else (
                                'library_delete_progress'
                                if request.url.path.startswith('/check_deletion_progress/')
                                else (
                                    'library_deletion_sse'
                                    if request.url.path.startswith('/delete_library_progress/')
                                    else paths[request.url.path]
                                )
                            )
                    )
                    try:
                        if handler == 'logs':
                            limit = _bounded_limit(request.query_params.get('limit'), 50, 200)
                            payload = data.logs(limit)
                        elif handler == 'devices':
                            limit = _bounded_limit(request.query_params.get('limit'), 200, 1000)
                            payload = data.devices(limit, flask_app)
                        elif handler == 'summary':
                            payload = data.summary(flask_app)
                        elif handler == 'image_refresh_progress':
                            payload = data.image_refresh_progress(
                                request.path_params['game_uuid'],
                            )
                            if payload is None:
                                from oneirodex.utils.api_contract import api_ok_payload

                                payload = api_ok_payload({'status': 'not_found', 'progress': 0})
                        elif handler == 'library_delete_progress':
                            payload = data.library_delete_progress(request.path_params['job_id'])
                            if payload is None:
                                from oneirodex.utils.api_contract import api_error_payload

                                body, status = api_error_payload(
                                    'Job not found', code='not_found', body_status='not_found',
                                )
                                response = JSONResponse(body, status_code=status)
                                payload = None
                        elif handler == 'library_deletion_sse':
                            import asyncio
                            import json

                            from starlette.responses import StreamingResponse

                            job_id = request.path_params['job_id']
                            progress = data.library_deletion_progress()

                            async def event_stream():
                                yield 'data: {"status": "connected", "message": "Progress tracking connected"}\n\n'
                                wait_count = 0
                                while job_id not in progress and wait_count < 20:
                                    await asyncio.sleep(0.5)
                                    wait_count += 1
                                if job_id not in progress:
                                    yield 'data: {"status": "error", "message": "Progress data not found"}\n\n'
                                    return
                                while job_id in progress:
                                    progress_data = dict(progress[job_id])
                                    yield f'data: {json.dumps(progress_data)}\n\n'
                                    if progress_data.get('status') in {'completed', 'error'}:
                                        await asyncio.sleep(1)
                                        if job_id in progress:
                                            del progress[job_id]
                                        break
                                    await asyncio.sleep(0.3)

                            response = StreamingResponse(
                                event_stream(), media_type='text/event-stream',
                            )
                            response.headers['Cache-Control'] = 'no-cache'
                            response.headers['Connection'] = 'keep-alive'
                            response.headers['X-Accel-Buffering'] = 'no'
                            payload = None
                        elif handler == 'system':
                            payload = data.system(flask_app)
                        elif handler == 'clear_logs':
                            from oneirodex.utils.api_contract import api_ok_payload

                            payload = api_ok_payload(data.clear_logs(auth.user))
                        elif handler == 'clear_permission_errors':
                            from oneirodex.utils.api_contract import api_ok_payload

                            for key in (
                                'permission_check_failed', 'permission_errors',
                                'permission_check_path',
                            ):
                                auth.session_data.pop(key, None)
                            response = JSONResponse(api_ok_payload())
                            payload = None
                        else:
                            payload = data.library_health(flask_app)
                        if payload is not None:
                            response = JSONResponse(payload)
                    except Exception:  # noqa: BLE001 — ops panels must fail safely
                        if handler == 'clear_logs':
                            data.rollback()
                        from oneirodex.utils.api_contract import api_error_payload

                        message = {
                            'logs': 'Recent events are unavailable',
                            'system': 'System snapshot is unavailable',
                            'devices': 'Device list is unavailable',
                            'summary': 'Ops summary is unavailable',
                            'library_health': 'Library health is unavailable',
                            'image_refresh_progress': 'Image refresh progress is unavailable',
                            'library_delete_progress': 'Library deletion progress is unavailable',
                            'library_deletion_sse': 'Library deletion progress is unavailable',
                            'clear_logs': 'System logs could not be cleared',
                        }[handler]
                        body, status = api_error_payload(message, code='unavailable')
                        response = JSONResponse(body, status_code=status)
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


def mount_admin_ops_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_ops_reads_router(flask_app, **kwargs))
    return app


def _bounded_limit(value, default, maximum):
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _error(message, code, status):
    from oneirodex.utils.api_contract import api_error_payload

    body, resolved = api_error_payload(message, code=code, status=status)
    return JSONResponse(body, status_code=resolved)
