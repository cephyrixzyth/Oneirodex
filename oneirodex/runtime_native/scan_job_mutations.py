"""Native FastAPI compatibility actions for legacy admin scan-job forms."""
from __future__ import annotations

from .form_compat import first_form_value
from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response

from .request_auth import request_auth_context
from .query_compat import first_query_value
from .response_compat import flask_redirect_response


class ScanJobMutationData:
    def cancel(self, job_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ScanJob

        job = db.session.get(ScanJob, job_id)
        if job and job.status == 'Running':
            job.is_enabled = False
            job.status = 'Stopping'
            job.error_message = 'Scan is stopping, waiting for threads to complete'
            db.session.commit()
            return ('Scan job is stopping. Waiting for threads to complete...', 'message')
        if job and job.status == 'Queued':
            job.is_enabled = False
            job.status = 'Cancelled'
            job.error_message = 'Queued scan cancelled before start'
            db.session.commit()
            return (f'Queued scan job {job_id} cancelled.', 'message')
        return ('Scan job not found or not in a cancellable state.', 'error')

    def delete(self, job_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ScanJob

        job = db.session.get(ScanJob, job_id)
        if job is None:
            return False
        db.session.delete(job)
        db.session.commit()
        return True

    def clear(self, status=None):
        from sqlalchemy import delete

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ScanJob

        if status is None:
            result = db.session.execute(
                delete(ScanJob).where(
                    ScanJob.status.in_(('Completed', 'Failed', 'Cancelled')),
                ),
            )
            message = (
                'completed/failed/cancelled scan jobs '
                '(Running/Stopping/Queued/Scheduled kept)'
            )
        else:
            result = db.session.execute(
                delete(ScanJob).where(ScanJob.status == status),
            )
            message = f'{status} scan jobs'
        db.session.commit()
        return int(result.rowcount or 0), message

    def restart(self, job_id, *, queue_policy, app, database_scope):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ScanJob
        from oneirodex.utils.scan_queue import restart_or_queue_scan

        if db.session.get(ScanJob, job_id) is None:
            return None
        return restart_or_queue_scan(
            job_id, queue_policy=queue_policy, allow_force=True,
            app=app, database_scope=database_scope,
        )


def create_scan_job_mutation_router(
    app, *, find_user, find_token, commit_token_touch,
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
):
    # Admin-role denials pass the legacy flash message/category options.
    # Use the shared login redirect adapter that supports those options;
    # the acquire-status variant only handles anonymous redirects.
    from .oidc_status import _login_redirect

    router = APIRouter()
    data = data_access or ScanJobMutationData()

    @router.post('/cancel_scan_job/{job_id}')
    async def cancel_scan_job(request: Request, job_id: str):
        return await _handle(
            request, app=app, data=data, action='cancel', job_id=job_id,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            _login_redirect=_login_redirect,
        )

    @router.post('/delete_scan_job/{job_id}')
    async def delete_scan_job(request: Request, job_id: str):
        return await _handle(
            request, app=app, data=data, action='delete', job_id=job_id,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            _login_redirect=_login_redirect,
        )

    @router.post('/restart_scan_job/{job_id}')
    async def restart_scan_job(request: Request, job_id: str):
        return await _handle(
            request, app=app, data=data, action='restart', job_id=job_id,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            _login_redirect=_login_redirect,
        )

    @router.post('/clear_all_scan_jobs')
    async def clear_all_scan_jobs(request: Request):
        return await _handle(
            request, app=app, data=data, action='clear_all',
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            _login_redirect=_login_redirect,
        )

    @router.post('/clear_scan_jobs')
    async def clear_scan_jobs(request: Request):
        return await _handle(
            request, app=app, data=data, action='clear',
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            _login_redirect=_login_redirect,
        )

    return router


async def _handle(
    request, *, app, data, action, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, _login_redirect,
    job_id=None,
):
    from .csrf_compat import csrf_error_response

    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        if auth.token is None:
            try:
                form = await request.form(max_files=0, max_fields=10, max_part_size=16 * 1024)
                csrf_token = first_form_value(form, str(app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'))
            except Exception:
                csrf_token = None
            csrf = csrf_error_response(request, auth.session_data, app.config, token=csrf_token)
        else:
            csrf = None
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(app, request, login_manager, auth)
        else:
            from oneirodex.utils.role_catalog import normalize_role

            if normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                response = _login_redirect(
                    app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                from starlette.responses import JSONResponse
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                response = JSONResponse(body, status_code=status)
            else:
                from starlette.exceptions import HTTPException

                try:
                    if action == 'cancel':
                        message, category = data.cancel(job_id)
                        auth.session_data.setdefault('_flashes', []).append((category, message))
                    elif action == 'delete':
                        if not data.delete(job_id):
                            raise HTTPException(status_code=404, detail='Not Found')
                        auth.session_data.setdefault('_flashes', []).append(
                            ('success', 'Scan job deleted successfully.'),
                        )
                    elif action == 'restart':
                        form = await request.form(
                            max_files=0, max_fields=10, max_part_size=16 * 1024,
                        )
                        from oneirodex.utils.scan_queue import parse_queue_policy

                        queue_policy = parse_queue_policy(
                            first_form_value(form, 'queue_policy'), first_form_value(form, 'force_parallel'),
                        )
                        result = data.restart(
                            job_id,
                            queue_policy=queue_policy,
                            app=app,
                            database_scope=database_scope,
                        )
                        if result is None:
                            raise HTTPException(status_code=404, detail='Not Found')
                        auth.session_data.setdefault('_flashes', []).append((
                            'error' if result.get('status') == 'rejected' else 'success',
                            result['message'],
                        ))
                    else:
                        status = None
                        if action == 'clear':
                            try:
                                form = await request.form(
                                    max_files=0, max_fields=10, max_part_size=16 * 1024,
                                )
                                status = str(first_form_value(form, 'status') or first_query_value(request.query_params, 'status') or '').strip()
                            except Exception:
                                status = str(first_query_value(request.query_params, 'status') or '').strip()
                            if status not in {'Completed', 'Failed', 'Cancelled'}:
                                auth.session_data.setdefault('_flashes', []).append(
                                    ('error', 'Unknown job status to clear.'),
                                )
                                return _finish(
                                    flask_redirect_response('/scan_management?active_tab=jobs', status_code=302),
                                    app, auth, request,
                                )
                        count, label = data.clear(status)
                        message = f'Cleared {count} {label}.'
                        auth.session_data.setdefault('_flashes', []).append(('success', message))
                    # Keep legacy form actions in the scan-jobs context. The
                    # native scan page defaults to Auto when the tab is absent.
                    target = '/scan_management?active_tab=jobs'
                    response = flask_redirect_response(target, status_code=302)
                except HTTPException:
                    raise
                except Exception:
                    if action in {'delete', 'clear', 'clear_all'}:
                        from oneirodex.runtime_native.db_session import native_db as db

                        db.session.rollback()
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    body, status = api_error_payload(
                        'Scan job action is unavailable', code='unavailable',
                    )
                    response = JSONResponse(body, status_code=status)
        return _finish(response, app, auth, request)


def _finish(response, app, auth, request):
    if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
        from .oidc_status import _set_session_cookie

        _set_session_cookie(response, app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        return Response(content=b'', status_code=response.status_code, headers=dict(response.headers))
    return response


def mount_scan_job_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_scan_job_mutation_router(flask_app, **kwargs))
    return app
