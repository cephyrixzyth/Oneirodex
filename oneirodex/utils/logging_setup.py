"""Central logging configuration for Oneirodex.

Before this module the backend had no logging configuration at all: a handful
of files did ``logger = logging.getLogger(__name__)`` and then logged into the
void (no root handler), while hundreds of other call sites used bare ``print``.
Operators on Unraid got an unfiltered, unstructured, un-levelled stream on
stdout and nothing to grep by.

``configure_logging(app)`` is called once, early in ``create_app()``. It wires
stdlib logging through :func:`logging.config.dictConfig`:

* a single console handler on **stdout** (Docker/Unraid capture stdout),
* level from ``ONEIRODEX_LOG_LEVEL`` (default ``INFO``),
* an optional JSON formatter behind ``ONEIRODEX_LOG_JSON=1`` for log shippers,
* a filter that stamps each record with the current request id (from
  ``flask.g``) when emitted inside a request context, ``-`` otherwise.

It is safe to call more than once (the test suite builds many apps); the last
call wins and existing module-level loggers keep working
(``disable_existing_loggers`` is ``False``).
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
import uuid

from flask import g, has_request_context, request

__all__ = ["configure_logging", "RequestIdFilter", "JsonFormatter", "new_request_id"]

DEFAULT_LEVEL = "INFO"
_VALID_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
_TRUTHY = {"1", "true", "yes", "on"}


def new_request_id() -> str:
    """Short correlation id for one request."""
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """Attach ``request_id`` / ``request_method`` / ``request_path`` to records.

    The fields are always present so a format string can reference
    ``%(request_id)s`` without risking ``KeyError`` from outside a request
    context (schedulers, startup, CLI).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        if has_request_context():
            rid = getattr(g, "request_id", None)
            if not rid:
                rid = new_request_id()
                try:
                    g.request_id = rid
                except Exception:  # pragma: no cover - g always writable in ctx
                    pass
            record.request_id = rid
            record.request_method = request.method
            record.request_path = request.path
        else:
            record.request_id = "-"
            record.request_method = "-"
            record.request_path = "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Opt-in via ``ONEIRODEX_LOG_JSON=1``."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        method = getattr(record, "request_method", "-")
        path = getattr(record, "request_path", "-")
        if method != "-":
            payload["method"] = method
        if path != "-":
            payload["path"] = path
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _level() -> str:
    raw = (os.getenv("ONEIRODEX_LOG_LEVEL") or DEFAULT_LEVEL).strip().upper()
    return raw if raw in _VALID_LEVELS else DEFAULT_LEVEL


def _json_enabled() -> bool:
    return (os.getenv("ONEIRODEX_LOG_JSON") or "").strip().lower() in _TRUTHY


def configure_logging(app=None) -> None:
    """Install the console logging config. Idempotent."""
    level = _level()
    formatter = "json" if _json_enabled() else "console"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {
                    "()": "oneirodex.utils.logging_setup.RequestIdFilter",
                },
            },
            "formatters": {
                "console": {
                    "format": (
                        "%(asctime)s %(levelname)-7s %(name)s "
                        "[%(request_id)s] %(message)s"
                    ),
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
                "json": {
                    "()": "oneirodex.utils.logging_setup.JsonFormatter",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": formatter,
                    "filters": ["request_id"],
                    "level": level,
                },
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            # werkzeug's per-request line is useful but noisy at DEBUG; pin it to
            # at least INFO so ONEIRODEX_LOG_LEVEL=DEBUG on our code does not also
            # unleash the dev-server request spam.
            "loggers": {
                "werkzeug": {"level": "INFO"},
                # urllib3 logs every request line (with its query string) at
                # DEBUG. Some provider APIs take a server key as a query
                # parameter (Steam's owned-games call), so DEBUG on our code
                # must not also write those keys to the container log.
                # Never below INFO, never louder than the configured level.
                "urllib3": {"level": "INFO" if level == "DEBUG" else level},
            },
        }
    )

    # The console handler above is a plain ``logging.StreamHandler`` on stdout.
    # On a Windows console running code page cp1252 a record carrying non-Latin-1
    # characters (an emoji in a warning message, say) raises ``UnicodeEncodeError``
    # inside ``StreamHandler.emit`` — the stdlib prints "--- Logging error ---" to
    # stderr and drops the line. Force the underlying stream to UTF-8 with a
    # replacing error handler so those records emit instead of vanishing.
    # ``TextIOWrapper.reconfigure`` exists on Py3.7+; streams that don't support it
    # (pytest capture, some redirects) are left untouched. Linux/Docker already run
    # a UTF-8 locale and are unaffected. This does not touch the JSON path or levels.
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):  # pragma: no cover - stream-dependent
            pass

    if app is not None:
        app.logger.setLevel(level)

        @app.before_request
        def _assign_request_id():  # pragma: no cover - exercised via any request
            if not getattr(g, "request_id", None):
                g.request_id = new_request_id()
