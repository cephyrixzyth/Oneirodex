"""Native FastAPI shell routes for the React member application.

The page handlers preserve the legacy signed-session bootstrap while keeping
asset and HTML construction independent from Flask request globals.
"""
from __future__ import annotations

import json
import html
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote
import uuid

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse, Response

from oneirodex.runtime_native.request_auth import request_auth_context


STATIC_MEMBER_TITLES = {
    '/discover': 'Discover',
    '/library': 'Library',
    '/systems': 'Systems',
    '/systems/completion': 'Set completion',
    '/systems/catalog': 'Licensed catalog',
    '/ways-to-play': 'Ways to Play',
    '/collections': 'Collections',
    '/news': 'News',
    '/wishlist': 'Wishlist',
    '/downloads': 'Downloads',
    '/playromtest': 'Discover',
    '/updates': 'Updates',
    '/acquire': 'Acquire',
    '/playtime': 'Playtime',
    '/activity': 'Activity',
    '/social-companion': 'Friends',
    '/chat': 'Chat',
    '/notifications': 'Notifications',
    '/tokens': 'Tokens',
    '/report': 'Report issue',
    '/big-picture': 'Big Picture',
    '/ownership': 'Store Ownership',
    '/welcome': 'Set up your stores',
    '/calendar': 'Release calendar',
    '/vr': 'VR Library',
    '/help': 'Help',
    '/favorites': '',
    '/trailers': 'Trailers',
}


def member_shell_route(path: str) -> bool:
    """Return true only for routes whose legacy handler returned the member shell."""
    return (
        path in STATIC_MEMBER_TITLES
        or re.fullmatch(r'/game_details/[^/]+', path) is not None
        or re.fullmatch(r'/discover/(?:zone/[^/]+|hub/genre/.+|[^/]+)', path) is not None
        or re.fullmatch(r'/collections/[^/]+', path) is not None
        or re.fullmatch(r'/members/[0-9]+', path) is not None
    )


def _e(value) -> str:
    return html.escape('' if value is None else str(value), quote=True)


def _static_path(static_url_path: str, filename: str) -> str:
    return f"{static_url_path.rstrip('/')}/{quote(filename.lstrip('/'), safe='/')}"


def _shell_settings(row) -> dict:
    values = getattr(row, 'settings', None) if row else None
    values = values if isinstance(values, dict) else {}
    return {
        'show_trailers': values.get('showTrailers', True),
        'show_help_button': values.get('showHelpButton', True),
        'show_play_status': values.get('showPlayStatus', True),
        'enable_delete_game_on_disk': values.get('enableDeleteGameOnDisk', True),
    }


def _legacy_feature_enabled(config, key: str, default: str) -> bool:
    """Parse member-page feature flags with the legacy route's string rules."""
    return str(config.get(key, default)).lower() in {'1', 'true', 'yes', 'on'}


def _flashes(session_data: dict) -> str:
    rows = []
    messages = session_data.pop('_flashes', [])
    for pair in messages if isinstance(messages, list) else []:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        category, message = pair
        alert = 'danger' if category == 'error' else (category or 'info')
        game_uuid = ''
        if category == 'image-refresh' and session_data.get('image_refresh_game_uuid'):
            game_uuid = f' data-game-uuid="{_e(session_data.pop("image_refresh_game_uuid", None))}"'
        rows.append(
            f'<div class="alert alert-{_e(alert)} alert-dismissible fade show" role="alert"{game_uuid}>'
            f'{_e(message)}'
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>'
            '</div>'
        )
    return '<div class="container-flash-messages">' + ''.join(rows) + '</div>' if rows else ''


def _asset_markup(theme: str, icon_pack: str, static_url_path: str, package_root: str) -> str:
    from oneirodex.utils.asset_urls import dist_asset_url, theme_asset_url
    from oneirodex.utils.icon_themes import icon_pack_css_url, icon_pack_previews_css_url

    static = lambda filename: _static_path(static_url_path, filename)
    theme_asset = lambda filename: theme_asset_url(
        filename, theme=theme, static_url_path=static_url_path,
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
    ]
    parts.extend(
        f'<script src="{_e(theme_asset(f"js/{name}"))}"></script>'
        for name in ('csrf-utils.js', 'od_modal_stack.js')
    )
    parts.extend(
        f'<link rel="stylesheet" href="{_e(theme_asset(f"css/{name}"))}">'
        for name in (
            'od-tokens.css', 'od-primitives.css', 'od-bootstrap-bridge.css',
            'od-density.css', 'od-shell.css', 'od-chrome.css', 'od-appbar.css',
            'base.css', 'modal-components.css', 'form-components.css',
            'components.css', 'od-loading-motifs.css', 'games/library_browser.css',
            'games/game_status.css',
        )
    )
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
        '<link rel="stylesheet" id="od-theme-fonts-css" href="/api/theme/fonts.css">',
        f'<link rel="stylesheet" href="{_e(dist_asset_url("member-app/member-app.css", static_url_path=static_url_path))}">',
        f'<link rel="stylesheet" href="{_e(theme_asset("css/od-era.css"))}">',
    ))
    parts.extend(
        f'<script src="{_e(theme_asset(f"js/{name}"))}"></script>'
        for name in (
            'od_loading_motifs.js', 'preferences_modal.js', 'popup_menu.js',
            'delete_game_modal.js', 'image_refresh_progress.js',
        )
    )
    return ''.join(parts)


def _member_root(user, settings: dict, app_config, extra: dict, static_url_path: str, package_root: str) -> str:
    from oneirodex.utils.avatar import avatar_url
    from oneirodex.utils.preset_themes import canonical_theme_slug

    prefs = getattr(user, 'preferences', None)
    role = getattr(user, 'role', None) or 'user'
    user_id = getattr(user, 'id', None) or ''
    source_url = app_config.get('ONEIRODEX_SOURCE_URL', '')

    def configured_or_preference(key, preference, default):
        if key in extra:
            return extra[key]
        return (getattr(prefs, preference, None) if prefs else None) or default

    theme = canonical_theme_slug(getattr(prefs, 'theme', None) if prefs else None)
    avatar = avatar_url(
        getattr(user, 'avatarpath', None), theme=theme,
        static_url=lambda filename: _static_path(static_url_path, filename),
        package_root=package_root,
    )
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
        'app-version': _app_version(package_root),
        'username': getattr(user, 'name', None) or '',
        'avatar': avatar,
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


def _app_version(package_root: str) -> str:
    try:
        return (Path(package_root).resolve().parent / 'VERSION').read_text(encoding='utf-8').strip() or '1.1.9'
    except OSError:
        return '1.1.9'


def render_member_shell(user, app_config, settings, session_data, csrf_token, *, path, extra=None):
    """Render the member app document from explicit request data and config."""
    from oneirodex.utils.preset_themes import canonical_theme_slug, era_for_theme

    extra = dict(extra or {})
    prefs = getattr(user, 'preferences', None)
    theme = canonical_theme_slug(getattr(prefs, 'theme', None) if prefs else None)
    icon_pack = (getattr(prefs, 'icon_pack', None) if prefs else None) or 'outline'
    static_url_path = getattr(app_config, 'static_url_path', None) or '/static'
    package_root = str(Path(getattr(app_config, 'root_path', Path(__file__).resolve().parents[1])))
    asset_markup = _asset_markup(theme, icon_pack, static_url_path, package_root)
    root_html = _member_root(user, settings, app_config.config, extra, static_url_path, package_root)
    csrf = _e(csrf_token)
    static = lambda filename: _static_path(static_url_path, filename)
    favicon = static('icons/favicon.ico')
    fav32 = static('icons/favicon-32.png')
    fav48 = static('icons/favicon-48.png')
    apple = static('icons/apple-touch-icon.png')
    manifest = '/manifest.webmanifest'
    from oneirodex.utils.asset_urls import dist_asset_url

    bundle = _e(dist_asset_url(
        'member-app/member-app.js', static_url_path=static_url_path,
        package_root=package_root,
    ))
    flash_html = _flashes(session_data)

    html = f'''<!DOCTYPE html>
<html lang="en" data-theme="{_e(theme)}" data-era="{_e(era_for_theme(theme))}" data-icon-pack="{_e(icon_pack)}">
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
<div id="od-era-atmosphere" aria-hidden="true"><div class="od-era-wall"></div><div class="od-era-scene"></div><div class="od-era-window"></div><div class="od-era-posters"></div><div class="od-era-furnish"></div><div class="od-era-stand"></div><div class="od-era-floor"></div><div class="od-era-lamp"></div><div class="od-era-vignette"></div><div class="od-era-grain"></div></div>
<div id="content" class="member-spa-content">{flash_html}{root_html}</div>
<div id="deleteGameModal" class="modal delete-game-modal" style="display:none; z-index: 15;"><div class="modal-content"><span class="close-button">&times;</span><h2>Warning!</h2><p>This action will DELETE THE GAME FROM DISK! This action cannot be undone.</p><form action="/delete_full_game" method="post" id="deleteGameForm"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="game_uuid" id="deleteGameUuid"><button type="submit" class="delete-confirm btn btn-danger">Delete Game</button><button type="button" class="delete-cancel btn btn-success">Cancel</button></form></div></div>
<div id="preferencesModalContainer"></div>
<script type="module" src="{bundle}"></script>
</body>
</html>'''
    return html


def create_member_shell_router(flask_app, *, database_scope):
    """Build authenticated GET/HEAD member-page routes on a FastAPI router."""
    router = APIRouter()
    from oneirodex.runtime_native.admin_pilot import _native_auth_backend

    find_user, find_token, commit_token_touch = _native_auth_backend(flask_app)
    login_manager = getattr(flask_app, 'login_manager', None)

    @router.api_route('/{member_path:path}', methods=['GET', 'HEAD'])
    async def member_shell(request: Request, member_path: str):
        path = '/' + member_path
        if not member_shell_route(path):
            return Response(status_code=404)
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app)
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, login_manager=login_manager,
            )
            if auth.user is None:
                from oneirodex.runtime_native.acquire_status import _login_redirect

                response = _login_redirect(flask_app, request, login_manager, auth)
                return response
            game_details = re.fullmatch(r'/game_details/([^/]+)', path)
            if game_details:
                from sqlalchemy import select
                from oneirodex.models import Game
                from oneirodex.runtime_native.db_session import native_db
                from oneirodex.utils.library_acl import user_can_access_game

                raw_uuid = game_details.group(1)
                try:
                    valid_uuid = str(uuid.UUID(raw_uuid, version=4))
                except (TypeError, ValueError, AttributeError):
                    return Response(status_code=404)
                game = native_db.session.execute(
                    select(Game).filter_by(uuid=valid_uuid)
                ).scalars().first()
                if game is None:
                    return Response(status_code=404)
                if not user_can_access_game(auth.user, game):
                    return Response(status_code=403)
            if path == '/activity' and not _legacy_feature_enabled(
                flask_app.config, 'ENABLE_ACTIVITY_FEED', 'true',
            ):
                response = RedirectResponse('/library', status_code=302)
                from oneirodex.utils.security_headers import security_header_values

                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                return response
            if path == '/vr' and not _legacy_feature_enabled(
                flask_app.config, 'ENABLE_VR_BROWSE', '',
            ):
                response = RedirectResponse('/library', status_code=302)
                from oneirodex.utils.security_headers import security_header_values

                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                return response

            if path == '/playromtest':
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append((
                    'info',
                    'Use Play from a game details page for browser emulation.',
                ))
                auth.session_data['_flashes'] = flashes

            from sqlalchemy import select
            from oneirodex.runtime_native.db_session import native_db
            from oneirodex.models import GlobalSettings
            from oneirodex.runtime_native.session_compat import generate_csrf_token

            extra = {}
            if path == '/library':
                from oneirodex.models import Library, UserPreference
                from oneirodex.utils.helpers.counts import (
                    get_first_run_state, get_games_count, get_library_count,
                )

                preferences = getattr(auth.user, 'preferences', None)
                if preferences is None:
                    preferences = UserPreference(user_id=auth.user.id)
                    native_db.session.add(preferences)
                    native_db.session.commit()
                    auth.user.preferences = preferences

                saved_filters = {}
                raw_filters = request.cookies.get('libraryFilters')
                if raw_filters:
                    try:
                        decoded = json.loads(unquote(raw_filters))
                        if isinstance(decoded, dict):
                            saved_filters = {key: value for key, value in decoded.items() if value}
                    except (json.JSONDecodeError, TypeError, ValueError):
                        saved_filters = {}

                query = request.query_params
                library_uuid = query.get('library_uuid') or saved_filters.get('library_uuid')
                library_name = query.get('library_name')
                if library_name:
                    library = native_db.session.execute(
                        select(Library).filter_by(name=library_name)
                    ).scalars().first()
                    if library is None:
                        flashes = list(auth.session_data.get('_flashes') or [])
                        flashes.append(('error', 'Library not found.'))
                        auth.session_data['_flashes'] = flashes
                        response = RedirectResponse('/library', status_code=302)
                        from oneirodex.runtime_native.oidc_status import _set_session_cookie

                        _set_session_cookie(response, flask_app, auth)
                        for key, value in security_header_values(flask_app.config).items():
                            response.headers.setdefault(key, value)
                        return response
                    library_uuid = library.uuid

                per_page = getattr(preferences, 'items_per_page', None) or 50
                raw_per_page = query.get('per_page')
                try:
                    per_page = int(raw_per_page) or per_page if raw_per_page else per_page
                except (TypeError, ValueError):
                    pass
                raw_rating = query.get('rating')
                try:
                    rating = int(raw_rating) if raw_rating else None
                except (TypeError, ValueError):
                    rating = None
                if rating is None:
                    saved_rating = saved_filters.get('rating')
                    rating = int(saved_rating) if str(saved_rating or '').isdigit() else None

                filters = {
                    'library_uuid': library_uuid,
                    'genre': query.get('genre') or saved_filters.get('genre'),
                    'rating': rating,
                    'game_mode': query.get('game_mode') or saved_filters.get('game_mode'),
                    'player_perspective': query.get('player_perspective') or saved_filters.get('player_perspective'),
                    'theme': query.get('theme') or saved_filters.get('theme'),
                }
                first_run = get_first_run_state()
                extra = {
                    'title': 'Library',
                    'library_count': get_library_count(),
                    'games_count': get_games_count(),
                    'scan_has_run': first_run['scan_has_run'],
                    'unmatched_count': first_run['unmatched_count'],
                    'user_per_page': per_page,
                    'user_default_sort': query.get('sort_by') or preferences.default_sort or 'name',
                    'user_default_sort_order': query.get('sort_order') or preferences.default_sort_order or 'asc',
                    'filters': {key: value for key, value in filters.items() if value is not None},
                }

            row = native_db.session.execute(
                select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
            ).scalars().first()
            settings = _shell_settings(row)
            csrf_token = generate_csrf_token(
                auth.session_data,
                flask_app.config.get('WTF_CSRF_SECRET_KEY') or flask_app.config.get('SECRET_KEY'),
                field_name=flask_app.config.get('WTF_CSRF_FIELD_NAME', 'csrf_token'),
            )
            collection = re.fullmatch(r'/collections/([^/]+)', path)
            if path == '/library':
                pass
            elif collection:
                extra.update(title='Collection', collection_uuid=collection.group(1))
            else:
                extra['title'] = STATIC_MEMBER_TITLES.get(path, 'Discover')
            html = render_member_shell(
                auth.user, flask_app, settings, auth.session_data, csrf_token,
                path=path, extra=extra,
            )
            response = Response(html, media_type='text/html')
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            from oneirodex.runtime_native.oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router
