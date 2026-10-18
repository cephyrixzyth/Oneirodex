"""FastAPI admin newsletter API routes."""
from __future__ import annotations

from .form_compat import first_form_value, first_form_values
from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .request_auth import request_auth_context


class AdminNewsletterData:
    def readiness(self):
        from oneirodex.utils.global_settings import global_settings_row

        settings = global_settings_row()
        enabled = bool(settings and (settings.settings or {}).get('enableNewsletterFeature', False))
        smtp = bool(settings and settings.smtp_enabled and settings.smtp_server
                     and settings.smtp_default_sender)
        return {'newsletter_enabled': enabled, 'smtp_ready': smtp,
                'can_send': enabled and smtp}

    def list_state(self):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Newsletter, User

        users = db.session.execute(select(User)).scalars().all()
        history = db.session.execute(
            select(Newsletter).order_by(Newsletter.sent_date.desc())
        ).scalars().all()
        return {
            **self.readiness(),
            'recipients': [{'id': user.id, 'email': user.email}
                           for user in users if user.email],
            'newsletters': [_summary(row) for row in history],
        }

    def detail(self, newsletter_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Newsletter

        row = db.session.get(Newsletter, newsletter_id)
        if row is None:
            return None
        return {
            **_summary(row), 'content': row.content,
            'sender': row.sender.name if row.sender else 'Unknown member',
            # Historical transport errors may have contained credentials or paths.
            'delivery_error': 'Some recipients could not be reached.'
            if row.status == 'failed' else None,
        }

    def send(self, subject, content, recipients, user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Newsletter, User
        from oneirodex.utils.smtp import send_email_quiet

        if not self.readiness()['can_send']:
            return None, 'Enable newsletters and configure SMTP before sending.', 'conflict'
        allowed = {row.email for row in db.session.execute(select(User)).scalars().all()
                   if row.email}
        if any(address not in allowed for address in recipients):
            return None, 'Select existing member recipients.', 'bad_request'
        recipients = list(dict.fromkeys(recipients))
        row = Newsletter(
            subject=subject.strip(), content=content, sender_id=user.id,
            recipient_count=len(recipients), recipients=recipients, status='pending',
        )
        db.session.add(row)
        db.session.commit()
        failed = 0
        for address in recipients:
            try:
                delivered = send_email_quiet(address, row.subject, content)
            except Exception:  # noqa: BLE001 — delivery details stay private
                delivered = False
            if not delivered:
                failed += 1
        row.status = 'failed' if failed else 'sent'
        row.error_message = f'Could not deliver to {failed} recipient(s).' if failed else None
        db.session.commit()
        return {'newsletter': _summary(row), 'failed_count': failed}, None, None

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_admin_newsletters_router(
    flask_app, *, find_user, find_token, commit_token_touch,
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
):
    from .acquire_status import _login_redirect

    router = APIRouter()
    data = data_access or AdminNewsletterData()

    @router.api_route('/api/admin/newsletters', methods=['GET', 'HEAD', 'POST'])
    @router.api_route('/api/admin/newsletters/{newsletter_id:int}', methods=['GET', 'HEAD'])
    @router.post('/admin/newsletter')
    async def newsletters(request: Request, newsletter_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            legacy_form = request.url.path == '/admin/newsletter'
            form_data = {}
            form_error = None
            if request.method == 'POST':
                if legacy_form:
                    form_data, form_error = await _legacy_form(request)
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                response = form_error or csrf_error_response(
                    request, session_data, flask_app.config,
                    token=form_data.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')) if legacy_form else None,
                )
                auth = None
            else:
                response = None
                auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
                if auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                else:
                    from oneirodex.utils.role_catalog import normalize_role

                    if normalize_role(getattr(auth.user, 'role', None)) != 'admin' or (
                        auth.token is not None and not auth.has_scope('admin')
                    ):
                        response = _error('Admin required', 'forbidden', 403)
            if response is None:
                if request.method in ('GET', 'HEAD'):
                    try:
                        if newsletter_id is None:
                            response = _ok(data.list_state())
                        elif newsletter_id < 1 or newsletter_id > 2147483647:
                            response = _error('Newsletter not found.', 'not_found', 404)
                        else:
                            detail = data.detail(newsletter_id)
                            response = (_ok({'newsletter': detail}) if detail is not None
                                        else _error('Newsletter not found.', 'not_found', 404))
                        response.headers['Cache-Control'] = 'no-store'
                    except Exception:  # noqa: BLE001 — keep ORM errors private
                        response = _error(
                            'Could not load newsletter.' if newsletter_id else 'Could not load newsletters.',
                            'internal', 500,
                        )
                else:
                    if legacy_form:
                        response = await _legacy_send(form_data, auth.user, auth, data)
                    else:
                        payload = await _json_object(request)
                        response = _send_newsletter(payload, auth.user, data)
            if auth is not None and (auth.should_set_session_cookie or auth.session_data.get('_flashes')):
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


def mount_admin_newsletters_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_newsletters_router(flask_app, **kwargs))
    return app


def _summary(row):
    return {
        'id': row.id, 'subject': row.subject,
        'sent_date': row.sent_date.isoformat() if row.sent_date else None,
        'status': row.status if row.status in ('pending', 'sent', 'failed') else 'unknown',
        'recipient_count': row.recipient_count,
    }


def _send_newsletter(payload, user, data):
    if not isinstance(payload, dict) or set(payload) != {'subject', 'content', 'recipients'}:
        return _error('Provide a subject, content and selected recipients.', 'bad_request', 400)
    subject, content, recipients = (payload[key] for key in ('subject', 'content', 'recipients'))
    if (not isinstance(subject, str) or not subject.strip() or len(subject) > 255
            or '\r' in subject or '\n' in subject
            or not isinstance(content, str) or not content.strip() or len(content) > 1_048_576
            or not isinstance(recipients, list) or not recipients
            or any(not isinstance(value, str) or not value or '\r' in value or '\n' in value
                   for value in recipients)):
        return _error('Enter a valid subject, message and recipients.', 'bad_request', 400)
    try:
        result, message, code = data.send(subject, content, recipients, user)
    except Exception:  # noqa: BLE001 — preserve safe send error and rollback
        data.rollback()
        return _error(
            'Could not complete newsletter delivery. Check history before trying again.',
            'internal', 500,
        )
    if message:
        return _error(message, code, 409 if code == 'conflict' else 400)
    return _ok(result)


async def _legacy_send(form, user, auth, data):
    import json
    from .account_avatar_upload import _flash

    subject = first_form_value(form, 'subject') or ''
    content = first_form_value(form, 'content') or ''
    recipients = [value.strip() for value in (first_form_value(form, 'recipients') or '').split(',') if value.strip()]
    if not subject.strip() or not content.strip() or not recipients:
        _flash(auth.session_data, 'error', 'Please correct the errors below.')
        return RedirectResponse('/admin/newsletter', status_code=302)
    result = _send_newsletter(
        {'subject': subject, 'content': content, 'recipients': recipients}, user, data,
    )
    payload = json.loads(result.body or b'{}')
    if result.status_code >= 400:
        category = 'warning' if result.status_code == 409 else 'error'
        _flash(auth.session_data, category, payload.get('error') or 'Could not send newsletter.')
    elif int((payload.get('failed_count') or 0)) > 0:
        _flash(auth.session_data, 'error', 'Some recipients could not be reached.')
    else:
        _flash(auth.session_data, 'success', 'Newsletter sent successfully!')
    return RedirectResponse('/admin/newsletter', status_code=302)


async def _legacy_form(request):
    from urllib.parse import parse_qs

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1_114_112:
            return {}, Response(status_code=413)
    try:
        fields = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}, Response(status_code=400)
    return first_form_values(fields), None


async def _json_object(request):
    import json

    try:
        value = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=status)
