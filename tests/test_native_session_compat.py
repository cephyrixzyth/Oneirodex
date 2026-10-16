from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from flask import Flask
from flask_wtf.csrf import generate_csrf as flask_generate_csrf
from flask_wtf.csrf import validate_csrf as flask_validate_csrf
from markupsafe import Markup

from oneirodex.runtime_native.session_compat import (
    CsrfTokenError,
    dump_session_cookie,
    encode_remember_cookie,
    generate_csrf_token,
    load_session_cookie,
    validate_csrf_token,
)


SECRET = "migration-test-secret"


def test_remember_cookie_matches_flask_login_codec():
    from flask_login.utils import decode_cookie, encode_cookie

    payload = '7:session-fingerprint'
    encoded = encode_remember_cookie(payload, SECRET)
    assert encoded == encode_cookie(payload, key=SECRET)
    assert decode_cookie(encoded, key=SECRET) == payload


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.secret_key = SECRET
    app.config["SECRET_KEY_FALLBACKS"] = []
    return app


def test_cookie_codec_matches_flask_default_serializer(app: Flask) -> None:
    session = {
        "user_id": 42,
        "roles": ("member", "admin"),
        "bytes": b"session-data",
        "uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        "markup": Markup("<b>safe</b>"),
        "nested": {" t": "ordinary key collision"},
        "created": datetime(2024, 1, 2, tzinfo=timezone.utc),
    }
    with app.app_context():
        reference = app.session_interface.get_signing_serializer(app).dumps(session)
    encoded = dump_session_cookie(session, SECRET)

    assert encoded == reference
    with app.app_context():
        assert app.session_interface.get_signing_serializer(app).loads(encoded) == session
    decoded = load_session_cookie(encoded, SECRET, max_age=31 * 24 * 60 * 60)
    assert decoded == session
    assert load_session_cookie(encoded + "x", SECRET, max_age=3600) == {}
    assert load_session_cookie(None, SECRET, max_age=3600) == {}


def test_cookie_codec_matches_flask_compression_behavior(app: Flask) -> None:
    session = {"large_value": "repeated-session-content-" * 200}
    with app.app_context():
        reference = app.session_interface.get_signing_serializer(app).dumps(session)
    encoded = dump_session_cookie(session, SECRET)
    assert encoded == reference
    assert encoded.startswith(".")
    assert load_session_cookie(encoded, SECRET, max_age=3600) == session


def test_cookie_codec_reads_fallback_signing_keys(app: Flask) -> None:
    app.secret_key = "retired-secret"
    with app.app_context():
        legacy_cookie = app.session_interface.get_signing_serializer(app).dumps(
            {"_user_id": "17", "csrf_token": "session-csrf-value"}
        )
    assert load_session_cookie(
        legacy_cookie,
        SECRET,
        fallback_secret_keys=("retired-secret",),
        max_age=3600,
    ) == {"_user_id": "17", "csrf_token": "session-csrf-value"}
    assert load_session_cookie(
        dump_session_cookie({"v": 1}, "retired-secret"), SECRET, max_age=-1
    ) == {}


def test_csrf_codec_matches_flask_wtf_token_bytes_and_session_key(app: Flask) -> None:
    entropy = b"e" * 64
    expected_session = {}
    native_session = {}
    with app.test_request_context("/"):
        app.config["WTF_CSRF_SECRET_KEY"] = "csrf-only-secret"
        app.config["WTF_CSRF_FIELD_NAME"] = "csrf_token"
        app.secret_key = SECRET
        # Flask-WTF's `generate_csrf` reads os.urandom only for a new value.
        import flask_wtf.csrf

        original = flask_wtf.csrf.os.urandom
        flask_wtf.csrf.os.urandom = lambda size: entropy
        try:
            reference = flask_generate_csrf()
            expected_session.update(dict(__import__("flask").session))
        finally:
            flask_wtf.csrf.os.urandom = original

    token = generate_csrf_token(
        native_session,
        "csrf-only-secret",
        random_bytes=lambda size: entropy,
    )
    assert token == reference
    assert native_session == expected_session
    validate_csrf_token(token, native_session, "csrf-only-secret")

    with app.test_request_context("/"):
        app.config["WTF_CSRF_SECRET_KEY"] = "csrf-only-secret"
        app.config["WTF_CSRF_FIELD_NAME"] = "csrf_token"
        __import__("flask").session.update(expected_session)
        flask_validate_csrf(reference)


@pytest.mark.parametrize(
    ("token", "session", "time_limit", "message"),
    [
        (None, {}, 3600, "The CSRF token is missing."),
        ("present", {}, 3600, "The CSRF session token is missing."),
        ("not-a-token", {"csrf_token": "value"}, 3600, "The CSRF token is invalid."),
    ],
)
def test_csrf_codec_rejects_bad_tokens_with_flask_wtf_reasons(
    token: str | None,
    session: dict[str, str],
    time_limit: int,
    message: str,
) -> None:
    with pytest.raises(CsrfTokenError, match=message):
        validate_csrf_token(token, session, SECRET, time_limit=time_limit)


def test_csrf_codec_rejects_expired_and_mismatched_tokens() -> None:
    session = {"csrf_token": "stored"}
    serializer = __import__("itsdangerous").URLSafeTimedSerializer(
        SECRET, salt="wtf-csrf-token"
    )
    token = serializer.dumps("stored")
    with pytest.raises(CsrfTokenError, match="The CSRF token has expired"):
        validate_csrf_token(token, session, SECRET, time_limit=-1)
    with pytest.raises(CsrfTokenError, match="The CSRF tokens do not match"):
        validate_csrf_token(serializer.dumps("other"), session, SECRET)


def test_module_has_no_flask_or_flask_wtf_imports() -> None:
    module_path = Path(__file__).parents[1] / "oneirodex" / "runtime_native" / "session_compat.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert "flask" not in imported
    assert "flask_wtf" not in imported

