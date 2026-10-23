"""Shared serialization for server notices rendered by the auth React shell."""

from __future__ import annotations

import json
from html import escape


def attach_auth_notices(shell: str, messages) -> str:
    """Attach session notices to the auth mount for React to render in-flow."""
    notices = []
    for category, message in messages:
        role = 'alert' if category in {'error', 'danger'} else 'status'
        notices.append({'role': role, 'message': str(message)})
    if not notices:
        return shell
    payload = escape(json.dumps(notices, ensure_ascii=False), quote=True)
    return shell.replace(
        '<div id="member-auth-root"></div>',
        f'<div id="member-auth-root" data-auth-notices="{payload}"></div>',
        1,
    )
