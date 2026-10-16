"""Native bootstrap for the existing signed member session and CSRF token."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from starlette.responses import JSONResponse

from .session_compat import dump_session_cookie, generate_csrf_token, load_session_cookie


def member_auth_runtime_fields(app, *, database_scope=None) -> dict:
    """Read only the non-secret OIDC labels needed by the auth shell."""
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.runtime_native.db_session import native_session_scope
    from oneirodex.utils.oidc import build_oidc_config
    from oneirodex.utils.global_settings import global_settings_row
    scope = database_scope(app) if database_scope else native_session_scope(app, db)
    with scope:
        oidc = build_oidc_config(global_settings_row())
    return {
        'oidc_enabled': oidc is not None,
        'oidc_display_name': oidc.display_name if oidc else 'Sign in with SSO',
    }


def member_auth_runtime_bootstrap(
    app,
    request: Request,
    *,
    auth_fields=None,
    database_scope=None,
    runtime: str = 'fastapi-session-compat',
):
    """Issue Flask-compatible CSRF/session bootstrap data through ASGI."""
    config = app.config
    secret_key = config.get('SECRET_KEY')
    if not secret_key:
        return JSONResponse(
            {'ok': False, 'error': 'Account setup is unavailable.', 'error_code': 'unavailable',
             'message': 'Account setup is unavailable.', 'success': False},
            status_code=503,
        )

    fields = (
        auth_fields()
        if auth_fields
        else member_auth_runtime_fields(app, database_scope=database_scope)
    )
    cookie_name = config.get('SESSION_COOKIE_NAME', 'session')
    session_data = load_session_cookie(
        request.cookies.get(cookie_name),
        secret_key,
        max_age=int(config['PERMANENT_SESSION_LIFETIME'].total_seconds()),
        fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
    )
    csrf_token = generate_csrf_token(
        session_data,
        config.get('WTF_CSRF_SECRET_KEY') or secret_key,
        field_name=config.get('WTF_CSRF_FIELD_NAME', 'csrf_token'),
    )
    response = JSONResponse({
        'csrf_token': csrf_token,
        'oidc_enabled': bool(fields.get('oidc_enabled')),
        'oidc_display_name': fields.get('oidc_display_name') or 'Sign in with SSO',
        'runtime': runtime,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    })
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie'
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)

    cookie_value = dump_session_cookie(
        session_data,
        secret_key,
        fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
    )
    permanent = bool(session_data.get('_permanent'))
    lifetime = config['PERMANENT_SESSION_LIFETIME']
    expires = datetime.now(timezone.utc) + lifetime if permanent else None
    cookie_path = config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/'
    samesite = config.get('SESSION_COOKIE_SAMESITE')
    response.set_cookie(
        cookie_name,
        cookie_value,
        expires=expires,
        path=cookie_path,
        domain=config.get('SESSION_COOKIE_DOMAIN'),
        secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
        httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
        samesite=str(samesite).lower() if samesite else None,
        partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
    )
    return response
