"""Native FastAPI account summary and invite routes."""
from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response as _csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class AccountSummaryData:
    """Adapter for the existing account summary projection and counts."""

    def summary(self, user, *, static_url=None, package_root=None) -> dict:
        from oneirodex.utils.account_invites import (
            invites_unlimited,
            smtp_ready,
            unused_invite_count,
        )
        from oneirodex.utils.avatar import STOCK_AVATARS, avatar_url

        unused = unused_invite_count(user)
        unlimited = invites_unlimited(user)
        return {
            'username': user.name,
            'email': user.email,
            'role': user.role,
            'avatar_path': user.avatarpath,
            'avatar_url': avatar_url(
                user.avatarpath,
                theme=getattr(getattr(user, 'preferences', None), 'theme', None) or 'default',
                static_url=static_url,
                package_root=package_root,
            ),
            'stock_avatars': [
                {**entry, 'url': avatar_url(
                    entry['path'], theme='default', static_url=static_url,
                    package_root=package_root,
                )}
                for entry in STOCK_AVATARS
            ],
            'invite_quota': None if unlimited else user.invite_quota,
            'invites_used': unused,
            'invites_remaining': (
                None if unlimited else max(0, (user.invite_quota or 0) - unused)
            ),
            'invites_unlimited': unlimited,
            'smtp_enabled': smtp_ready(),
        }


class AccountInvitesData:
    """Adapter around the existing browser account invites projection."""

    def invites(self, user, *, origin: str | None = None) -> dict:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken
        from oneirodex.utils.account_invites import (
            INVITE_TTL_HOURS,
            invite_row,
            invites_unlimited,
            site_url,
            smtp_ready,
        )
        from oneirodex.utils.public_origin import is_local_site_url, site_url_is_configured

        invites = db.session.execute(
            select(InviteToken).filter_by(creator_user_id=user.user_id, used=False)
        ).scalars().all()
        unlimited = invites_unlimited(user)
        return {
            'invites': [invite_row(invite, origin=origin) for invite in invites],
            'quota': None if unlimited else user.invite_quota,
            'remaining': None if unlimited else max(0, (user.invite_quota or 0) - len(invites)),
            'unlimited': unlimited,
            'smtp_enabled': smtp_ready(),
            'ttl_hours': INVITE_TTL_HOURS,
            'site_url_configured': site_url_is_configured() or not is_local_site_url(site_url()),
        }

    def create(self, user, email: str | None, *, origin: str | None = None) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken
        from oneirodex.utils.account_invites import (
            invite_row,
            invite_url,
            invites_unlimited,
            smtp_ready,
            unused_invite_count,
        )

        unused = unused_invite_count(user)
        unlimited = invites_unlimited(user)
        if not unlimited and (user.invite_quota or 0) <= unused:
            return {'error': "You're out of invites. An admin can raise your limit.", 'code': 'forbidden'}

        token = str(uuid.uuid4())
        invite = InviteToken(
            token=token,
            creator_user_id=user.user_id,
            recipient_email=email,
        )
        db.session.add(invite)
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logging.getLogger(__name__).warning('invite create failed: %s', exc)
            return {'error': 'Could not create the invite.', 'code': 'internal'}

        emailed = False
        if email and smtp_ready():
            try:
                from oneirodex.utils.smtp import send_invite_email_quiet

                emailed = bool(send_invite_email_quiet(
                    email, invite_url(token, origin=origin), audit_user=getattr(user, 'id', None) or 'system',
                ))
            except Exception as exc:
                logging.getLogger(__name__).warning('invite email failed: %s', exc)

        return {
            'invite': invite_row(invite, origin=origin),
            'emailed': emailed,
            'remaining': None if unlimited else max(0, (user.invite_quota or 0) - (unused + 1)),
            'unlimited': unlimited,
        }

    def delete(self, user, token: str) -> dict:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken
        from oneirodex.utils.account_invites import unused_invite_count

        invite = db.session.execute(
            select(InviteToken).filter_by(token=token, creator_user_id=user.user_id)
        ).scalar_one_or_none()
        if invite is None:
            return {'error': 'Invite not found.', 'code': 'not_found'}
        db.session.delete(invite)
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logging.getLogger(__name__).warning('invite delete failed: %s', exc)
            return {'error': 'Could not revoke the invite.', 'code': 'internal'}
        return {
            'revoked': token,
            'remaining': max(0, (user.invite_quota or 0) - unused_invite_count(user)),
        }


def create_account_summary_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    invites_data=None,
    mutations_data=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Create GET/HEAD route preserving browser-session-only account access."""
    router = APIRouter()
    data = data_access or AccountSummaryData()
    invite_data = invites_data or AccountInvitesData()
    mutations = mutations_data or invite_data
    uses_native_data = data_access is None

    def request_scope():
        return database_scope(flask_app) if database_scope else nullcontext()

    def static_url(filename: str) -> str:
        adapter = flask_app.url_map.bind(
            'localhost', script_name=flask_app.config.get('APPLICATION_ROOT') or '/',
        )
        return adapter.build('static', {'filename': filename})

    @router.api_route('/api/account/summary', methods=['GET', 'HEAD'])
    def account_summary(request: Request):
        with request_scope():
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None:
                response = _native_error(
                    'Sign in with your site account to manage invites', 'forbidden',
                    config=flask_app.config,
                )
            else:
                payload = (
                    data.summary(auth.user, static_url=static_url, package_root=flask_app.root_path)
                    if uses_native_data else data.summary(auth.user)
                )
                response = _native_success(payload, config=flask_app.config)
                # Flask persists the session after remember-cookie login. The
                # resolver marks that login as a session modification.
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/account/invites', methods=['GET', 'HEAD', 'POST'])
    async def account_invites(request: Request):
        with request_scope():
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if request.method == 'POST':
                csrf_response = _csrf_error_response(request, auth.session_data, flask_app.config)
                if csrf_response is not None:
                    response = csrf_response
                elif auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                elif auth.token is not None:
                    response = _native_error(
                        'Sign in with your site account to manage invites', 'forbidden',
                        config=flask_app.config,
                    )
                else:
                    body = _json_mapping(await request.body())
                    raw_email = body.get('email')
                    email = None
                    invalid_email = False
                    if raw_email is not None:
                        if not isinstance(raw_email, str):
                            invalid_email = True
                        else:
                            email = raw_email.strip() or None
                            if email:
                                from email_validator import EmailNotValidError, validate_email

                                try:
                                    validate_email(email, check_deliverability=False)
                                except EmailNotValidError:
                                    invalid_email = True

                    if invalid_email:
                        response = _native_error(
                            'Invalid email.', 'bad_request', config=flask_app.config,
                        )
                    else:
                        from oneirodex.utils.public_origin import public_origin_for_request

                        result = mutations.create(
                            auth.user, email,
                            origin=public_origin_for_request(request, flask_app.config),
                        )
                        if 'error' in result:
                            response = _native_error(
                                result['error'], result['code'], config=flask_app.config,
                            )
                        else:
                            response = _native_success(
                                result, status=201, config=flask_app.config,
                            )
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None:
                response = _native_error(
                    'Sign in with your site account to manage invites', 'forbidden',
                    config=flask_app.config,
                )
            else:
                from oneirodex.utils.public_origin import public_origin_for_request

                response = _native_success(invite_data.invites(
                    auth.user,
                    origin=public_origin_for_request(request, flask_app.config),
                ), config=flask_app.config)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/account/invites/{token}', methods=['DELETE'])
    def delete_account_invite(token: str, request: Request):
        with request_scope():
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            csrf_response = _csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None:
                response = _native_error(
                    'Sign in with your site account to manage invites', 'forbidden',
                    config=flask_app.config,
                )
            else:
                result = mutations.delete(auth.user, token)
                if 'error' in result:
                    response = _native_error(
                        result['error'], result['code'], config=flask_app.config,
                    )
                else:
                    response = _native_success(result, config=flask_app.config)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_account_summary_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_summary_router(flask_app, **kwargs))
    return app


def _json_mapping(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _native_json_response(payload, *, status=200, config):
    from oneirodex.runtime_native.runtime_context import NativeJSONProvider

    provider = NativeJSONProvider(config)
    body = (provider.dumps(payload, separators=(',', ':')) + '\n').encode('utf-8')
    return Response(body, status_code=status, media_type=provider.mimetype)


def _native_success(payload, *, status=200, config):
    from oneirodex.utils.api_contract import api_ok_payload

    return _native_json_response(api_ok_payload(payload), status=status, config=config)


def _native_error(message, code, *, detail=None, config):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return _native_json_response(payload, status=status, config=config)


