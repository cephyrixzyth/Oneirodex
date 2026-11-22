"""The signed-in member's theme for the current request.

Request auth records it here, so server-side art that follows the member's
theme (stock avatars, per-game placeholder covers) does not depend on a
Flask-Login proxy the served app no longer has.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_REQUEST_THEME: ContextVar[Optional[str]] = ContextVar('oneirodex_request_theme', default=None)


def set_request_theme_from_user(user) -> None:
    theme = None
    try:
        prefs = getattr(user, 'preferences', None) if user is not None else None
        raw = getattr(prefs, 'theme', None) if prefs is not None else None
        if raw:
            from oneirodex.utils.preset_themes import canonical_theme_slug

            theme = canonical_theme_slug(raw)
    except Exception:  # noqa: BLE001 — a missing preference row is just "default"
        theme = None
    _REQUEST_THEME.set(theme)


def request_theme() -> Optional[str]:
    """The current request's member theme slug, or None outside a signed-in request."""
    return _REQUEST_THEME.get()
