"""Non-template HTML shell renderer for React-owned admin pages."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from flask import current_app, get_flashed_messages, session, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from markupsafe import escape

from oneirodex.runtime_native.admin_pilot import legacy_chrome_fields
from oneirodex.utils.asset_urls import dist_asset_url


_ATMOSPHERE = '''<div id="od-era-atmosphere" aria-hidden="true">
  <div class="od-era-wall"></div><div class="od-era-scene"></div>
  <div class="od-era-window"></div><div class="od-era-posters"></div>
  <div class="od-era-furnish"></div><div class="od-era-stand"></div>
  <div class="od-era-floor"></div><div class="od-era-lamp"></div>
  <div class="od-era-vignette"></div><div class="od-era-grain"></div>
</div>'''


def _e(value) -> str:
    return str(escape("" if value is None else value))


def _flashes() -> str:
    rows = []
    for category, message in get_flashed_messages(with_categories=True):
        alert_category = "danger" if category == "error" else (category or "info")
        game_uuid = ""
        if category == "image-refresh" and session.get("image_refresh_game_uuid"):
            game_uuid = f' data-game-uuid="{_e(session.pop("image_refresh_game_uuid", None))}"'
        rows.append(
            f'<div class="alert alert-{_e(alert_category)} alert-dismissible fade show" role="alert"{game_uuid}>'
            f'{_e(message)}'
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>'
            '</div>'
        )
    if not rows:
        return ""
    return '<div class="container-flash-messages">' + "".join(rows) + "</div>"


def _stylesheet_tag(href: str) -> str:
    path = urlparse(href).path
    stylesheet_id = ""
    if path.endswith("/icon-themes/previews.css"):
        stylesheet_id = ' id="od-icon-pack-previews-css"'
    elif "/icon-themes/" in path and path.endswith("/pack.css"):
        stylesheet_id = ' id="od-icon-pack-css"'
    elif path.endswith("/theme_fonts.css"):
        stylesheet_id = ' id="od-theme-fonts-css"'
    return f'<link rel="stylesheet"{stylesheet_id} href="{_e(href)}">'


def render_admin_spa(*, title: str):
    """Emit the shared admin document for a route whose body belongs to React."""
    fields = legacy_chrome_fields(current_user)
    theme = fields["theme"]
    csrf = _e(generate_csrf())
    chrome_marker = ' data-chrome="v2"' if current_app.config.get("ENABLE_NEW_CHROME", True) else ""
    scripts = theme["scripts"]
    initial_scripts = scripts[:6]
    csrf_script = scripts[6:7]
    early_theme_scripts = scripts[7:9]
    late_theme_scripts = scripts[9:]
    stylesheets = theme["stylesheets"]
    stylesheets.insert(-1, dist_asset_url("admin-app/admin-app.css"))
    prefs_json = json.dumps(fields["preferences_url"]).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = f'''<!DOCTYPE html>
<html lang="en" data-theme="{_e(theme['name'])}" data-era="{_e(theme['era'])}" data-icon-pack="{_e(theme['icon_pack'])}"{chrome_marker}>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="utf-8">
    <meta name="csrf-token" content="{csrf}">
    <title>{_e(title)}</title>
    <link rel="icon" href="{_e(url_for('static', filename='icons/favicon.ico'))}?v=gt20260805" sizes="any">
    <link rel="icon" type="image/png" sizes="32x32" href="{_e(url_for('static', filename='icons/favicon-32.png'))}?v=gt20260805">
    <link rel="icon" type="image/png" sizes="48x48" href="{_e(url_for('static', filename='icons/favicon-48.png'))}?v=gt20260805">
    <link rel="apple-touch-icon" href="{_e(url_for('static', filename='icons/apple-touch-icon.png'))}?v=gt20260805">
    <link rel="manifest" href="{_e(url_for('member.app_manifest'))}">
    <meta name="theme-color" content="#0b0f14">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    {''.join(f'<script src="{_e(src)}"{" defer" if src.endswith("od_pwa_install.js") else ""}></script>' for src in initial_scripts)}
    {''.join(f'<script src="{_e(src)}"></script>' for src in csrf_script)}
    {''.join(_stylesheet_tag(href) for href in stylesheets)}
    {''.join(f'<script src="{_e(src)}"></script>' for src in early_theme_scripts)}
    <style>
      body.admin-shell .modal.fade, body.admin-spa .modal.fade {{ z-index: 1065 !important; background-color: transparent; }}
      body.admin-shell .modal.fade .modal-dialog, body.admin-spa .modal.fade .modal-dialog {{ pointer-events: auto; z-index: 1; }}
      body.admin-shell.modal-open > .modal-backdrop, body.admin-spa.modal-open > .modal-backdrop {{ z-index: 1060 !important; }}
    </style>
    {''.join(f'<script src="{_e(src)}"></script>' for src in late_theme_scripts)}
</head>
<body class="admin-shell admin-spa">
{_ATMOSPHERE}
<div id="admin-app-root" data-admin-chrome="1" data-username="{_e(getattr(current_user, 'name', None) or '')}" data-avatar="{_e(fields['avatar_url'])}" data-admin-render="spa"></div>
<div id="admin-legacy-content" class="od-admin-legacy">{_flashes()}</div>
<div id="preferencesModalContainer"></div>
<script type="application/json" id="od-prefs-panel-url">{prefs_json}</script>
<script type="module" src="{_e(dist_asset_url('admin-app/admin-app.js'))}"></script>
</body>
</html>'''
    return current_app.response_class(html, mimetype="text/html")
