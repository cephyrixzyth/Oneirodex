"""Framework-independent codec for Flask's signed session and CSRF tokens.

The format in this module mirrors Flask 3.1's default
``SecureCookieSessionInterface`` and Flask-WTF 1.3's CSRF helpers. It is a
temporary migration boundary: callers pass session mappings and configuration
values explicitly, so this module does not depend on Flask request globals.
"""
from __future__ import annotations

import base64
import dataclasses
import decimal
import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import date, datetime
from typing import Any

from itsdangerous import BadData, BadSignature, SignatureExpired, URLSafeTimedSerializer
from markupsafe import Markup
from werkzeug.http import http_date, parse_date


SESSION_COOKIE_SALT = "cookie-session"
CSRF_TOKEN_SALT = "wtf-csrf-token"
DEFAULT_CSRF_FIELD_NAME = "csrf_token"
DEFAULT_CSRF_TIME_LIMIT = 3600


def encode_remember_cookie(payload: str, secret_key: str | bytes) -> str:
    """Match Flask-Login's signed remember-cookie wire format."""
    key = secret_key.encode('utf-8') if isinstance(secret_key, str) else secret_key
    digest = hmac.new(key, payload.encode('utf-8'), hashlib.sha512).hexdigest()
    return f'{payload}|{digest}'


def _json_default(value: Any) -> Any:
    """Match Flask's default JSON provider for values outside tagged JSON."""
    if isinstance(value, date):
        return http_date(value)
    if isinstance(value, (decimal.Decimal, uuid.UUID)):
        return str(value)
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "__html__"):
        return str(value.__html__())
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class _TaggedJSON:
    """Flask's default tagged JSON representation without importing Flask."""

    _tag_keys = (" di", " t", " b", " m", " u", " d")

    def dumps(self, value: Any) -> str:
        return json.dumps(
            self._tag(value),
            default=_json_default,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def loads(self, value: str | bytes) -> Any:
        return self._untag(json.loads(value))

    def _tag(self, value: Any) -> Any:
        if isinstance(value, dict):
            if len(value) == 1 and next(iter(value)) in self._tag_keys:
                key = next(iter(value))
                return {" di": {f"{key}__": self._tag(value[key])}}
            return {key: self._tag(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return {" t": [self._tag(item) for item in value]}
        if isinstance(value, list):
            return [self._tag(item) for item in value]
        if isinstance(value, bytes):
            return {" b": base64.b64encode(value).decode("ascii")}
        if callable(getattr(value, "__html__", None)):
            return {" m": str(value.__html__())}
        if isinstance(value, uuid.UUID):
            return {" u": value.hex}
        if isinstance(value, datetime):
            return {" d": http_date(value)}
        return value

    def _untag(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._untag(item) for item in value]
        if not isinstance(value, dict):
            return value
        value = {key: self._untag(item) for key, item in value.items()}
        if len(value) != 1:
            return value
        key, tagged = next(iter(value.items()))
        if key == " di" and isinstance(tagged, dict) and len(tagged) == 1:
            escaped_key, item = next(iter(tagged.items()))
            return {escaped_key[:-2]: item}
        if key == " t":
            return tuple(tagged)
        if key == " b":
            return base64.b64decode(tagged)
        if key == " m":
            return Markup(tagged)
        if key == " u":
            return uuid.UUID(tagged)
        if key == " d":
            return parse_date(tagged)
        return value


_SESSION_JSON = _TaggedJSON()


def _session_serializer(secret_keys: Sequence[str | bytes]) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        list(secret_keys),
        salt=SESSION_COOKIE_SALT,
        serializer=_SESSION_JSON,
        signer_kwargs={
            "key_derivation": "hmac",
            "digest_method": hashlib.sha1,
        },
    )


def dump_session_cookie(
    session_data: Mapping[str, Any],
    secret_key: str | bytes,
    *,
    fallback_secret_keys: Sequence[str | bytes] = (),
) -> str:
    """Serialize and sign session data using Flask's default cookie format."""
    return _session_serializer((*fallback_secret_keys, secret_key)).dumps(dict(session_data))


def load_session_cookie(
    cookie_value: str | None,
    secret_key: str | bytes,
    *,
    max_age: int,
    fallback_secret_keys: Sequence[str | bytes] = (),
) -> dict[str, Any]:
    """Load a Flask session cookie; absent or invalid signatures yield `{}`.

    Flask also treats a bad signature or expired cookie as an empty session.
    No signature or cookie content is included in exceptions or logs.
    """
    if not cookie_value:
        return {}
    try:
        data = _session_serializer((*fallback_secret_keys, secret_key)).loads(
            cookie_value, max_age=max_age
        )
        return dict(data)
    except BadSignature:
        return {}


def generate_csrf_token(
    session_data: MutableMapping[str, Any],
    secret_key: str | bytes,
    *,
    field_name: str = DEFAULT_CSRF_FIELD_NAME,
    random_bytes=os.urandom,
) -> str:
    """Generate a Flask-WTF-compatible timed token and persist its session key."""
    serializer = URLSafeTimedSerializer(secret_key, salt=CSRF_TOKEN_SALT)
    if field_name not in session_data:
        session_data[field_name] = hashlib.sha1(random_bytes(64)).hexdigest()
    try:
        token = serializer.dumps(session_data[field_name])
    except TypeError:
        session_data[field_name] = hashlib.sha1(random_bytes(64)).hexdigest()
        token = serializer.dumps(session_data[field_name])
    return token


class CsrfTokenError(ValueError):
    """CSRF validation failure with Flask-WTF-compatible reason strings."""


def validate_csrf_token(
    token: str | None,
    session_data: Mapping[str, Any],
    secret_key: str | bytes,
    *,
    field_name: str = DEFAULT_CSRF_FIELD_NAME,
    time_limit: int | None = DEFAULT_CSRF_TIME_LIMIT,
) -> None:
    """Validate token expiry, signature, session binding, and constant-time match."""
    if not token:
        raise CsrfTokenError("The CSRF token is missing.")
    if field_name not in session_data:
        raise CsrfTokenError("The CSRF session token is missing.")
    serializer = URLSafeTimedSerializer(secret_key, salt=CSRF_TOKEN_SALT)
    try:
        decoded = serializer.loads(token, max_age=time_limit)
    except SignatureExpired:
        raise CsrfTokenError("The CSRF token has expired.") from None
    except BadData:
        raise CsrfTokenError("The CSRF token is invalid.") from None
    if not hmac.compare_digest(session_data[field_name], decoded):
        raise CsrfTokenError("The CSRF tokens do not match.")

