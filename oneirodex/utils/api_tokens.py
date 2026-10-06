"""API token helpers: create, verify, and Flask-Login request loader."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, g, has_app_context
from flask_login import current_user
from sqlalchemy import select

from oneirodex import db, login_manager
from oneirodex.models import ApiToken, User
from oneirodex.utils.api_response import api_error
from oneirodex.utils.rbac import normalize_role

VALID_SCOPES = frozenset({
    'read:library',
    'read:social',
    'write:social',
    'write:presence',
    'write:download',
    'write:library',
    'admin',
})

TOKEN_SCOPE_PRESETS: dict[str, dict] = {
    'companion': {
        'label': 'Desktop companion',
        'scopes': ['read:library', 'write:download'],
    },
    'thin': {
        'label': 'Thin client',
        'scopes': ['read:library', 'read:social', 'write:presence'],
    },
}

TOKEN_PREFIX = 'gt_'
# Public prefix is secrets.token_hex(4); secret is secrets.token_urlsafe(32).
_RAW_TOKEN_RE = re.compile(r'^gt_[0-9a-f]{8}_[A-Za-z0-9_-]+$')
_logger = logging.getLogger(__name__)

# Scopes a role may never hold — session cookie *or* Bearer. W31 S10 only
# narrowed the session path; a child could still mint `write:download` and the
# bearer branch in user_has_scope skipped this map entirely.
_SESSION_SCOPE_DENY = {
    'child': frozenset({'admin', 'write:library', 'write:download'}),
}


def forbidden_scopes_for_role(role: str | None) -> frozenset[str]:
    """Scopes this role must never be granted, including on an API token."""
    return _SESSION_SCOPE_DENY.get(normalize_role(role), frozenset())


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


def is_raw_api_token(raw: str) -> bool:
    """True when *raw* is exactly one generated token string (no labels/junk)."""
    return bool(raw) and bool(_RAW_TOKEN_RE.fullmatch(raw))


def scrub_token_prefix_for_log(raw: str) -> str:
    """Return a log-safe prefix label — never the secret."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return 'none'
    body = raw[len(TOKEN_PREFIX):]
    if '_' not in body:
        return 'malformed'
    prefix, _secret = body.split('_', 1)
    if prefix and re.fullmatch(r'[0-9a-fA-F]{1,16}', prefix):
        return prefix.lower()
    return 'invalid'


def generate_api_token(
    user: User,
    name: str,
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
) -> tuple[ApiToken, str]:
    """Create a token row and return (model, raw_token). Raw shown once.

    ``expires_in_days=None`` keeps the historical behaviour — a token that lives
    until it is revoked. Callers that can afford an expiry should set one.
    """
    denied = forbidden_scopes_for_role(getattr(user, 'role', None))
    cleaned = []
    rejected = []
    for scope in scopes or ['read:library']:
        scope = (scope or '').strip()
        if scope not in VALID_SCOPES or scope in cleaned:
            continue
        if scope in denied:
            rejected.append(scope)
            continue
        cleaned.append(scope)
    if rejected:
        raise ValueError(
            'scopes not allowed for this account: ' + ', '.join(rejected)
        )
    if not cleaned:
        cleaned = ['read:library']

    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f'{TOKEN_PREFIX}{prefix}_{secret}'
    if not is_raw_api_token(raw):
        # Defensive: urlsafe alphabet is already A-Za-z0-9_-, so this should not fire.
        raise RuntimeError('generated api token failed purity check')

    expires_at = None
    if expires_in_days is not None:
        if expires_in_days <= 0:
            raise ValueError('expires_in_days must be positive')
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    row = ApiToken(
        user_id=user.id,
        name=(name or 'API token').strip()[:100],
        token_prefix=prefix,
        token_hash=_hash_secret(secret),
        scopes=cleaned,
        expires_at=expires_at,
    )
    db.session.add(row)
    db.session.commit()
    return row, raw


def revoke_api_token(token_id: int, user_id: int | None = None) -> bool:
    query = select(ApiToken).filter_by(id=token_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    row = db.session.execute(query).scalars().first()
    if not row or row.revoked_at:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    db.session.commit()
    return True


def verify_bearer_token(
    raw: str,
    *,
    touch: bool = True,
) -> tuple[User | None, ApiToken | None]:
    """Verify a raw Bearer secret. Returns (user, token) or (None, None)."""
    user, token, _reason = verify_bearer_token_detailed(raw, touch=touch)
    return user, token


def verify_bearer_token_detailed(
    raw: str,
    *,
    touch: bool = True,
) -> tuple[User | None, ApiToken | None, str | None]:
    """Like verify_bearer_token, but returns a scrubbed failure reason.

    Reasons (never include the secret): malformed | unknown_prefix | bad_hash |
    expired | inactive_user. Success returns reason=None.
    """
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None, None, 'malformed'
    body = raw[len(TOKEN_PREFIX):]
    if '_' not in body:
        return None, None, 'malformed'
    prefix, secret = body.split('_', 1)
    if not prefix or not secret:
        return None, None, 'malformed'

    row = db.session.execute(
        select(ApiToken).filter_by(token_prefix=prefix, revoked_at=None)
    ).scalars().first()
    if not row:
        return None, None, 'unknown_prefix'
    if not secrets.compare_digest(row.token_hash, _hash_secret(secret)):
        return None, None, 'bad_hash'
    # Checked after the hash so an expired token cannot be distinguished from a
    # wrong one without knowing the secret.
    if row.is_expired():
        return None, None, 'expired'

    user = db.session.get(User, row.user_id)
    if not user or not user.state:
        return None, None, 'inactive_user'

    if touch:
        row.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
    return user, row, None


def _log_api_token_auth_failed(reason: str, raw: str) -> None:
    """WARNING line for operators — never logs the secret."""
    prefix = scrub_token_prefix_for_log(raw)
    message = f'api_token_auth_failed reason={reason} prefix={prefix}'
    # Module logger always (pytest-friendly); mirror to Flask app logger for ops.
    _logger.warning(message)
    if has_app_context():
        current_app.logger.warning(message)


@login_manager.request_loader
def load_user_from_request(req):
    """Authenticate via Authorization: Bearer gt_… for API clients."""
    auth = req.headers.get('Authorization', '')
    if not auth.lower().startswith('bearer '):
        g.api_token = None
        return None
    raw = auth.split(' ', 1)[1].strip()
    user, token, reason = verify_bearer_token_detailed(raw)
    if user is None:
        # Bearer presented but rejected — surface for companion connect debugging.
        _log_api_token_auth_failed(reason or 'malformed', raw)
        g.api_token = None
        return None
    g.api_token = token
    return user


def user_has_scope(scope: str) -> bool:
    if not current_user.is_authenticated:
        return False
    role = normalize_role(getattr(current_user, 'role', None))
    # Role deny-list wins over a Bearer token that already carries the scope
    # (tokens minted before this gate, or a companion preset a child should
    # never have been able to create).
    if scope in forbidden_scopes_for_role(role):
        return False
    token = getattr(g, 'api_token', None)
    if token is not None:
        return token.has_scope(scope)

    # Session cookie: admins get every remaining scope; everyone else gets the
    # non-admin set, minus whatever their role is explicitly denied (above).
    if role == 'admin':
        return True
    if scope == 'admin':
        return False
    return True


def require_browser_session(fn):
    """Keep account invitation secrets outside delegated bearer authority."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        # Resolve Flask-Login before inspecting g: request_loader sets api_token.
        if not current_user.is_authenticated:
            return api_error('Unauthorized', code='unauthorized')
        if getattr(g, 'api_token', None) is not None:
            return api_error('Sign in with your site account to manage invites', code='forbidden')
        return fn(*args, **kwargs)

    return wrapped


def require_api_scope(scope: str):
    """Require an authenticated user with the given API scope."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                # api_error, not a bare jsonify: the frontend branches on
                # error_code, and these two were the only auth failures in the
                # tree that shipped without one.
                return api_error('Unauthorized', code='unauthorized')
            if not user_has_scope(scope):
                return api_error(
                    f'Missing scope: {scope}',
                    code='forbidden',
                    detail={'required_scope': scope},
                )
            return fn(*args, **kwargs)

        return wrapped

    return decorator
