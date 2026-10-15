"""Native FastAPI routes for managing a user's personal API tokens."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


_logger = logging.getLogger(__name__)


class PersonalTokenData:
    """Persistence adapter; route tests replace it with in-memory fakes."""

    def list_for_user(self, user_id: int) -> list[Any]:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ApiToken

        return db.session.execute(
            select(ApiToken)
            .filter_by(user_id=user_id)
            .order_by(ApiToken.created_at.desc())
        ).scalars().all()

    def create(self, user, name: str, scopes: list[str] | None):
        from oneirodex.utils.api_tokens import generate_api_token

        return generate_api_token(user, name, scopes)

    def revoke(self, token_id: int, user_id: int) -> bool:
        from oneirodex.utils.api_tokens import revoke_api_token

        return revoke_api_token(token_id, user_id=user_id)


class PersonalTokenPolicy:
    """Lazy adapter to the canonical scope catalog and generation checks."""

    def valid_scopes(self) -> frozenset[str]:
        from oneirodex.utils.api_tokens import VALID_SCOPES

        return VALID_SCOPES

    def presets(self) -> Mapping[str, Mapping[str, Any]]:
        from oneirodex.utils.api_tokens import TOKEN_SCOPE_PRESETS

        return TOKEN_SCOPE_PRESETS

    def forbidden_scopes(self, role: str | None) -> frozenset[str]:
        from oneirodex.utils.api_tokens import forbidden_scopes_for_role

        return forbidden_scopes_for_role(role)

    def is_raw_token(self, raw: str) -> bool:
        from oneirodex.utils.api_tokens import is_raw_api_token

        return is_raw_api_token(raw)


def create_account_tokens_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    policy=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Build native GET/POST/DELETE personal token routes.

    Authentication uses the shared Flask-session/remember/Bearer resolver.
    All persistence and scope policy are injectable so the contract can be
    exercised without creating a database or writing token rows.
    """
    router = APIRouter()
    data = data_access or PersonalTokenData()
    scopes_policy = policy or PersonalTokenPolicy()

    @router.api_route('/api/tokens', methods=['GET', 'HEAD'])
    def list_api_tokens(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
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
            else:
                denied = scopes_policy.forbidden_scopes(
                    getattr(auth.user, 'role', None)
                )
                payload = {
                    'tokens': [
                        row.to_public_dict()
                        for row in data.list_for_user(auth.user.id)
                    ],
                    'valid_scopes': sorted(
                        scope for scope in scopes_policy.valid_scopes()
                        if scope not in denied
                    ),
                    'scope_presets': {
                        key: preset
                        for key, preset in scopes_policy.presets().items()
                        if not denied.intersection(preset['scopes'])
                    },
                }
                response = JSONResponse(payload)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            _add_security_headers(response, flask_app.config)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/tokens')
    async def create_api_token(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )

            # Flask-WTF runs before login_required and body validation. Keep
            # that order so writes without a valid browser CSRF token fail
            # before either authentication or request-body details are exposed.
            csrf_error = _csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf_error is not None:
                response = csrf_error
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, validation_error = await _validated_body(request)
                if validation_error is not None:
                    response = validation_error
                else:
                    response = _create_token_response(
                        auth,
                        body,
                        data=data,
                        policy=scopes_policy,
                        logger=getattr(flask_app, 'logger', _logger),
                    )
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)

            _add_security_headers(response, flask_app.config)
            return response

    @router.delete('/api/tokens/{token_id:int}')
    def delete_api_token(token_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            csrf_error = _csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf_error is not None:
                response = csrf_error
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not data.revoke(token_id, auth.user.id):
                response = _api_error('Token not found', code='not_found')
            else:
                response = _api_ok()
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            _add_security_headers(response, flask_app.config)
            return response

    return router


def mount_account_tokens_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_tokens_router(flask_app, **kwargs))
    return app


async def _validated_body(request: Request) -> tuple[Any | None, Response | None]:
    from oneirodex.schemas.tokens import CreateApiTokenBody

    try:
        payload = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        return CreateApiTokenBody.model_validate(payload), None
    except ValidationError as exc:
        details: dict[str, str | list[str]] = {}
        for error in exc.errors():
            location = error.get('loc') or ()
            key = '.'.join(str(part) for part in location) or '__root__'
            message = str(error.get('msg') or 'Invalid value')
            if key in details:
                existing = details[key]
                if isinstance(existing, list):
                    existing.append(message)
                else:
                    details[key] = [existing, message]
            else:
                details[key] = message
        return None, _api_error('Invalid request.', code='unprocessable', detail=details)


def _create_token_response(auth, body, *, data, policy, logger) -> Response:
    user = auth.user
    name = body.name
    preset = (body.preset or '').strip().lower()
    scopes = body.scopes

    if preset:
        preset_def = policy.presets().get(preset)
        if preset_def is None:
            return _api_error(f'Unknown preset: {preset}', code='bad_request')
        scopes = preset_def['scopes']
    if scopes is not None and not isinstance(scopes, list):
        return _api_error('scopes must be a list', code='bad_request')
    if scopes is not None:
        if not all(isinstance(scope, str) for scope in scopes):
            return _api_error('scopes must be strings', code='bad_request')
        # One normalized list is used for every gate and for persistence.
        scopes = [scope.strip() for scope in scopes]

    if getattr(user, 'role', None) != 'admin' and scopes and 'admin' in scopes:
        return _api_error('admin scope requires admin role', code='forbidden')

    denied_by_token = []
    if auth.token is not None:
        requested = scopes or ['read:library']
        denied_by_token = [
            scope for scope in requested
            if not auth.token.has_scope(str(scope).strip())
        ]
    if denied_by_token:
        return _api_error(
            'A token can only create tokens with scopes it already has',
            code='forbidden',
            detail={'denied_scopes': denied_by_token},
        )

    denied = policy.forbidden_scopes(getattr(user, 'role', None))
    blocked = [
        str(scope).strip() for scope in (scopes or [])
        if str(scope).strip() in denied
    ]
    if blocked:
        return _api_error(
            'Those scopes are not allowed for this account',
            code='forbidden',
            detail={'denied_scopes': blocked},
        )

    row, raw = data.create(user, name, scopes)
    if not policy.is_raw_token(raw):
        logger.error('api_token_create_impure prefix=%s', getattr(row, 'token_prefix', 'unknown'))
        return _api_error('Token generation failed purity check', code='internal')
    return JSONResponse(
        {
            'token': row.to_public_dict(),
            'secret': raw,
            'warning': 'Store this secret now; it will not be shown again.',
        },
        status_code=201,
    )


def _csrf_error_response(request: Request, session_data: dict, config: Mapping[str, Any]):
    return csrf_error_response(request, session_data, config)


def _api_error(message: str, *, code: str, detail: Any = None) -> JSONResponse:
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return JSONResponse(payload, status_code=status)


def _api_ok() -> JSONResponse:
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload())


def _add_security_headers(response: Response, config: Mapping[str, Any]) -> None:
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)
