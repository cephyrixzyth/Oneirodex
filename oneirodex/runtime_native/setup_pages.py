"""Native static-shell routing for the six-step first-run setup wizard."""
from __future__ import annotations

from contextlib import nullcontext
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse

from .request_auth import request_auth_context


class SetupPagesData:
    def required(self):
        from oneirodex.utils.setup import is_setup_required

        return is_setup_required()

    def in_progress(self):
        from oneirodex.utils.setup import is_setup_in_progress

        return is_setup_in_progress()

    def current_step(self):
        from oneirodex.utils.setup import get_current_setup_step

        return get_current_setup_step()

    def start(self):
        from oneirodex.utils.setup import set_setup_step

        set_setup_step(1)

    def redirect_url(self):
        from oneirodex.utils.setup import get_setup_redirect_url

        return get_setup_redirect_url()


def create_setup_pages_router(
    flask_app: FastAPI,
    *,
    find_user,
    find_token,
    commit_token_touch,
    load_user_id=None,
    login_manager=None,
    data_access=None,
    database_scope=None,
):
    router = APIRouter()
    data = data_access or SetupPagesData()
    expected_steps = {
        '/setup/smtp': 2,
        '/setup/features': 3,
        '/setup/igdb': 4,
        '/setup/integrations': 5,
        '/setup/library': 6,
    }
    wrong_step_messages = {
        '/setup/smtp': 'Please complete the admin account setup first.',
        '/setup/features': 'Please complete the previous setup steps first.',
        '/setup/igdb': 'Please complete the previous setup steps first.',
        '/setup/integrations': 'Please complete the previous setup steps first.',
    }

    @router.api_route('/setup', methods=['GET', 'HEAD'])
    def setup_home(request: Request):
        return _serve(request, '/setup')

    for page in expected_steps:
        async def handler(request: Request, _page=page):
            return _serve(request, _page)

        router.add_api_route(page, handler, methods=['GET', 'HEAD'])

    def _serve(request, page):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
                allow_bearer=False,
            )
            had_flashes = bool(auth.session_data.get('_flashes'))
            if page == '/setup':
                required = data.required()
                if not required and data.in_progress():
                    response = RedirectResponse(data.redirect_url(), status_code=302)
                elif not required:
                    _flash(auth.session_data, 'warning', 'Setup has already been completed.')
                    response = RedirectResponse('/login', status_code=302)
                else:
                    data.start()
                    response = _shell(request, flask_app, auth)
            else:
                step = data.current_step()
                if step is None:
                    if page != '/setup/library':
                        _flash(auth.session_data, 'warning', 'Setup already completed.')
                        response = RedirectResponse('/login', status_code=302)
                    else:
                        response = RedirectResponse('/setup', status_code=302)
                elif step != expected_steps[page]:
                    message = wrong_step_messages.get(page)
                    if message:
                        _flash(auth.session_data, 'warning', message)
                    response = RedirectResponse('/setup', status_code=302)
                elif auth.user is None or _role(auth.user) != 'admin':
                    _flash(
                        auth.session_data, 'warning',
                        'Sign in with the admin account you just created to finish setup.',
                    )
                    response = RedirectResponse(
                        '/login?' + urlencode({'next': request.url.path}), status_code=302,
                    )
                else:
                    response = _shell(request, flask_app, auth)

            _finish_response(
                response, flask_app, auth,
                session_changed=had_flashes or bool(auth.session_data.get('_flashes')),
            )
            return response

    return router


def _role(user):
    from oneirodex.utils.role_catalog import normalize_role

    return normalize_role(getattr(user, 'role', None) or '')


def _flash(session, category, message):
    flashes = list(session.get('_flashes') or [])
    flashes.append((category, message))
    session['_flashes'] = flashes


def _shell(request, flask_app, auth):
    from oneirodex.runtime_native.auth_pages import _shell_response

    return _shell_response(flask_app, auth.session_data)


def _finish_response(response, flask_app, auth, *, session_changed=False):
    if auth.remember_action:
        from oneirodex.runtime_native.auth_login import _write_remember_cookie

        _write_remember_cookie(response, auth.session_data, flask_app.config)
    if auth.should_set_session_cookie or session_changed:
        from oneirodex.runtime_native.oidc_status import _set_session_cookie

        _set_session_cookie(response, flask_app, auth)
    from oneirodex.runtime_native.auth_pages import _security_headers

    _security_headers(response, flask_app.config)


def mount_setup_pages_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_setup_pages_router(flask_app, **kwargs))
    return app
