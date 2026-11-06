"""Coverage for oneirodex/utils/logging_setup.py.

The backend had no logging configuration before A0.4. These tests pin the
contract: level from ONEIRODEX_LOG_LEVEL, JSON opt-in, a request-id filter that
is safe outside a request context, and idempotence (the suite builds many apps).
No database needed.
"""

from __future__ import annotations

import json
import logging

import pytest

from oneirodex.utils import logging_setup as ls


@pytest.fixture(autouse=True)
def _restore_logging():
    """Snapshot and restore root logging so these tests don't leak config."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def test_default_level_is_info(monkeypatch):
    monkeypatch.delenv("ONEIRODEX_LOG_LEVEL", raising=False)
    assert ls._level() == "INFO"


def test_level_from_env_is_honoured(monkeypatch):
    monkeypatch.setenv("ONEIRODEX_LOG_LEVEL", "debug")
    assert ls._level() == "DEBUG"


def test_bogus_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("ONEIRODEX_LOG_LEVEL", "chatty")
    assert ls._level() == "INFO"


def test_configure_logging_installs_one_console_handler(monkeypatch):
    monkeypatch.delenv("ONEIRODEX_LOG_JSON", raising=False)
    monkeypatch.setenv("ONEIRODEX_LOG_LEVEL", "WARNING")
    ls.configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert any(
        isinstance(item, ls.UvicornAccessSecretFilter)
        for item in logging.getLogger("uvicorn.access").filters
    )


def test_configure_logging_is_idempotent(monkeypatch):
    monkeypatch.setenv("ONEIRODEX_LOG_LEVEL", "INFO")
    ls.configure_logging()
    ls.configure_logging()
    assert len(logging.getLogger().handlers) == 1


def test_uvicorn_access_filter_installation_is_idempotent():
    access_logger = logging.getLogger("uvicorn.access")
    saved_filters = access_logger.filters[:]
    access_logger.filters[:] = [
        item for item in access_logger.filters
        if not isinstance(item, ls.UvicornAccessSecretFilter)
    ]
    try:
        ls.install_uvicorn_access_secret_filter()
        ls.install_uvicorn_access_secret_filter()
        assert sum(
            isinstance(item, ls.UvicornAccessSecretFilter)
            for item in access_logger.filters
        ) == 1
    finally:
        access_logger.filters[:] = saved_filters


def test_request_id_filter_outside_request_context_uses_dash():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", (), None)
    assert ls.RequestIdFilter().filter(rec) is True
    assert rec.request_id == "-"
    assert rec.request_method == "-"
    assert rec.request_path == "-"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/reset_password/raw-secret-token", "/reset_password/[redacted]"),
        ("/api/auth/confirm/one-time-code", "/api/auth/confirm/[redacted]"),
        ("/register?token=invite-secret", "/register?token=%5Bredacted%5D"),
    ],
)
def test_uvicorn_access_filter_redacts_auth_tokens(path, expected):
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", path, "1.1", 200), None,
    )

    assert ls.UvicornAccessSecretFilter().filter(rec) is True
    assert rec.args[2] == expected
    assert "raw-secret-token" not in rec.getMessage()
    assert "one-time-code" not in rec.getMessage()
    assert "invite-secret" not in rec.getMessage()


def test_request_id_filter_inside_request_context_stamps_id():
    from flask import Flask, g

    app = Flask(__name__)
    with app.test_request_context("/probe", method="POST"):
        g.request_id = "abc123"
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", (), None)
        ls.RequestIdFilter().filter(rec)
        assert rec.request_id == "abc123"
        assert rec.request_method == "POST"
        assert rec.request_path == "/probe"


def test_request_id_filter_redacts_reset_token_path():
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/reset_password/private-reset-token"):
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", (), None)
        ls.RequestIdFilter().filter(rec)

    assert rec.request_path == "/reset_password/[redacted]"


def test_request_id_filter_mints_an_id_when_g_has_none():
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/x"):
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", (), None)
        ls.RequestIdFilter().filter(rec)
        assert rec.request_id != "-"
        assert len(rec.request_id) == 12


def test_json_formatter_emits_one_object_per_line():
    rec = logging.LogRecord("mylog", logging.ERROR, __file__, 7, "boom %s", ("x",), None)
    rec.request_id = "rid42"
    line = ls.JsonFormatter().format(rec)
    obj = json.loads(line)
    assert obj["level"] == "ERROR"
    assert obj["logger"] == "mylog"
    assert obj["msg"] == "boom x"
    assert obj["request_id"] == "rid42"
    assert "\n" not in line


def test_json_formatter_includes_traceback_when_present():
    try:
        raise ValueError("nope")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "l", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    obj = json.loads(ls.JsonFormatter().format(rec))
    assert "ValueError: nope" in obj["exc"]


def test_json_mode_selected_by_env(monkeypatch):
    monkeypatch.setenv("ONEIRODEX_LOG_JSON", "1")
    assert ls._json_enabled() is True
    monkeypatch.setenv("ONEIRODEX_LOG_JSON", "0")
    assert ls._json_enabled() is False
