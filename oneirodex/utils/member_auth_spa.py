"""Serve the built React authentication/setup shell without Jinja."""

from __future__ import annotations

from html import escape
from pathlib import Path

from flask import abort, current_app, get_flashed_messages


def render_member_auth_spa():
    """Return the static auth document, preserving queued Flask flash notices."""
    shell_path = Path(current_app.static_folder or '') / 'dist' / 'member-auth' / 'auth.html'
    try:
        shell = shell_path.read_text(encoding='utf-8')
    except OSError:
        current_app.logger.error('Built member authentication shell is unavailable')
        abort(503)
    if shell.count('id="member-auth-root"') != 1 or '</body>' not in shell:
        current_app.logger.error('Built member authentication shell failed validation')
        abort(503)

    notices = []
    for category, message in get_flashed_messages(with_categories=True):
        role = 'alert' if category in {'error', 'danger'} else 'status'
        notices.append(
            f'<p class="auth-pilot__message" role="{role}">'
            f'{escape(str(message), quote=True)}</p>'
        )
    if notices:
        shell = shell.replace(
            '<div id="member-auth-root"></div>',
            '<div class="auth-pilot__notices" aria-label="Messages">'
            + ''.join(notices)
            + '</div><div id="member-auth-root"></div>',
            1,
        )
    response = current_app.response_class(shell, mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie'
    return response
