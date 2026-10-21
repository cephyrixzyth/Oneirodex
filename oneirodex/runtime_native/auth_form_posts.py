"""FastAPI form endpoints for the React member-auth shell."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, PlainTextResponse

from .form_compat import first_form_value
from .request_auth import request_auth_context
from .query_compat import first_query_value
from .response_compat import flask_redirect_response


def create_auth_form_post_router(
    flask_app: FastAPI,
    *,
    find_user,
    find_token,
    commit_token_touch,
    load_user_id=None,
    login_manager=None,
    database_scope=None,
    login_data=None,
    registration_data=None,
    password_reset_data=None,
):
    router = APIRouter()
    if login_data is None:
        from .auth_login import AuthLoginData

        login_data = AuthLoginData()
    if registration_data is None:
        from .auth_registration import AuthRegistrationData

        registration_data = AuthRegistrationData()
    if password_reset_data is None:
        from .password_reset_confirm import PasswordResetConfirmData

        password_reset_data = PasswordResetConfirmData()
    from .account_summary import AccountInvitesData

    invite_data = AccountInvitesData()

    def setup_redirect_if_required():
        """Match Flask's global first-run redirect for non-API invite forms."""
        from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

        if should_redirect_to_setup():
            return flask_redirect_response(get_setup_redirect_url(), status_code=302)
        return None

    async def prepare(request):
        form = await request.form() if request.method == 'POST' else {}
        session_data = _session_data(request, flask_app.config)
        csrf_error = (
            _form_csrf_error(request, form, session_data, flask_app.config)
            if request.method == 'POST' else None
        )
        auth = None
        if csrf_error is None:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
                allow_bearer=False,
            )
        return form, session_data, auth, csrf_error

    @router.post('/login', include_in_schema=False)
    async def login_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001 — malformed browser forms are client errors
                response = PlainTextResponse('Invalid login form.', status_code=400)
                return _finish(response, flask_app)
            if response is not None:
                return _finish(response, flask_app)
            if auth.user is not None:
                return _finish(flask_redirect_response('/discover', status_code=302), flask_app, auth)

            from oneirodex.schemas.auth import LoginBody

            try:
                body = LoginBody.model_validate({
                    'username': first_form_value(form, 'username', ''),
                    'password': first_form_value(form, 'password', ''),
                })
            except ValidationError:
                _flash(auth.session_data, 'error', 'Please enter your username and password.')
                return _render_auth_form(flask_app, auth)

            try:
                user, failure = login_data.authenticate(
                    body.username, body.password,
                    _client_ip(request, flask_app.config),
                )
            except Exception:  # noqa: BLE001 — credential/storage details stay private
                user, failure = None, ('internal', 'Could not sign in. Please try again.')
            if failure:
                if failure[0] == 'forbidden':
                    category = (
                        'error' if failure[1] == 'Your account has been banned.'
                        else 'warning'
                    )
                else:
                    category = 'error'
                _flash(auth.session_data, category, failure[1])
                return _finish(flask_redirect_response('/login', status_code=302), flask_app, auth)

            from oneirodex.runtime_native.auth_resolver import session_identifier
            from oneirodex.runtime_native.auth_login import _safe_next
            from oneirodex.utils.trusted_proxy import trusted_forwarded_for

            auth.session_data['_user_id'] = str(user.get_id())
            auth.session_data['_fresh'] = True
            auth.session_data['_id'] = session_identifier(
                request.client.host if request.client else None,
                request.headers.get('user-agent'),
                trusted_forwarded_for(request, flask_app.config),
            )
            auth.session_data['_remember'] = 'set'
            target = _safe_next(first_query_value(request.query_params, 'next'))
            return _finish(flask_redirect_response(target), flask_app, auth)

    @router.post('/register', include_in_schema=False)
    async def registration_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001
                response = PlainTextResponse('Invalid registration form.', status_code=400)
                return _finish(response, flask_app)
            if response is not None:
                return _finish(response, flask_app)
            invite_token = first_query_value(request.query_params, 'token')
            if auth.user is not None:
                if not invite_token:
                    return _finish(flask_redirect_response('/login', status_code=302), flask_app, auth)
                for key in ('_user_id', '_fresh', '_id', 'next', '_remember_seconds'):
                    auth.session_data.pop(key, None)
                auth.session_data['_remember'] = 'clear'

            from oneirodex.schemas.registration import RegistrationBody
            from oneirodex.runtime_native.auth_registration import _registration_errors

            try:
                body = RegistrationBody.model_validate({
                    'username': first_form_value(form, 'username', ''),
                    'email': first_form_value(form, 'email', ''),
                    'password': first_form_value(form, 'password', ''),
                }).model_dump()
            except ValidationError:
                _flash(auth.session_data, 'error', 'Please check the account details and try again.')
                return _render_auth_form(flask_app, auth)

            errors = _registration_errors(body)
            if errors:
                _flash(auth.session_data, 'error', 'Invalid registration details.')
                _flash_errors(auth.session_data, errors)
                return _render_auth_form(flask_app, auth)

            try:
                result, failure = registration_data.register(
                    body, invite_token, request, flask_app.config,
                )
            except Exception:  # noqa: BLE001 — account/mail internals stay private
                result, failure = None, ('internal', 'Could not create the account.', 500, None)
            if failure:
                _flash(auth.session_data, _failure_category(failure[0]), failure[1])
                _flash_errors(auth.session_data, failure[3])
                return _finish(flask_redirect_response(_register_target(invite_token), status_code=302), flask_app, auth)

            if result.get('confirmation_sent'):
                _flash(auth.session_data, 'success', 'A confirmation email has been sent via email.')
            else:
                _flash(auth.session_data, 'warning', 'Your account was created, but the confirmation email could not be sent.')
            return _finish(flask_redirect_response('/index'), flask_app, auth)

    @router.post('/reset_password_request', include_in_schema=False)
    async def password_reset_request_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001
                response = PlainTextResponse('Invalid password reset form.', status_code=400)
                return _finish(response, flask_app)
            if response is not None:
                return _finish(response, flask_app)
            if auth.user is not None:
                return _finish(flask_redirect_response('/login', status_code=302), flask_app, auth)

            from oneirodex.schemas.password_reset import PasswordResetRequestBody
            from oneirodex.runtime_native.password_reset_confirm import _client_ip
            from email_validator import EmailNotValidError, validate_email

            email = str(first_form_value(form, 'email') or '').strip()
            try:
                body = PasswordResetRequestBody.model_validate({'email': email})
                validate_email(body.email, check_deliverability=False)
            except (ValidationError, EmailNotValidError):
                _flash(auth.session_data, 'error', 'Invalid email address.')
                return _render_auth_form(flask_app, auth)

            try:
                outcome = password_reset_data.request_reset(
                    body.email.lower(), _client_ip(request, flask_app.config),
                    request, flask_app.config,
                )
            except Exception:  # noqa: BLE001 — keep account/mail internals private
                outcome = 'internal'
            if outcome == 'rate_limited':
                _flash(auth.session_data, 'error', 'Too many password reset requests. Please wait and try again.')
                target = '/reset_password_request'
            elif outcome == 'requested':
                _flash(auth.session_data, 'message', 'If that email is registered, password reset instructions were sent.')
                target = '/login'
            else:
                _flash(auth.session_data, 'error', 'Could not request a password reset. Please try again.')
                target = '/reset_password_request'
            return _finish(flask_redirect_response(target, status_code=302), flask_app, auth)

    @router.post('/reset_password/{token}', include_in_schema=False)
    async def password_reset_confirm_form(token: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001
                response = PlainTextResponse('Invalid password reset form.', status_code=400)
                return _finish(response, flask_app)
            if response is not None:
                return _finish(response, flask_app)
            if auth.user is not None:
                return _finish(flask_redirect_response('/login', status_code=302), flask_app, auth)

            try:
                valid_token = password_reset_data.valid_reset_token(token)
            except Exception:  # noqa: BLE001 — keep token lookup details private
                valid_token = False
            if not valid_token:
                _flash(auth.session_data, 'message', 'The password reset link is invalid or has expired.')
                return _finish(flask_redirect_response('/login', status_code=302), flask_app, auth)

            from oneirodex.schemas.password_reset import PasswordResetConfirmBody
            from oneirodex.runtime_native.password_reset_confirm import _password_form_errors

            payload = {
                'password': first_form_value(form, 'password', ''),
                'confirm_password': first_form_value(form, 'confirm_password', ''),
            }
            try:
                body = PasswordResetConfirmBody.model_validate(payload).model_dump()
            except ValidationError:
                body = payload
            errors = _password_form_errors(body)
            if errors:
                _flash(auth.session_data, 'error', 'Invalid password details.')
                _flash_errors(auth.session_data, errors)
                return _render_auth_form(flask_app, auth)
            try:
                changed = password_reset_data.reset(token, body['password'])
            except Exception:  # noqa: BLE001
                changed = None
            if changed is None:
                _flash(auth.session_data, 'error', 'Could not reset the password. Please try again.')
                target = f'/reset_password/{token}'
            elif not changed:
                _flash(auth.session_data, 'message', 'The password reset link is invalid or has expired.')
                target = '/login'
            else:
                _flash(auth.session_data, 'message', 'Your password has been reset.')
                target = '/login'
            return _finish(flask_redirect_response(target, status_code=302), flask_app, auth)

    @router.api_route('/user/invites', methods=['GET', 'HEAD', 'POST'], include_in_schema=False)
    async def invites_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001
                response = PlainTextResponse('Invalid invite form.', status_code=400)
                return _finish(response, flask_app)
            if request.method == 'POST' and response is not None:
                return _finish(response, flask_app)
            setup_response = setup_redirect_if_required()
            if setup_response is not None:
                return _finish(setup_response, flask_app, auth)
            if auth is None:
                response = flask_redirect_response('/login?next=%2Fuser%2Finvites', status_code=302)
                return _finish(response, flask_app)
            if auth.user is None:
                from .acquire_status import _login_redirect

                response = _login_redirect(flask_app, request, login_manager, auth)
                return _finish(response, flask_app, auth)
            if auth.token is not None:
                return _finish(PlainTextResponse('A browser session is required.', status_code=403), flask_app, auth)

            target = '/library?account=invites'
            if request.method in {'GET', 'HEAD'}:
                from oneirodex.utils.public_origin import site_url_is_configured
                from oneirodex.utils.role_catalog import normalize_role

                if not site_url_is_configured() and normalize_role(getattr(auth.user, 'role', None)) == 'admin':
                    _flash(
                        auth.session_data, 'warning',
                        'Set a public Site URL in admin settings so invite links are not tied to localhost. Until then, links use the address you are browsing from.',
                    )
                response = flask_redirect_response(target, status_code=302)
                return _finish(response, flask_app, auth)

            from email_validator import EmailNotValidError, validate_email

            email = str(first_form_value(form, 'email') or '').strip()
            try:
                if not email or len(email) > 254:
                    raise ValueError('invalid email')
                validate_email(email, check_deliverability=False)
            except (EmailNotValidError, ValueError):
                _flash(auth.session_data, 'error', 'Invalid email.')
                return _finish(flask_redirect_response(target, status_code=302), flask_app, auth)

            try:
                from oneirodex.utils.public_origin import public_origin_for_request

                result = invite_data.create(
                    auth.user, email,
                    origin=public_origin_for_request(request, flask_app.config),
                )
            except Exception:  # noqa: BLE001 — do not expose invite/mail/storage details
                result = {'error': 'Could not create the invite.', 'code': 'internal'}
            if 'error' in result:
                category = 'danger' if result['code'] == 'forbidden' else 'error'
                _flash(auth.session_data, category, result['error'])
            else:
                _flash(
                    auth.session_data, 'success',
                    'Invite sent successfully. The invite expires after 48 hours.',
                )
            return _finish(flask_redirect_response(target, status_code=302), flask_app, auth)

    @router.post('/delete_invite/{token}', include_in_schema=False)
    async def delete_invite_form(token: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            try:
                _form, _session, auth, response = await prepare(request)
            except Exception:  # noqa: BLE001
                response = PlainTextResponse('Invalid invite request.', status_code=400)
                return _finish(response, flask_app)
            if response is not None:
                return _finish(response, flask_app)
            setup_response = setup_redirect_if_required()
            if setup_response is not None:
                return _finish(setup_response, flask_app, auth)
            if auth.user is None:
                from .acquire_status import _login_redirect

                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None:
                response = PlainTextResponse('A browser session is required.', status_code=403)
            else:
                try:
                    result = invite_data.delete(auth.user, token)
                except Exception:  # noqa: BLE001
                    result = {'error': 'An error occurred while deleting the invite.', 'code': 'internal'}
                if result.get('code') == 'not_found':
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Invite not found or you do not have permission to delete it.',
                        code='not_found', status=200,
                    )
                    response = JSONResponse(body, status_code=status)
                elif 'error' in result:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(result['error'], code=result['code'])
                    response = JSONResponse(body, status_code=status)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload({}))
            return _finish(response, flask_app, auth)

    return router


def mount_auth_form_post_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_auth_form_post_router(flask_app, **kwargs))
    return app


def _session_data(request, config):
    from oneirodex.runtime_native.password_reset_confirm import _session_data as load_session

    return load_session(request, config)


def _form_csrf_error(request, form, session_data, config):
    if not config.get('WTF_CSRF_ENABLED', True):
        return None
    from oneirodex.runtime_native.session_compat import CsrfTokenError, validate_csrf_token

    field = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    token = request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token') or first_form_value(form, field)
    try:
        validate_csrf_token(
            token, session_data,
            config.get('WTF_CSRF_SECRET_KEY') or config.get('SECRET_KEY'),
            field_name=field, time_limit=config.get('WTF_CSRF_TIME_LIMIT', 3600),
        )
    except CsrfTokenError as exc:
        import html

        from starlette.responses import HTMLResponse

        body = (
            '<!doctype html>\n'
            '<html lang=en>\n'
            '<title>400 Bad Request</title>\n'
            '<h1>Bad Request</h1>\n'
            f'<p>{html.escape(str(exc))}</p>\n'
        )
        return HTMLResponse(body, status_code=400)
    return None


def _finish(response, flask_app, auth=None):
    if auth is not None:
        from oneirodex.runtime_native.auth_login import _write_remember_cookie
        from oneirodex.runtime_native.oidc_status import _set_session_cookie

        _write_remember_cookie(response, auth.session_data, flask_app.config)
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _render_auth_form(flask_app, auth):
    """Render compatibility-form validation in the shared auth shell."""
    from .auth_pages import _shell_response

    response = _shell_response(flask_app, auth.session_data)
    return _finish(response, flask_app, auth)


def _flash(session_data, category, message):
    flashes = list(session_data.get('_flashes') or [])
    flashes.append((category, message))
    session_data['_flashes'] = flashes


def _flash_errors(session_data, errors):
    if not isinstance(errors, dict):
        return
    for messages in errors.values():
        for message in messages:
            _flash(session_data, 'error', str(message))


def _failure_category(code):
    return 'warning' if code in {'forbidden', 'bad_request'} else 'error'


def _register_target(invite_token):
    if not invite_token:
        return '/register'
    from urllib.parse import urlencode

    return '/register?' + urlencode({'token': invite_token})


def _client_ip(request, config):
    from oneirodex.runtime_native.auth_login import _client_ip as resolve_ip

    return resolve_ip(request, config)
