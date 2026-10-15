"""Native member/admin reads for the licensed catalog cache."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class LicensedCatalogData:
    def report(self, platform: str, user) -> dict:
        from oneirodex.utils.licensed_catalog import licensed_catalog_report

        return licensed_catalog_report(platform, user)

    def status(self, platform: str) -> dict:
        from oneirodex.utils.licensed_catalog import cache_age_summary

        return cache_age_summary(platform)

    def refresh(self, platform: str) -> dict:
        from oneirodex.utils.licensed_catalog import refresh_platform_catalog

        return refresh_platform_catalog(platform)


def create_licensed_catalog_reads_router(
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
    data = data_access or LicensedCatalogData()

    def secure(response: Response, request: Request):
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

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

    @router.api_route('/api/licensed-catalog', methods=['GET', 'HEAD'])
    def licensed_catalog(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = authenticate(request)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                from oneirodex.utils.set_completion import REGION_LABELS, REGION_PREF_ORDER

                platform = (
                    request.query_params.get('library_platform')
                    or request.query_params.get('platform')
                    or ''
                ).strip()
                try:
                    if not platform:
                        payload = {
                            'regions': list(REGION_PREF_ORDER),
                            'region_labels': dict(REGION_LABELS),
                            'note': (
                                'Pass library_platform to read cached IGDB release_dates. '
                                'Empty cache is not zero games ever made.'
                            ),
                        }
                    else:
                        payload = data.report(platform, auth.user)
                except ValueError as exc:
                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                else:
                    response = JSONResponse(api_ok_payload(payload))
        return secure(response, request)

    @router.api_route('/api/licensed-catalog/status', methods=['GET', 'HEAD'])
    def licensed_catalog_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = authenticate(request)
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                body, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(body, status_code=status)
            else:
                platform = (
                    request.query_params.get('library_platform')
                    or request.query_params.get('platform')
                    or ''
                ).strip()
                if not platform:
                    body, status = api_error_payload(
                        'library_platform required', code='bad_request'
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    try:
                        result = data.status(platform)
                    except ValueError as exc:
                        body, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload(result))
        return secure(response, request)

    @router.post('/api/licensed-catalog/refresh')
    async def licensed_catalog_refresh(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from oneirodex.runtime_native.csrf_compat import csrf_error_response
            from oneirodex.runtime_native.request_auth import _lifetime_seconds
            from oneirodex.runtime_native.session_compat import load_session_cookie

            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name),
                flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(
                    flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                ),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if response is None:
                auth = authenticate(request)
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                from oneirodex.utils.role_catalog import normalize_role

                user = auth.user
                admin = (
                    user is not None
                    and bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                elif not admin:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    body, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    try:
                        content_type = request.headers.get('content-type', '').lower()
                        if 'application/json' in content_type:
                            raw = await request.json()
                        elif 'application/x-www-form-urlencoded' in content_type or 'multipart/form-data' in content_type:
                            raw = dict(await request.form())
                        else:
                            raw = {}
                    except Exception:  # noqa: BLE001 — Flask get_json(silent=True)
                        raw = {}
                    platform = str(
                        raw.get('library_platform')
                        or raw.get('platform')
                        or ''
                    ).strip() if isinstance(raw, dict) else ''
                    if not platform:
                        body, status = api_error_payload(
                            'library_platform required', code='bad_request'
                        )
                        response = JSONResponse(body, status_code=status)
                    else:
                        try:
                            from starlette.concurrency import run_in_threadpool

                            result = await run_in_threadpool(data.refresh, platform)
                        except ValueError as exc:
                            body, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(body, status_code=status)
                        except RuntimeError as exc:
                            import logging

                            logging.getLogger(__name__).warning(
                                'Licensed catalog refresh for %s failed: %s', platform, exc,
                            )
                            body, status = api_error_payload(
                                'IGDB did not return a licensed catalog page.',
                                code='bad_gateway',
                                detail='The upstream catalog request failed. Check the server log.',
                            )
                            response = JSONResponse(body, status_code=status)
                        else:
                            from oneirodex.utils.event_logging import log_system_event

                            await run_in_threadpool(
                                log_system_event,
                                f'Licensed catalog refresh: {result["library_platform"]} '
                                f'titles={result["unique_titles"]} pages={result["pages"]}',
                                event_type='admin', event_level='information',
                            )
                            response = JSONResponse(api_ok_payload(result))
                if auth.should_set_session_cookie:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)

        return secure(response, request)

    return router


def mount_licensed_catalog_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_licensed_catalog_reads_router(flask_app, **kwargs))
    return app
