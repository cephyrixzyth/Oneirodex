"""Non-template document renderer for the admin design-system styleguide."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from markupsafe import escape

from oneirodex.utils.asset_urls import theme_asset_url
from oneirodex.utils.icon_themes import icon_pack_css_url, icon_pack_previews_css_url
from oneirodex.utils.preset_themes import canonical_theme_slug, era_for_theme


_BODY_PATH = Path(__file__).resolve().parents[1] / "ui" / "styleguide_body.html"
_ATMOSPHERE = '''<div id="od-era-atmosphere" aria-hidden="true">
  <div class="od-era-wall"></div><div class="od-era-scene"></div>
  <div class="od-era-window"></div><div class="od-era-posters"></div>
  <div class="od-era-furnish"></div><div class="od-era-stand"></div>
  <div class="od-era-floor"></div><div class="od-era-lamp"></div>
  <div class="od-era-vignette"></div><div class="od-era-grain"></div>
</div>'''


def _e(value) -> str:
    return str(escape("" if value is None else value))


@lru_cache(maxsize=1)
def _styleguide_body() -> str:
    """Read trusted, checked-in specimen markup without a template runtime."""
    return _BODY_PATH.read_text(encoding="utf-8")


def _flash_html(session_data: dict | None = None) -> str:
    if session_data is None:
        from flask import get_flashed_messages, session

        messages = get_flashed_messages(with_categories=True)
    else:
        messages = session_data.pop('_flashes', [])
        messages = [
            tuple(item) for item in messages
            if isinstance(item, (tuple, list)) and len(item) == 2
        ]
    rows = []
    for category, message in messages:
        alert_category = "danger" if category == "error" else (category or "info")
        game_uuid = ""
        if category == "image-refresh" and session_data and session_data.get("image_refresh_game_uuid"):
            game_uuid = f' data-game-uuid="{_e(session_data.pop("image_refresh_game_uuid", None))}"'
        rows.append(
            f'<div class="alert alert-{_e(alert_category)} alert-dismissible fade show" role="alert"{game_uuid}>'
            f'{_e(message)}'
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>'
            '</div>'
        )
    if not rows:
        return ""
    return '<div class="container-flash-messages">' + "".join(rows) + "</div>"


def _asset_markup(
    theme: str, icon_pack: str, *, static_url_path: str | None = None,
    package_root: str | Path | None = None,
) -> str:
    static_url_path = static_url_path or '/static'
    static = lambda filename: f"{static_url_path.rstrip('/')}/{filename.lstrip('/')}"
    themed = lambda path: theme_asset_url(
        path, theme=theme, static_url_path=static_url_path,
        package_root=package_root,
    )
    parts = [
        f'<script src="{_e(static("vendor/jquery/3.7.1/jquery.min.js"))}"></script>',
        f'<link rel="stylesheet" href="{_e(static("vendor/bootstrap/5.3.2/css/bootstrap.min.css"))}">',
        f'<script src="{_e(static("vendor/bootstrap/5.3.2/js/bootstrap.bundle.min.js"))}"></script>',
        f'<script src="{_e(static("vendor/notify/0.4.2/notify.min.js"))}"></script>',
        f'<script src="{_e(static("js/od_toast.js"))}"></script>',
        f'<script src="{_e(static("js/od_pwa_install.js"))}" defer></script>',
        f'<script src="{_e(static("js/od_dom_actions.js"))}"></script>',
        *(f'<script src="{_e(themed(f"js/{name}"))}"></script>' for name in (
            "csrf-utils.js", "od_modal_stack.js",
        )),
        *(f'<link rel="stylesheet" href="{_e(themed(f"css/{name}"))}">' for name in (
            "od-tokens.css", "od-primitives.css", "od-bootstrap-bridge.css",
            "od-density.css", "od-shell.css", "od-chrome.css", "od-appbar.css",
            "base.css", "modal-components.css", "form-components.css",
            "components.css", "od-loading-motifs.css", "games/library_browser.css",
            "games/game_status.css",
        )),
    ]
    previews = icon_pack_previews_css_url(
        static_url_path=static_url_path, package_root=package_root,
    )
    pack_css = icon_pack_css_url(
        icon_pack, static_url_path=static_url_path, package_root=package_root,
    )
    if previews:
        parts.append(f'<link rel="stylesheet" id="od-icon-pack-previews-css" href="{_e(previews)}">')
    if pack_css:
        parts.append(f'<link rel="stylesheet" id="od-icon-pack-css" href="{_e(pack_css)}">')
    parts.extend((
        f'<link rel="stylesheet" id="od-theme-fonts-css" href="/api/theme/fonts.css">',
        f'<link rel="stylesheet" href="{_e(themed("css/od-era.css"))}">',
        *(f'<script src="{_e(themed(f"js/{name}"))}"></script>' for name in (
            "od_loading_motifs.js", "preferences_modal.js", "popup_menu.js",
            "delete_game_modal.js", "image_refresh_progress.js",
        )),
    ))
    return "".join(parts)


def render_styleguide(
    *, user=None, session_data: dict | None = None, csrf_token: str | None = None,
    static_url_path: str | None = None, package_root: str | Path | None = None,
    as_response: bool = True,
):
    """Build the admin-gated styleguide document without invoking Jinja."""
    if user is None or session_data is None or csrf_token is None:
        from flask import current_app, session
        from flask_login import current_user
        from flask_wtf.csrf import generate_csrf

        user = current_user if user is None else user
        session_data = session if session_data is None else session_data
        csrf_token = generate_csrf() if csrf_token is None else csrf_token
        static_url_path = static_url_path or current_app.static_url_path
        package_root = package_root or current_app.root_path

    prefs = getattr(user, "preferences", None)
    theme = canonical_theme_slug(getattr(prefs, "theme", None) if prefs else None)
    icon_pack = (getattr(prefs, "icon_pack", None) if prefs else None) or "outline"
    csrf = _e(csrf_token)
    static = lambda filename: _e(f"{(static_url_path or '/static').rstrip('/')}/{filename.lstrip('/')}")
    body = _styleguide_body().replace("__CURRENT_THEME__", _e(theme)).replace(
        "__CURRENT_ICON_PACK__", _e(icon_pack)
    )
    html = f'''<!DOCTYPE html>
<html lang="en" data-theme="{_e(theme)}" data-era="{_e(era_for_theme(theme))}" data-icon-pack="{_e(icon_pack)}">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="utf-8">
    <meta name="csrf-token" content="{csrf}">
    <title>Styleguide · Oneirodex</title>
    <link rel="icon" href="{static('icons/favicon.ico')}?v=gt20260805" sizes="any">
    <link rel="icon" type="image/png" sizes="32x32" href="{static('icons/favicon-32.png')}?v=gt20260805">
    <link rel="icon" type="image/png" sizes="48x48" href="{static('icons/favicon-48.png')}?v=gt20260805">
    <link rel="apple-touch-icon" href="{static('icons/apple-touch-icon.png')}?v=gt20260805">
    <link rel="manifest" href="/manifest.webmanifest">
    <meta name="theme-color" content="#0b0f14">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    {_asset_markup(theme, icon_pack, static_url_path=static_url_path, package_root=package_root)}
    <style>
      #content.member-spa-content {{ margin-left: 0; margin-right: 0; width: 100%; max-width: 100%; }}
      .modal.fade {{ z-index: 1065 !important; background-color: transparent; }}
      body.modal-open > .modal-backdrop {{ z-index: 1060 !important; }}
    </style>
</head>
<body>
{_ATMOSPHERE}
<div id="content" class="member-spa-content">{_flash_html(session_data)}{body}</div>
<div id="deleteGameModal" class="modal delete-game-modal" style="display:none; z-index: 15;">
    <div class="modal-content"><span class="close-button">&times;</span><h2>Warning!</h2>
    <p>This action will DELETE THE GAME FROM DISK! This action cannot be undone.</p>
    <form action="/delete_full_game" method="post" id="deleteGameForm">
        <input type="hidden" name="csrf_token" value="{csrf}">
        <input type="hidden" name="game_uuid" id="deleteGameUuid">
        <button type="submit" class="delete-confirm btn btn-danger">Delete Game</button>
        <button type="button" class="delete-cancel btn btn-success">Cancel</button>
    </form></div>
</div>
<div id="preferencesModalContainer"></div>
</body>
</html>'''
    if as_response:
        from flask import current_app

        return current_app.response_class(html, mimetype="text/html")
    return html
