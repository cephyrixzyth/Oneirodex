"""Small, escaped HTML email bodies with no template-engine dependency."""

from __future__ import annotations

from html import escape
from typing import Any


def _e(value: Any) -> str:
    """Escape dynamic text and attribute values before inserting them in HTML."""
    return escape('' if value is None else str(value), quote=True)


def render_daily_digest(items: list[dict[str, Any]], inbox_link: str | None) -> str:
    count = len(items)
    rows: list[str] = []
    for item in items:
        body = item.get('body') or ''
        link = item.get('link') or ''
        row = f'<li>\n      <strong>{_e(item.get("title", ""))}</strong>'
        if body:
            row += f'\n      — {_e(body)}'
        if link:
            row += f'\n      — <a href="{_e(link)}">Open</a>'
        rows.append(row + '\n    </li>')
    inbox = (
        f'\n  <p><a href="{_e(inbox_link)}">Open notifications in Oneirodex</a></p>'
        if inbox_link
        else ''
    )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
        '  <title>Oneirodex digest</title>\n</head>\n'
        '<body style="font-family: system-ui, sans-serif; line-height: 1.45; color: #1a1a1a;">\n'
        f'  <p>You have <strong>{count}</strong> unread notification'
        f'{"s" if count != 1 else ""}.</p>\n  <ul>\n'
        + '\n'.join(rows)
        + '\n  </ul>'
        + inbox
        + '\n  <p style="font-size: 0.9em; color: #555;">\n'
        '    You opted in to a daily email digest (mentions, DMs, free games).\n'
        '    Turn this off under More → Notifications.\n  </p>\n</body>\n</html>'
    )


def render_social_notification(
    *, title: str, body: str | None, link: str | None,
) -> str:
    body_markup = f'\n  <p>{_e(body)}</p>' if body else ''
    link_markup = (
        f'\n  <p><a href="{_e(link)}">Open in Oneirodex</a></p>' if link else ''
    )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
        f'  <title>{_e(title)}</title>\n</head>\n'
        '<body style="font-family: system-ui, sans-serif; line-height: 1.45; color: #1a1a1a;">\n'
        f'  <p><strong>{_e(title)}</strong></p>'
        + body_markup
        + link_markup
        + '\n  <p style="font-size: 0.9em; color: #555;">\n'
        '    You opted in to email for mentions and direct messages.\n'
        '    Turn this off under More → Notifications.\n  </p>\n</body>\n</html>'
    )


def render_invite_email(invite_url: str) -> str:
    return f'''<!DOCTYPE html>
<html>
<head>
    <title>Oneirodex !</title>
    <style>
        body {{
            background-color: #f3f4f6;
            color: #333;
            font-family: 'Courier New', Courier, monospace;
            padding: 20px;
        }}
        .container {{
            background-color: #fff;
            border: 1px solid #ddd;
            padding: 20px;
            border-radius: 10px;
            max-width: 600px;
            margin: 20px auto;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h2 {{ color: #007bff; }}
        a {{
            background-color: #007bff;
            color: #ffffff;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
        }}
        p {{ margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Welcome to Oneirodex!</h2>
        <p>Hello,</p>
        <p>You've been invited to join Oneirodex, a platform for sharing games. To complete your registration and get started, please use the link below:</p>
        <a href="{_e(invite_url)}" style="display: inline-block; margin: 20px 0;">Complete Your Registration</a>
        <p>Please note that this invitation link will expire after 48 hours. If you don't complete your registration by then, you'll need to request a new invitation.</p>
        <p>Best regards,<br>The Oneirodex Team</p>
    </div>
</body>
</html>'''
