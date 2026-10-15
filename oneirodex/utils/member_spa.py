"""Non-template HTML shell for the member React SPA."""

from __future__ import annotations

import json

from flask import current_app, get_flashed_messages, request, session, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from markupsafe import escape

from oneirodex import app_version
from oneirodex.utils.asset_urls import dist_asset_url, theme_asset_url
from oneirodex.utils.avatar import avatar_url
from oneirodex.utils.icon_themes import icon_pack_css_url, icon_pack_previews_css_url
from oneirodex.utils.preset_themes import canonical_theme_slug, era_for_theme
from oneirodex.utils.processors import get_global_settings


_ATMOSPHERE = '''<div id="od-era-atmosphere" aria-hidden="true">
  <div class="od-era-wall"></div><div class="od-era-scene"></div>
  <div class="od-era-window"></div><div class="od-era-posters"></div>
  <div class="od-era-furnish"></div><div class="od-era-stand"></div>
  <div class="od-era-floor"></div><div class="od-era-lamp"></div>
  <div class="od-era-vignette"></div><div class="od-era-grain"></div>
</div>'''

_DELETE_GAME_MODAL = '''<div id="deleteGameModal" class="modal delete-game-modal" style="display:none; z-index: 15;">
    <div class="modal-content">
        <span class="close-button">&times;</span>
        <h2>Warning!</h2>
        <p>This action will DELETE THE GAME FROM DISK! This action cannot be undone.</p>
        <form action="/delete_full_game" method="post" id="deleteGameForm">
            <input type="hidden" name="csrf_token" value="{csrf}">
            <input type="hidden" name="game_uuid" id="deleteGameUuid">
            <button type="submit" class="delete-confirm btn btn-danger">Delete Game</button>
            <button type="button" class="delete-cancel btn btn-success">Cancel</button>
        </form>
    </div>
</div>'''


def _e(value) -> str:
    return str(escape('' if value is None else value))


def _asset_markup(theme: str, icon_pack: str) -> str:
    parts = [
        f'<script src="{_e(url_for("static", filename="vendor/jquery/3.7.1/jquery.min.js"))}"></script>',
        f'<link rel="stylesheet" href="{_e(url_for("static", filename="vendor/bootstrap/5.3.2/css/bootstrap.min.css"))}">',
        f'<script src="{_e(url_for("static", filename="vendor/bootstrap/5.3.2/js/bootstrap.bundle.min.js"))}"></script>',
        f'<script src="{_e(url_for("static", filename="vendor/notify/0.4.2/notify.min.js"))}"></script>',
        f'<script src="{_e(url_for("static", filename="js/od_toast.js"))}"></script>',
        f'<script src="{_e(url_for("static", filename="js/od_pwa_install.js"))}" defer></script>',
        f'<script src="{_e(url_for("static", filename="js/od_dom_actions.js"))}"></script>',
        *(f'<script src="{_e(theme_asset_url(f"js/{name}", theme=theme))}"></script>' for name in (
            'csrf-utils.js', 'od_modal_stack.js',
        )),
        *(f'<link rel="stylesheet" href="{_e(theme_asset_url(f"css/{name}", theme=theme))}">' for name in (
            'od-tokens.css', 'od-primitives.css', 'od-bootstrap-bridge.css',
            'od-density.css', 'od-shell.css', 'od-chrome.css', 'od-appbar.css',
            'base.css', 'modal-components.css', 'form-components.css',
            'components.css', 'od-loading-motifs.css', 'games/library_browser.css',
            'games/game_status.css',
        )),
    ]
    previews = icon_pack_previews_css_url()
    pack_css = icon_pack_css_url(icon_pack)
    if previews:
        parts.append(f'<link rel="stylesheet" id="od-icon-pack-previews-css" href="{_e(previews)}">')
    if pack_css:
        parts.append(f'<link rel="stylesheet" id="od-icon-pack-css" href="{_e(pack_css)}">')
    parts.extend((
        f'<link rel="stylesheet" id="od-theme-fonts-css" href="{_e(url_for("apis.theme_fonts_css"))}">',
        f'<link rel="stylesheet" href="{_e(dist_asset_url("member-app/member-app.css"))}">',
        f'<link rel="stylesheet" href="{_e(theme_asset_url("css/od-era.css", theme=theme))}">',
        *(f'<script src="{_e(theme_asset_url(f"js/{name}", theme=theme))}"></script>' for name in (
            'od_loading_motifs.js', 'preferences_modal.js', 'popup_menu.js',
            'delete_game_modal.js', 'image_refresh_progress.js',
        )),
    ))
    return ''.join(parts)


def _member_root(extra: dict) -> str:
    prefs = getattr(current_user, 'preferences', None)
    role = getattr(current_user, 'role', None) or 'user'
    user_id = getattr(current_user, 'id', None) or ''
    settings = get_global_settings()
    app_config = current_app.config
    source_url = app_config.get('ONEIRODEX_SOURCE_URL', '')

    def configured_or_preference(key, preference, default):
        if key in extra:
            return extra[key]
        return (getattr(prefs, preference, None) if prefs else None) or default

    attributes = {
        'tile-size': (getattr(prefs, 'tile_size', None) if prefs else None) or '50',
        'is-admin': str(role == 'admin').lower(),
        'is-librarian': str(role in ('admin', 'librarian')).lower(),
        'role': role,
        'user-id': user_id,
        'show-trailers': str(bool(settings.get('show_trailers', True))).lower(),
        'show-help': str(bool(settings.get('show_help_button', True))).lower(),
        'enable-vr': str(bool(app_config.get('ENABLE_VR_BROWSE'))).lower(),
        'enable-activity': str(bool(app_config.get('ENABLE_ACTIVITY_FEED', True))).lower(),
        'enable-new-chrome': str(bool(app_config.get('ENABLE_NEW_CHROME', True))).lower(),
        'show-play-status': str(bool(settings.get('show_play_status', True))).lower(),
        'show-tile-titles': str(not prefs or getattr(prefs, 'show_tile_titles', True) is not False).lower(),
        'source-url': source_url,
        'app-version': app_version,
        'username': getattr(current_user, 'name', None) or '',
        'avatar': avatar_url(getattr(current_user, 'avatarpath', None)),
        'locale': (getattr(prefs, 'locale', None) if prefs else None) or 'en',
        'per-page': configured_or_preference('user_per_page', 'items_per_page', 20),
        'default-sort': configured_or_preference('user_default_sort', 'default_sort', 'name'),
        'default-sort-order': configured_or_preference('user_default_sort_order', 'default_sort_order', 'asc'),
        'library-count': extra.get('library_count', 0),
        'games-count': extra.get('games_count', 0),
        'scan-has-run': '1' if extra.get('scan_has_run') else '0',
        'unmatched-count': extra.get('unmatched_count', 0),
        'enable-delete-on-disk': str(bool(settings.get('enable_delete_game_on_disk', True))).lower(),
        'current-filters': json.dumps(extra.get('filters', {}), ensure_ascii=False, separators=(',', ':')),
    }
    return '<div id="member-app-root"' + ''.join(
        f' data-{name}="{_e(value)}"' for name, value in attributes.items()
    ) + '></div>'


def _flash_html() -> str:
    rows = []
    for category, message in get_flashed_messages(with_categories=True):
        alert_category = 'danger' if category == 'error' else (category or 'info')
        game_uuid = ''
        if category == 'image-refresh' and session.get('image_refresh_game_uuid'):
            game_uuid = f' data-game-uuid="{_e(session.pop("image_refresh_game_uuid", None))}"'
        rows.append(
            f'<div class="alert alert-{_e(alert_category)} alert-dismissible fade show" role="alert"{game_uuid}>'
            f'{_e(message)}'
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>'
            '</div>'
        )
    if not rows:
        return ''
    return '<div class="container-flash-messages">' + ''.join(rows) + '</div>'


def render_member_spa(**extra):
    """Build the member SPA document without invoking the Jinja renderer."""
    prefs = getattr(current_user, 'preferences', None)
    theme = canonical_theme_slug(getattr(prefs, 'theme', None) if prefs else None)
    icon_pack = (getattr(prefs, 'icon_pack', None) if prefs else None) or 'outline'
    era = era_for_theme(theme)
    asset_markup = _asset_markup(theme, icon_pack)
    root_html = _member_root(extra)
    csrf = _e(generate_csrf())
    favicon = url_for('static', filename='icons/favicon.ico')
    fav32 = url_for('static', filename='icons/favicon-32.png')
    fav48 = url_for('static', filename='icons/favicon-48.png')
    apple = url_for('static', filename='icons/apple-touch-icon.png')
    manifest = url_for('member.app_manifest')
    bundle = _e(dist_asset_url('member-app/member-app.js'))

    html = f'''<!DOCTYPE html>
<html lang="en" data-theme="{_e(theme)}" data-era="{_e(era)}" data-icon-pack="{_e(icon_pack)}">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="utf-8">
    <meta name="csrf-token" content="{csrf}">
    <title>Oneirodex</title>
    <link rel="icon" href="{_e(favicon)}?v=gt20260805" sizes="any">
    <link rel="icon" type="image/png" sizes="32x32" href="{_e(fav32)}?v=gt20260805">
    <link rel="icon" type="image/png" sizes="48x48" href="{_e(fav48)}?v=gt20260805">
    <link rel="apple-touch-icon" href="{_e(apple)}?v=gt20260805">
    <link rel="manifest" href="{_e(manifest)}">
    <meta name="theme-color" content="#0b0f14">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    {asset_markup}
    <style>
      #content.member-spa-content {{ margin-left: 0; margin-right: 0; width: 100%; max-width: 100%; }}
      .modal.fade {{ z-index: 1065 !important; background-color: transparent; }}
      body.modal-open > .modal-backdrop {{ z-index: 1060 !important; }}
    </style>
</head>
<body>
{_ATMOSPHERE}
<div id="content" class="member-spa-content">
{_flash_html()}
{root_html}
</div>
{_DELETE_GAME_MODAL.format(csrf=csrf)}
<div id="preferencesModalContainer"></div>
<script type="module" src="{bundle}"></script>
</body>
</html>'''
    return current_app.response_class(html, mimetype='text/html')
