"""Native compatibility handlers for the remaining scan form entry points."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class LegacyScanFormData:
    def resolve_path(self, app, folder_path, library_root):
        from oneirodex.utils.library_roots import resolve_scan_path

        return resolve_scan_path(folder_path, library_root, app)

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(app)

    def safe_path(self, path, allowed_bases):
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(path, allowed_bases)

    def readable_directory(self, path):
        import os

        return os.path.exists(path) and os.access(path, os.R_OK)

    def scan_patterns(self):
        from oneirodex.utils.functions import load_scanning_filter_patterns

        return load_scanning_filter_patterns()

    def list_games(self, path, insensitive, sensitive):
        from oneirodex.utils.gamenames import get_game_names_from_folder

        return get_game_names_from_folder(path, insensitive, sensitive)


def create_legacy_scan_form_router(
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
    data = data_access or LegacyScanFormData()

    @router.post('/scan_manual_folder')
    async def scan_manual_folder(request: Request):
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from oneirodex.utils.role_catalog import normalize_role

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            form = await request.form(max_files=0, max_fields=16, max_part_size=32 * 1024)
            try:
                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(
                        flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                    ),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                response = csrf_error_response(
                    request, session_data, flask_app.config,
                    token=str(form.get('csrf_token') or ''),
                )
                auth = None
                if response is None:
                    auth = request_auth_context(
                        request, flask_app.config, find_user=find_user,
                        find_token=find_token, commit_token_touch=commit_token_touch,
                        load_user_id=load_user_id, login_manager=login_manager,
                    )
                    if auth.user is None:
                        response = _login_redirect(flask_app, request, login_manager, auth)
                    elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                        response = _login_redirect(
                            flask_app, request, login_manager, auth,
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

                if response is None:
                    folder_path = str(form.get('folder_path') or '').strip()
                    library_root = str(form.get('library_root') or '').strip() or None
                    cancelled = bool(form.get('cancel'))
                    if cancelled:
                        pass
                    elif not str(form.get('library_uuid') or '').strip():
                        _flash(auth, 'error', 'Please select a library.')
                    else:
                        resolved, root_error = data.resolve_path(
                            flask_app, folder_path, library_root,
                        )
                        if root_error:
                            _flash(auth, 'error', f'Service configuration error: {root_error}')
                        else:
                            allowed_bases = data.allowed_bases(flask_app)
                            if not allowed_bases:
                                _flash(auth, 'error', 'Service configuration error: No allowed base directories configured.')
                            else:
                                safe, reason = data.safe_path(resolved, allowed_bases)
                                if not safe:
                                    _flash(auth, 'error', f'Access denied: {reason}')
                                elif data.readable_directory(resolved):
                                    insensitive, sensitive = data.scan_patterns()
                                    games = data.list_games(resolved, insensitive, sensitive)
                                    auth.session_data['active_tab'] = 'manualScan'
                                    auth.session_data['game_paths'] = {
                                        row['name']: row['full_path'] for row in games
                                    }
                                else:
                                    _flash(auth, 'error', 'Folder does not exist or cannot be accessed.')
                    response = RedirectResponse(
                        '/scan_manual_folder' if cancelled else
                        '/scan_management?active_tab=manual', status_code=302,
                    )

                if auth is not None and auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
                from oneirodex.utils.security_headers import security_header_values
                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                return response
            finally:
                await form.close()

    return router


def _flash(auth, category, message):
    values = list(auth.session_data.get('_flashes') or [])
    values.append((category, message))
    auth.session_data['_flashes'] = values


def mount_legacy_scan_form_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_legacy_scan_form_router(flask_app, **kwargs))
    return app
