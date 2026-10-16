"""FastAPI admin read for scan queue/job status."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


class ScanJobReadData:
    def path_info(self, raw):
        import os

        try:
            exists = os.path.exists(raw)
        except OSError:
            exists = False
        return {
            'path': raw,
            'exists': exists,
            'is_dir': os.path.isdir(raw) if exists else False,
            'basename': os.path.basename(raw.rstrip('\\/')) if raw else None,
            'open_via': 'desktop',
            'note': 'Server returns path string only; Desktop companion opens host explorer.',
        }

    def drain_if_idle(self, app, *, database_scope=None):
        from oneirodex.utils.scan_queue import maybe_drain_scan_queue

        maybe_drain_scan_queue(app, database_scope=database_scope)

    def list_jobs(self, filters):
        from sqlalchemy import or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library, ScanJob

        query = (
            select(ScanJob)
            .outerjoin(Library, ScanJob.library_uuid == Library.uuid)
            .order_by(ScanJob.last_run.desc().nullslast())
        )
        if filters['statuses']:
            query = query.where(ScanJob.status.in_(filters['statuses']))
        if filters['library_uuid']:
            query = query.where(ScanJob.library_uuid == filters['library_uuid'])
        if filters['q']:
            pattern = f"%{filters['q']}%"
            query = query.where(or_(
                ScanJob.scan_folder.ilike(pattern), Library.name.ilike(pattern),
            ))
        return db.session.execute(query).scalars().unique().all()

    def queue_position(self, job_id):
        from oneirodex.utils.scan_queue import queue_position

        return queue_position(job_id)


def create_scan_job_reads_router(
    flask_app, *, find_user, find_token, commit_token_touch, load_user_id,
    login_manager, database_scope=None, data_access=None,
):
    from .acquire_status import _login_redirect

    router = APIRouter()
    data = data_access or ScanJobReadData()

    @router.api_route('/api/scan_jobs_status', methods=['GET', 'HEAD'])
    async def scan_jobs_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('Admin required', code='forbidden')
                    response = JSONResponse(body, status_code=status)
            if response is None:
                try:
                    try:
                        data.drain_if_idle(flask_app, database_scope=database_scope)
                    except Exception:  # best-effort safety drain, matching legacy poll
                        pass
                    from oneirodex.utils.scan_job_timing import (
                        compute_scan_job_timing, parse_scan_job_status_filter,
                    )

                    query = request.query_params
                    filters = {
                        'statuses': parse_scan_job_status_filter(query.get('status')),
                        'library_uuid': (query.get('library_uuid') or '').strip(),
                        'q': (query.get('q') or query.get('name') or '').strip(),
                    }
                    rows = []
                    for job in data.list_jobs(filters):
                        timing = compute_scan_job_timing(job)
                        processed = timing['folders_processed']
                        total = job.total_folders or 0
                        row = {
                            'id': job.id,
                            'library_name': job.library.name if job.library else 'No Library Assigned',
                            'library_uuid': job.library_uuid,
                            'folders': job.folders,
                            'status': job.status,
                            'total_folders': total,
                            'folders_success': job.folders_success or 0,
                            'folders_failed': job.folders_failed or 0,
                            'folders_processed': processed,
                            'removed_count': job.removed_count or 0,
                            'scan_folder': job.scan_folder,
                            'setting_remove': bool(job.setting_remove),
                            'setting_filefolder': bool(job.setting_filefolder),
                            'setting_download_missing_images': bool(job.setting_download_missing_images),
                            'current_processing': job.current_processing,
                            'error_message': job.error_message or '',
                            'last_run': job.last_run.strftime('%Y-%m-%d %H:%M:%S') if job.last_run else 'Not Available',
                            'last_update': job.last_progress_update.isoformat() if job.last_progress_update else None,
                            'next_run': job.next_run.strftime('%Y-%m-%d %H:%M:%S') if job.next_run else 'Not Scheduled',
                            'progress_percentage': round(processed / total * 100, 1) if total > 0 else 0,
                            **timing,
                        }
                        if job.status == 'Queued':
                            row['queue_position'] = data.queue_position(job.id)
                        rows.append(row)
                    response = JSONResponse(rows)
                except Exception:  # noqa: BLE001 — status polling must not leak ORM errors
                    import logging

                    logging.getLogger(__name__).exception('Scan job status read failed')
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('Scan status is unavailable', code='internal')
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

    @router.api_route('/api/path/open', methods=['GET', 'HEAD'])
    async def open_path_info(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('Admin required', code='forbidden')
                    response = JSONResponse(body, status_code=status)
            if response is None:
                raw = (request.query_params.get('path')
                       or request.query_params.get('full_disk_path') or '').strip()
                if not raw:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('path required', code='bad_request')
                    response = JSONResponse(body, status_code=status)
                elif len(raw) > 2048:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('path too long', code='bad_request')
                    response = JSONResponse(body, status_code=status)
                else:
                    response = JSONResponse(data.path_info(raw))
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


def mount_scan_job_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_scan_job_reads_router(flask_app, **kwargs))
    return app
