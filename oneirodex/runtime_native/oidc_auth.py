"""Native FastAPI OIDC authorization-code flow with signed-session PKCE state."""
from __future__ import annotations

import secrets
import uuid
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse

from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context
from .query_compat import first_query_value

_NONCE_KEY = 'oidc_nonce'


class OidcAuthData:
    def settings(self):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GlobalSettings

        return db.session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()

    def provision(self, claims, config, app):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.oidc import provision_or_update_user

        return provision_or_update_user(
            db.session, claims, config,
            roles_locked=bool(app.config.get('OIDC_LOCK_ROLES', True)),
            trust_provider_email=bool(app.config.get('OIDC_TRUST_PROVIDER_EMAIL', False)),
        )

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def log_login(self, user):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'User {user.name} logged in via OIDC SSO.',
            event_type='login', event_level='information',
        )


def create_oidc_auth_router(
    app, *, find_user: Callable[[int], Any | None], find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None], load_user_id=None, login_manager=None,
    data_access=None, database_scope=None, client_factory=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or OidcAuthData()

    @router.get('/login/oidc')
    async def oidc_start(request: Request):
        return await _start(request, app, data, find_user, find_token,
                            commit_token_touch, load_user_id, login_manager,
                            database_scope, client_factory)

    @router.get('/login/oidc/callback')
    async def oidc_callback(request: Request):
        return await _callback(request, app, data, find_user, find_token,
                               commit_token_touch, load_user_id, login_manager,
                               database_scope, client_factory)

    return router


async def _start(request, app, data, find_user, find_token, commit_token_touch,
                 load_user_id, login_manager, database_scope, client_factory):
    from oneirodex.utils.oidc import (
        AUTHLIB_NATIVE_AVAILABLE, OIDC_SESSION_STATE_KEY, OIDC_SESSION_VERIFIER_KEY,
        build_oidc_config, generate_pkce_pair,
    )

    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        auth = _auth(request, app, find_user, find_token, commit_token_touch, load_user_id, login_manager)
        if auth.user is not None:
            return _finish(RedirectResponse('/discover', status_code=302), app, auth, request)
        config = build_oidc_config(data.settings())
        if not config:
            _flash(auth, 'warning', 'Single sign-on is not enabled.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request)
        if not AUTHLIB_NATIVE_AVAILABLE:
            _flash(auth, 'error', 'SSO is configured but authlib is not installed. Contact an administrator.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request)
        try:
            client = (client_factory or _make_oidc_client)(config)
            verifier, challenge = generate_pkce_pair()
            state = uuid.uuid4().hex
            nonce = secrets.token_urlsafe(32)
            auth.session_data[OIDC_SESSION_STATE_KEY] = state
            auth.session_data[OIDC_SESSION_VERIFIER_KEY] = verifier
            auth.session_data[_NONCE_KEY] = nonce
            authorization = await client.create_authorization_url(
                redirect_uri=config.redirect_uri, state=state,
                code_challenge=challenge, code_challenge_method='S256', nonce=nonce,
            )
            response = RedirectResponse(authorization['url'], status_code=302)
        except Exception:
            app.logger.exception('OIDC authorization initialization failed')
            _flash(auth, 'error', 'SSO client failed to initialize.')
            response = RedirectResponse('/login', status_code=302)
        return _finish(response, app, auth, request, force_session=True)


async def _callback(request, app, data, find_user, find_token, commit_token_touch,
                    load_user_id, login_manager, database_scope, client_factory):
    from oneirodex.utils.oidc import OIDC_SESSION_STATE_KEY, OIDC_SESSION_VERIFIER_KEY
    from oneirodex.runtime_native.auth_resolver import session_identifier
    from oneirodex.utils.trusted_proxy import trusted_forwarded_for
    from oneirodex.utils.oidc import (
        AUTHLIB_NATIVE_AVAILABLE, build_oidc_config, format_oidc_callback_error,
        format_oidc_idp_error,
    )

    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        auth = _auth(request, app, find_user, find_token, commit_token_touch, load_user_id, login_manager)
        if auth.user is not None:
            return _finish(RedirectResponse('/discover', status_code=302), app, auth, request)
        config = build_oidc_config(data.settings())
        if not config:
            _flash(auth, 'warning', 'Single sign-on is not enabled.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request)
        if not AUTHLIB_NATIVE_AVAILABLE:
            _flash(auth, 'error', 'SSO is configured but authlib is not installed.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request)
        idp_error = first_query_value(request.query_params, 'error')
        if idp_error:
            _flash(auth, 'error', format_oidc_idp_error(idp_error, first_query_value(request.query_params, 'error_description')))
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request)

        state = auth.session_data.pop(OIDC_SESSION_STATE_KEY, None)
        verifier = auth.session_data.pop(OIDC_SESSION_VERIFIER_KEY, None)
        nonce = auth.session_data.pop(_NONCE_KEY, None)
        callback_state = first_query_value(request.query_params, 'state')
        if not state or not callback_state or not secrets.compare_digest(str(state), str(callback_state)):
            _flash(auth, 'error', 'Invalid SSO state. Please try again.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request, force_session=True)
        if not verifier or not nonce:
            _flash(auth, 'error', 'SSO session expired or was reused. Please start sign-in again.')
            return _finish(RedirectResponse('/login', status_code=302), app, auth, request, force_session=True)

        try:
            client = (client_factory or _make_oidc_client)(config)
            token = await client.fetch_access_token(
                redirect_uri=config.redirect_uri,
                code=first_query_value(request.query_params, 'code'),
                code_verifier=verifier,
            )
            id_token = token.get('id_token') if isinstance(token, dict) else None
            if not isinstance(id_token, str) or not id_token.strip():
                raise ValueError(
                    'SSO response did not include a valid identity token. '
                    'Please contact an administrator.'
                )
            claims = await client.parse_id_token(token, nonce=nonce)
            if (
                not isinstance(claims, dict)
                or not isinstance(claims.get('sub'), str)
                or not claims['sub'].strip()
            ):
                raise ValueError(
                    'SSO response did not contain a valid identity. '
                    'Please contact an administrator.'
                )
            userinfo = token.get('userinfo')
            # The legacy Authlib callback prefers its validated userinfo claim
            # set. The native flow parses the ID token directly, so recover
            # profile and configured role claims from UserInfo when that token
            # is sparse. UserInfo must belong to the same OIDC subject, and it
            # can never replace signed identity or token-validation claims.
            role_claim = config.role_claim or 'groups'
            profile_claims = ('email', 'preferred_username', 'nickname')
            if not isinstance(userinfo, dict) and (
                not any(claims.get(key) for key in profile_claims)
                or role_claim not in claims
            ):
                try:
                    userinfo = await client.userinfo(token=token)
                except Exception:
                    app.logger.warning('OIDC UserInfo lookup failed; using validated ID token claims.', exc_info=True)
            if isinstance(userinfo, dict) and userinfo:
                subject = claims['sub']
                userinfo_subject = userinfo.get('sub')
                if userinfo_subject != subject:
                    raise ValueError('SSO identity claims did not match. Please contact an administrator.')
                for key, value in userinfo.items():
                    if key not in claims and key not in {
                        'iss', 'sub', 'aud', 'azp', 'exp', 'iat',
                        'auth_time', 'nonce', 'at_hash', 'c_hash',
                    }:
                        claims[key] = value
            user = data.provision(claims, config, app)
        except ValueError as exc:
            data.rollback()
            _flash(auth, 'error', str(exc))
            response = RedirectResponse('/login', status_code=302)
            return _finish(response, app, auth, request, force_session=True)
        except Exception as exc:
            data.rollback()
            app.logger.exception('OIDC callback failed')
            _flash(auth, 'error', format_oidc_callback_error(exc))
            response = RedirectResponse('/login', status_code=302)
            return _finish(response, app, auth, request, force_session=True)

        auth.session_data['_user_id'] = str(user.get_id())
        auth.session_data['_fresh'] = True
        auth.session_data['_id'] = session_identifier(
            request.client.host if request.client else None,
            request.headers.get('user-agent'),
            trusted_forwarded_for(request, app.config),
        )
        auth.session_data['_remember'] = 'set'
        data.log_login(user)
        response = RedirectResponse(_safe_next(first_query_value(request.query_params, 'next')), status_code=302)
        from oneirodex.runtime_native.auth_login import _write_remember_cookie
        _write_remember_cookie(response, auth.session_data, app.config)
        return _finish(response, app, auth, request, force_session=True)


def _auth(request, app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _make_oidc_client(config):
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    client_kwargs = {'scope': config.scopes}
    if config.client_secret:
        client_kwargs['token_endpoint_auth_method'] = 'client_secret_basic'
    else:
        client_kwargs['token_endpoint_auth_method'] = 'none'
    oauth.register(
        name='oidc', client_id=config.client_id,
        client_secret=config.client_secret or None,
        server_metadata_url=config.issuer_url.rstrip('/') + '/.well-known/openid-configuration',
        client_kwargs=client_kwargs,
    )
    client = oauth.create_client('oidc')
    if client is None:
        raise RuntimeError('OIDC client registration failed')
    return client


def _safe_next(value):
    from urllib.parse import urlsplit

    if isinstance(value, str):
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if candidate.startswith('/') and candidate[1:2] not in {'/', '\\'} and not parsed.scheme and not parsed.netloc:
            return candidate
    return '/discover'


def _flash(auth, category, message):
    values = list(auth.session_data.get('_flashes') or [])
    values.append((category, message))
    auth.session_data['_flashes'] = values


def _finish(response, app, auth, request, *, force_session=False):
    if force_session or auth.should_set_session_cookie or auth.session_data.get('_flashes'):
        _set_session_cookie(response, app, auth)
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(app.config).items():
        response.headers.setdefault(key, value)
    return response


def mount_oidc_auth_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_oidc_auth_router(flask_app, **kwargs))
    return app
