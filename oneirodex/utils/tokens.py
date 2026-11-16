"""Signed-token helpers.

``get_serializer`` was defined (identically) in both ``oneirodex/routes.py`` and
``oneirodex/routes_login.py``. Wave A2.1f retired the ``'main'`` blueprint, so the
canonical copy now lives here and ``routes_login`` imports it.
"""

import hashlib
import hmac

from itsdangerous import URLSafeTimedSerializer
from oneirodex.utils.runtime_config import get_runtime_config


def get_serializer() -> URLSafeTimedSerializer:
    """Return a ``URLSafeTimedSerializer`` keyed by the active app's SECRET_KEY."""
    return URLSafeTimedSerializer(get_runtime_config()['SECRET_KEY'])


def password_reset_token_digest(token: str) -> str:
    """Return the database lookup value for a password-reset bearer token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def email_verification_token_digest(token: str) -> str:
    """Return the database lookup value for a mailbox-confirmation bearer token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def email_verification_token_matches(stored: str | None, token: str) -> bool:
    """Accept hashed tokens and short-lived raw tokens from pre-migration rows.

    A missing value preserves the historical signed-token behavior for older
    unverified rows that predate persisted confirmation tokens.
    """
    if not stored:
        return True
    return (
        hmac.compare_digest(stored, email_verification_token_digest(token))
        or hmac.compare_digest(stored, token)
    )
