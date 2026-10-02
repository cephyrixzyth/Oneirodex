"""OIDC / SSO foundation for Oneirodex (Authentik, Authelia, Keycloak-ready)."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import func, select

from oneirodex.utils.rbac import VALID_ROLES, normalize_role
from oneirodex.utils.global_settings import global_settings_row

try:
    from authlib.integrations.flask_client import OAuth
    from authlib.oauth2.rfc7636 import create_s256_code_challenge

    AUTHLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when authlib missing
    AUTHLIB_AVAILABLE = False
    OAuth = None  # type: ignore[misc, assignment]
    create_s256_code_challenge = None  # type: ignore[misc, assignment]

OIDC_SESSION_STATE_KEY = 'oidc_auth_state'
OIDC_SESSION_VERIFIER_KEY = 'oidc_code_verifier'

DEFAULT_ROLE_MAP: dict[str, str] = {
    'admin': 'admin',
    'oneirodex-admin': 'admin',
    'oneirodex-admin': 'admin',
    'librarian': 'librarian',
    'oneirodex-librarian': 'librarian',
    'oneirodex-librarian': 'librarian',
    'child': 'child',
    'oneirodex-child': 'child',
    'oneirodex-child': 'child',
}

_oauth: Any | None = None
_oidc_registered_key: str | None = None


@dataclass(frozen=True)
class OidcConfig:
    enabled: bool
    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    role_claim: str
    role_map: dict[str, str]
    display_name: str


def get_env_oidc_enabled() -> bool:
    return os.getenv('OIDC_ENABLED', 'false').lower() in ('1', 'true', 'yes')


def parse_role_map(raw: str | dict[str, str] | None) -> dict[str, str]:
    if not raw:
        return DEFAULT_ROLE_MAP.copy()
    if isinstance(raw, dict):
        return {str(k).lower(): normalize_role(v) for k, v in raw.items()}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return DEFAULT_ROLE_MAP.copy()
    if not isinstance(parsed, dict):
        return DEFAULT_ROLE_MAP.copy()
    return {str(k).lower(): normalize_role(v) for k, v in parsed.items()}


def map_claims_to_role(
    claims: dict[str, Any],
    role_claim: str = 'groups',
    role_map: dict[str, str] | None = None,
) -> str:
    """Map IdP claim values to a Oneirodex role (admin/librarian/user/child)."""
    mapping = role_map or DEFAULT_ROLE_MAP
    claim_value = claims.get(role_claim)
    if claim_value is None:
        return 'user'

    values = claim_value if isinstance(claim_value, (list, tuple, set)) else [claim_value]
    best_role = 'user'
    best_rank = 0
    role_rank = {'child': 10, 'user': 20, 'librarian': 30, 'admin': 40}

    for value in values:
        mapped = mapping.get(str(value).lower())
        if mapped and mapped in VALID_ROLES:
            rank = role_rank.get(mapped, 0)
            if rank > best_rank:
                best_role = mapped
                best_rank = rank

    return normalize_role(best_role)


def is_oidc_enabled(settings_record=None) -> bool:
    """Feature flag: requires OIDC_ENABLED env var and GlobalSettings.oidc_enabled."""
    if not get_env_oidc_enabled():
        return False
    if settings_record is None:
        from oneirodex import db
        from oneirodex.models import GlobalSettings

        settings_record = global_settings_row()
    if not settings_record:
        return False
    return bool(getattr(settings_record, 'oidc_enabled', False))


def oidc_readiness_report(settings_record=None) -> dict[str, Any]:
    """
    Operator-facing readiness checklist for live Authentik/SSO wiring.

    Does not contact the IdP — reports local configuration completeness only.
    """
    from oneirodex import db
    from oneirodex.models import GlobalSettings

    if settings_record is None:
        settings_record = db.session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
        ).scalars().first()

    env_enabled = get_env_oidc_enabled()
    db_enabled = bool(getattr(settings_record, 'oidc_enabled', False)) if settings_record else False
    issuer = (
        (getattr(settings_record, 'oidc_issuer_url', None) if settings_record else None)
        or os.getenv('OIDC_ISSUER_URL', '')
    ).strip()
    client_id = (
        (getattr(settings_record, 'oidc_client_id', None) if settings_record else None)
        or os.getenv('OIDC_CLIENT_ID', '')
    ).strip()
    redirect_uri = (
        (getattr(settings_record, 'oidc_redirect_uri', None) if settings_record else None)
        or os.getenv('OIDC_REDIRECT_URI', '')
    ).strip()
    trusted_proxies = int(os.getenv('TRUSTED_PROXIES', '0') or '0')

    missing: list[str] = []
    if not env_enabled:
        missing.append('OIDC_ENABLED env')
    if not db_enabled:
        missing.append('Admin Integrations → Enable OIDC')
    if not issuer:
        missing.append('issuer_url')
    if not client_id:
        missing.append('client_id')
    if not redirect_uri:
        missing.append('redirect_uri')
    if not AUTHLIB_AVAILABLE:
        missing.append('authlib package')

    ready = len(missing) == 0
    return {
        'ready': ready,
        'live_verified': False,
        'env_enabled': env_enabled,
        'db_enabled': db_enabled,
        'authlib_available': AUTHLIB_AVAILABLE,
        'has_issuer': bool(issuer),
        'has_client_id': bool(client_id),
        'has_redirect_uri': bool(redirect_uri),
        'trusted_proxies': trusted_proxies,
        'missing': missing,
        'message': (
            'OIDC is fully configured locally. Complete live Authentik smoke using the runbook.'
            if ready
            else 'OIDC is not ready — missing: ' + ', '.join(missing)
        ),
        'runbook': 'docs/runbooks/oidc-sso.md',
    }


def build_oidc_config(settings_record=None) -> OidcConfig | None:
    if settings_record is None:
        from oneirodex import db
        from oneirodex.models import GlobalSettings

        settings_record = global_settings_row()

    if not is_oidc_enabled(settings_record):
        return None

    issuer = (
        getattr(settings_record, 'oidc_issuer_url', None)
        or os.getenv('OIDC_ISSUER_URL', '')
    ).strip().rstrip('/')
    client_id = (
        getattr(settings_record, 'oidc_client_id', None)
        or os.getenv('OIDC_CLIENT_ID', '')
    ).strip()
    client_secret = (
        getattr(settings_record, 'oidc_client_secret', None)
        or os.getenv('OIDC_CLIENT_SECRET', '')
    ).strip()
    redirect_uri = (
        getattr(settings_record, 'oidc_redirect_uri', None)
        or os.getenv('OIDC_REDIRECT_URI', '')
    ).strip()
    scopes = (
        getattr(settings_record, 'oidc_scopes', None)
        or os.getenv('OIDC_SCOPES', 'openid email profile')
    ).strip()
    role_claim = (
        getattr(settings_record, 'oidc_role_claim', None)
        or os.getenv('OIDC_ROLE_CLAIM', 'groups')
    ).strip() or 'groups'
    role_map_raw = getattr(settings_record, 'oidc_role_map', None) or os.getenv('OIDC_ROLE_MAP')
    display_name = (
        getattr(settings_record, 'oidc_display_name', None)
        or os.getenv('OIDC_DISPLAY_NAME', 'Sign in with SSO')
    ).strip() or 'Sign in with SSO'

    if not issuer or not client_id or not redirect_uri:
        return None

    return OidcConfig(
        enabled=True,
        issuer_url=issuer,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        role_claim=role_claim,
        role_map=parse_role_map(role_map_raw),
        display_name=display_name,
    )


def extract_user_identity(claims: dict[str, Any]) -> tuple[str, str]:
    email = (claims.get('email') or '').strip().lower()
    username = (
        claims.get('preferred_username')
        or claims.get('nickname')
        or (email.split('@')[0] if email else None)
        or claims.get('sub')
        or 'oidc-user'
    )
    return str(username).strip(), email


def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    if AUTHLIB_AVAILABLE and create_s256_code_challenge is not None:
        code_challenge = create_s256_code_challenge(code_verifier)
    else:
        # Fallback stub when authlib is unavailable (tests / partial installs).
        code_challenge = code_verifier
    return code_verifier, code_challenge


def store_oidc_session(flask_session, state: str, code_verifier: str) -> None:
    flask_session[OIDC_SESSION_STATE_KEY] = state
    flask_session[OIDC_SESSION_VERIFIER_KEY] = code_verifier


def pop_oidc_session(flask_session) -> tuple[str | None, str | None]:
    state = flask_session.pop(OIDC_SESSION_STATE_KEY, None)
    verifier = flask_session.pop(OIDC_SESSION_VERIFIER_KEY, None)
    return state, verifier


def format_oidc_idp_error(error: str, description: str | None = None) -> str:
    """Return a user-safe flash message for IdP error query params on the callback."""
    code = (error or '').strip().lower()
    detail = (description or '').strip()

    if code == 'access_denied':
        return 'Sign-in was cancelled or denied at the identity provider.'
    if code == 'invalid_request':
        if detail:
            return f'SSO request was rejected by the identity provider: {detail}'
        return 'SSO request was rejected by the identity provider.'
    if code == 'invalid_scope':
        return 'SSO scopes are misconfigured. Contact an administrator.'
    if code == 'server_error':
        return 'The identity provider reported a server error. Try again later.'
    if code == 'temporarily_unavailable':
        return 'The identity provider is temporarily unavailable. Try again later.'

    if detail:
        return f'SSO sign-in failed ({code}): {detail}'
    if code:
        return f'SSO sign-in failed ({code}). Please try again or use local login.'
    return 'SSO sign-in failed. Please try again or use local login.'


def format_oidc_callback_error(exc: Exception) -> str:
    """Return a user-safe flash message for OIDC token exchange / provisioning failures."""
    message = str(exc).strip()
    lower = message.lower()
    error_code = getattr(exc, 'error', None)
    if error_code:
        lower = f'{lower} {str(error_code).lower()}'

    if 'redirect_uri' in lower or 'redirect uri' in lower:
        return (
            'SSO redirect URI mismatch. Ensure OIDC_REDIRECT_URI matches the IdP '
            'client redirect URI exactly (including https and path).'
        )
    if 'invalid_grant' in lower or 'code_verifier' in lower or 'pkce' in lower:
        return 'SSO session expired or was reused. Please start sign-in again.'
    if 'access_denied' in lower:
        return 'Sign-in was cancelled or denied at the identity provider.'
    if 'invalid_client' in lower:
        return 'SSO client credentials are misconfigured. Contact an administrator.'
    if 'invalid_scope' in lower:
        return 'SSO scopes are misconfigured. Contact an administrator.'
    if 'state' in lower and 'invalid' in lower:
        return 'Invalid SSO state. Please try again.'

    if message and len(message) <= 180 and not any(
        token in lower for token in ('traceback', 'exception', 'http')
    ):
        return f'SSO login failed: {message}'

    return 'SSO login failed. Please try again or use local login.'


def get_oauth_client():
    global _oauth
    return _oauth


def init_oauth(app) -> Any | None:
    """Register the OIDC client with Flask. Returns OAuth instance or None."""
    global _oauth
    if not AUTHLIB_AVAILABLE:
        app.logger.warning('authlib is not installed; OIDC routes will return 503 until authlib is added.')
        return None

    if _oauth is None:
        _oauth = OAuth()
    _oauth.init_app(app)
    return _oauth


def register_oidc_provider(app, config: OidcConfig) -> None:
    global _oidc_registered_key
    oauth = init_oauth(app)
    if oauth is None:
        return

    registration_key = f'{config.issuer_url}:{config.client_id}'
    if _oidc_registered_key == registration_key:
        return

    metadata_url = urljoin(config.issuer_url + '/', '.well-known/openid-configuration')
    client_kwargs: dict[str, Any] = {'scope': config.scopes}
    if config.client_secret:
        client_kwargs['token_endpoint_auth_method'] = 'client_secret_basic'
    else:
        client_kwargs['token_endpoint_auth_method'] = 'none'

    oauth.register(
        name='oidc',
        client_id=config.client_id,
        client_secret=config.client_secret or None,
        server_metadata_url=metadata_url,
        client_kwargs=client_kwargs,
    )
    _oidc_registered_key = registration_key


def provision_or_update_user(db_session, claims: dict[str, Any], config: OidcConfig):
    """JIT provision or update a local User from OIDC claims."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from oneirodex.models import User

    username, email = extract_user_identity(claims)
    role = map_claims_to_role(claims, config.role_claim, config.role_map)
    subject = str(claims.get('sub') or '').strip()[:255] or None

    # Linking order. It used to match by email without asking whether the
    # provider verified it, then by username, so an IdP account called "admin"
    # (or claiming the admin's address) signed in as the local admin.
    #   1. the provider subject stored on an earlier sign-in;
    #   2. a local account whose email the provider says is verified, and
    #      only one not yet linked to another subject;
    #   3. an account this code created earlier for a provider that sends no
    #      email (placeholder address), by name;
    #   4. otherwise a new account.
    user = None
    if subject:
        user = db_session.execute(select(User).filter(User.oidc_subject == subject)).scalars().first()

    if user is None and email and _email_verified(claims):
        candidate_user = db_session.execute(
            select(User).filter(func.lower(User.email) == email)
        ).scalars().first()
        if candidate_user is not None and candidate_user.oidc_subject in (None, subject):
            user = candidate_user

    if user is None and not email:
        candidate_user = db_session.execute(
            select(User).filter(func.lower(User.name) == func.lower(username))
        ).scalars().first()
        if (candidate_user is not None and candidate_user.oidc_subject in (None, subject)
                and (candidate_user.email or '').endswith('@oidc.local')):
            user = candidate_user

    if user is None and email and db_session.execute(
        select(User.id).filter(func.lower(User.email) == email)
    ).first() is not None:
        # The address belongs to a local account we may not link (the provider
        # did not verify it, or it is already linked elsewhere). A second
        # account cannot share it either.
        raise ValueError(
            'An account with this email already exists. Sign in with its password, '
            'or ask your identity provider to verify the address.'
        )

    if user is None:
        base_name = username[:64]
        candidate = base_name
        suffix = 1
        while db_session.execute(select(User).filter_by(name=candidate)).scalars().first():
            candidate = f'{base_name[:58]}-{suffix}'
            suffix += 1

        user = User(
            user_id=str(uuid4()),
            name=candidate,
            email=email or f'{candidate}@oidc.local',
            role=role,
            # Explicit: the column default only applies at INSERT, so the
            # disabled-account check below saw None and refused every new user.
            state=True,
            is_email_verified=True,
            created=datetime.now(timezone.utc),
        )
        user.set_password(secrets.token_urlsafe(32))
        db_session.add(user)
    else:
        # The local email is left alone: overwriting it from the provider let
        # a linked IdP account take over password resets for the local account.
        # Sec-B: lock roles after first provision so IdP group churn cannot escalate/demote.
        roles_locked = True
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                roles_locked = bool(current_app.config.get('OIDC_LOCK_ROLES', True))
        except Exception:
            roles_locked = True
        if not roles_locked:
            user.role = normalize_role(role)
        if not user.is_email_verified:
            user.is_email_verified = True

    user.lastlogin = datetime.now(timezone.utc)
    if user.state is False:
        raise ValueError('Account is disabled.')
    if subject and not user.oidc_subject:
        user.oidc_subject = subject

    db_session.commit()
    return user


def _email_verified(claims: dict[str, Any]) -> bool:
    """The provider vouches for the email (OIDC ``email_verified``), or the
    operator vouches for the provider (``OIDC_TRUST_PROVIDER_EMAIL``)."""
    value = claims.get('email_verified')
    if isinstance(value, str):
        value = value.strip().lower() == 'true'
    if value is True:
        return True
    try:
        from flask import current_app, has_app_context

        return bool(has_app_context() and current_app.config.get('OIDC_TRUST_PROVIDER_EMAIL'))
    except Exception:  # noqa: BLE001
        return False
