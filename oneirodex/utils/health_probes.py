"""Liveness and readiness probe helpers for Docker / Unraid."""

from __future__ import annotations

from typing import Any

import logging

from flask import current_app
from sqlalchemy import text

from oneirodex import app_version, db
from oneirodex.init_manager import is_initialization_complete


def build_liveness() -> dict[str, Any]:
    """Process is up — no dependency checks."""
    return {
        'status': 'ok',
        'probe': 'liveness',
        'version': app_version,
    }


def check_database() -> tuple[bool, str | None]:
    """Return (ok, error_message)."""
    try:
        db.session.execute(text('SELECT 1'))
        return True, None
    except Exception as exc:  # noqa: BLE001 — surface any DB failure to probes
        # The probe is unauthenticated: the class name only, never the driver's
        # message, which names the database host, port, user and database.
        logging.getLogger(__name__).warning('Readiness probe: database check failed: %s', exc)
        return False, type(exc).__name__


def build_readiness() -> tuple[dict[str, Any], int]:
    """
    Ready when the database answers and startup init is marked complete.

    In Flask TESTING, init env may be unset — DB success alone is enough.
    """
    db_ok, db_error = check_database()
    testing = bool(current_app.config.get('TESTING'))
    init_ok = is_initialization_complete() or testing

    payload: dict[str, Any] = {
        'status': 'ok' if (db_ok and init_ok) else 'not_ready',
        'probe': 'readiness',
        'version': app_version,
        'checks': {
            'database': {'ok': db_ok, 'error': db_error},
            'initialization': {
                'ok': init_ok,
                'complete': is_initialization_complete(),
                'testing_bypass': testing and not is_initialization_complete(),
            },
        },
    }
    return payload, (200 if payload['status'] == 'ok' else 503)
