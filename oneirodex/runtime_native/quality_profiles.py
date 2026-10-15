"""Native FastAPI handler for the admin quality-profile list endpoint."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class QualityProfilesData:
    """Adapter around the existing list helper (including its legacy projection)."""

    def list(self) -> dict:
        from oneirodex.utils.quality_profiles import list_quality_profiles

        return list_quality_profiles()

    def create(self, payload: dict) -> dict:
        from oneirodex.utils.quality_profiles import create_quality_profile

        return create_quality_profile(payload)

    def save(self, payload: dict) -> dict:
        from oneirodex.utils.quality_profiles import save_quality_profile

        return save_quality_profile(payload)

    def set_active(self, profile_id: str) -> dict:
        from oneirodex.utils.quality_profiles import set_active_quality_profile

        return set_active_quality_profile(profile_id)

    def get_one(self, profile_id: str) -> dict:
        from oneirodex.utils.quality_profiles import get_quality_profile

        return get_quality_profile(profile_id)

    def update(self, profile_id: str, payload: dict) -> dict:
        from oneirodex.utils.quality_profiles import update_quality_profile

        return update_quality_profile(profile_id, payload)

    def delete(self, profile_id: str) -> dict:
        from oneirodex.utils.quality_profiles import delete_quality_profile

        return delete_quality_profile(profile_id)

    def score(self, *, title: str, size_bytes: int | None, profile_id: str | None) -> dict:
        from oneirodex.utils.quality_profiles import score_release_title

        return score_release_title(title, size_bytes=size_bytes, profile_id=profile_id)


def create_quality_profiles_router(
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
    """Create native GET/HEAD routes matching login_required/admin_required."""
    router = APIRouter()
    data = data_access or QualityProfilesData()

    @router.api_route('/api/quality-profiles/{profile_id}', methods=['GET', 'HEAD', 'PUT', 'PATCH', 'DELETE'])
    @router.api_route('/api/quality-profiles', methods=['GET', 'HEAD', 'POST', 'PUT'])
    @router.api_route('/api/quality-profiles/score', methods=['POST'])
    @router.api_route('/api/quality-profiles/active', methods=['PUT', 'POST'])
    async def quality_profiles(request: Request, profile_id: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            writing = request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            csrf_response = None
            if writing:
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload
            from oneirodex.utils.role_catalog import normalize_role
            from starlette.responses import JSONResponse

            user = auth.user if auth is not None else None
            is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and (
                normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            else:
                path = request.url.path
                body = None
                if request.method in ('POST', 'PUT', 'PATCH'):
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                payload_body = body if isinstance(body, dict) else {}
                if path.endswith('/active') and request.method in ('PUT', 'POST'):
                    from pydantic import ValidationError
                    from oneirodex.schemas.quality_stats import SetActiveQualityProfileBody
                    from oneirodex.utils.validation import format_validation_errors

                    try:
                        model = SetActiveQualityProfileBody.model_validate(payload_body)
                        result = data.set_active((model.id or model.active_id or model.profile_id or '').strip())
                    except ValidationError as exc:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    except KeyError as exc:
                        payload, status = api_error_payload(str(exc), code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(result)
                elif path.endswith('/score') and request.method == 'POST':
                    from pydantic import ValidationError
                    from oneirodex.schemas.quality_stats import ScoreReleaseBody
                    from oneirodex.utils.validation import format_validation_errors

                    try:
                        model = ScoreReleaseBody.model_validate(payload_body)
                    except ValidationError as exc:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            size_bytes = int(model.size_bytes) if model.size_bytes is not None else None
                        except (TypeError, ValueError):
                            size_bytes = None
                        profile = (model.profile_id or model.id or '').strip() or None
                        response = JSONResponse(data.score(
                            title=model.title, size_bytes=size_bytes, profile_id=profile,
                        ))
                elif profile_id is not None:
                    if request.method == 'GET':
                        result = data.get_one(profile_id)
                        if result.get('id') != profile_id:
                            payload, status = api_error_payload(f'profile not found: {profile_id}', code='not_found')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(result)
                    elif request.method == 'DELETE':
                        try:
                            response = JSONResponse(data.delete(profile_id))
                        except KeyError as exc:
                            payload, status = api_error_payload(str(exc), code='not_found')
                            response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            response = JSONResponse(data.update(profile_id, payload_body))
                        except KeyError as exc:
                            payload, status = api_error_payload(str(exc), code='not_found')
                            response = JSONResponse(payload, status_code=status)
                        except (TypeError, ValueError) as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                elif request.method in ('GET', 'HEAD'):
                    response = JSONResponse(data.list())
                elif request.method == 'POST':
                    try:
                        response = JSONResponse(data.create(payload_body), status_code=201)
                    except (TypeError, ValueError) as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        response = JSONResponse(data.save(payload_body))
                    except KeyError as exc:
                        payload, status = api_error_payload(str(exc), code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    except (TypeError, ValueError) as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_quality_profiles_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_quality_profiles_router(flask_app, **kwargs))
    return app
