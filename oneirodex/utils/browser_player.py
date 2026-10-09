"""Browser play engine settings.

Admin keys live under ``GlobalSettings.settings['browser_player']``.
Only engines that are actually wired may be the default or listed as available.
"""

from __future__ import annotations

from typing import Any

from flask import current_app, g, has_app_context, has_request_context
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import GlobalSettings

STORAGE_KEY = 'browser_player'

# Names we recognize in settings. Availability is a separate set.
KNOWN_ENGINES = ('webretro', 'emulatorjs')
# Both browser engines ship in the image; admins can disable EmulatorJS in the
# browser play settings without removing the bundled release.
SHIPPED_ENGINES = ('webretro',)


def available_engines() -> tuple[str, ...]:
    """Engines that can actually boot a game on this install, in listing order.

    Memoised per request. `emulatorjs_installed()` is a filesystem stat, and
    `play_engine_fields()` runs once per game in `browse_play_fields` — so an
    unmemoised probe meant one stat per tile, up to a thousand on a single
    browse page, against a Docker bind mount to the NAS array. Request scope,
    not app-context scope: an operator who drops a release in mid-session sees
    it on the next page rather than after a restart.
    """
    if has_request_context() and hasattr(g, '_browser_player_available'):
        return g._browser_player_available

    from oneirodex.utils.emulatorjs import emulatorjs_installed

    engines = list(SHIPPED_ENGINES)
    enabled = True
    if has_app_context() and current_app.extensions.get('sqlalchemy') is not None:
        enabled = _blob(_settings_row()).get('browser_player_emulatorjs_enabled', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {'1', 'true', 'yes', 'on'}
    if enabled and emulatorjs_installed():
        engines.append('emulatorjs')
    resolved = tuple(engines)
    if has_request_context():
        g._browser_player_available = resolved
    return resolved

DEFAULTS: dict[str, Any] = {
    'browser_player_default': 'webretro',
    'browser_player_emulatorjs_enabled': True,
    'browser_player_allow_member_choice': False,
    # BP-1: NES-only Nostalgist host. Off by default.
    'nostalgist_nes_pilot': False,
    'webrcade_sidecar_url': '',
    'webrcade_feed_export': False,
}


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _ensure_settings_row() -> GlobalSettings:
    row = _settings_row()
    if row is None:
        row = GlobalSettings(settings={})
        db.session.add(row)
        db.session.flush()
    return row


def _blob(row: GlobalSettings | None) -> dict[str, Any]:
    raw = getattr(row, 'settings', None) if row is not None else None
    if not isinstance(raw, dict):
        return {}
    nested = raw.get(STORAGE_KEY)
    return nested if isinstance(nested, dict) else {}


def _clean_url(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    if not (text.startswith('http://') or text.startswith('https://')):
        raise ValueError('webrcade_sidecar_url must be http(s) or empty')
    return text.rstrip('/')


def normalize_browser_player_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a full settings dict from a partial payload (no I/O)."""
    src = raw if isinstance(raw, dict) else {}
    default = str(src.get('browser_player_default') or DEFAULTS['browser_player_default']).strip().lower()
    if default not in KNOWN_ENGINES:
        raise ValueError(f'Unsupported browser_player_default: {default}')
    allow = src.get(
        'browser_player_allow_member_choice',
        DEFAULTS['browser_player_allow_member_choice'],
    )
    if isinstance(allow, str):
        allow = allow.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        allow = bool(allow)
    export = src.get('webrcade_feed_export', DEFAULTS['webrcade_feed_export'])
    if isinstance(export, str):
        export = export.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        export = bool(export)
    pilot = src.get('nostalgist_nes_pilot', DEFAULTS['nostalgist_nes_pilot'])
    if isinstance(pilot, str):
        pilot = pilot.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        pilot = bool(pilot)
    emulatorjs_enabled = src.get('browser_player_emulatorjs_enabled', DEFAULTS['browser_player_emulatorjs_enabled'])
    if isinstance(emulatorjs_enabled, str):
        emulatorjs_enabled = emulatorjs_enabled.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        emulatorjs_enabled = bool(emulatorjs_enabled)
    from oneirodex.utils.emulatorjs import emulatorjs_installed

    emulatorjs_installed_here = emulatorjs_installed()
    available = (
        (*SHIPPED_ENGINES, 'emulatorjs')
        if emulatorjs_enabled and emulatorjs_installed_here
        else tuple(SHIPPED_ENGINES)
    )
    if default not in available:
        if default == 'emulatorjs' and emulatorjs_enabled and not emulatorjs_installed_here:
            raise ValueError(
                f'emulatorjs is not installed in this build — default must be one of: {", ".join(available)}'
            )
        default = 'webretro'
    return {
        'browser_player_default': default,
        'browser_player_emulatorjs_enabled': emulatorjs_enabled,
        'browser_player_allow_member_choice': allow,
        'nostalgist_nes_pilot': pilot,
        'webrcade_sidecar_url': _clean_url(src.get('webrcade_sidecar_url')),
        'webrcade_feed_export': export,
        'browser_players_available': list(available),
        'emulatorjs_installed': emulatorjs_installed_here,
    }


def get_browser_player_settings() -> dict[str, Any]:
    """Read stored admin keys, filling defaults. Safe without a settings row."""
    # Request scope on purpose. `g` is app-context scoped, so caching on a bare
    # app context makes a long-lived one (a CLI command, a worker loop) hold the
    # first answer forever — `set_browser_player_settings` can only clear the
    # context it runs in, which is a different process. A request is short
    # enough that "once per request" is both cheap and always fresh.
    if has_request_context() and hasattr(g, '_browser_player_settings'):
        return g._browser_player_settings
    try:
        merged = {**DEFAULTS, **_blob(_settings_row())}
        cleaned = normalize_browser_player_settings(merged)
    except Exception:
        cleaned = normalize_browser_player_settings(DEFAULTS)
    if has_request_context():
        g._browser_player_settings = cleaned
    return cleaned


def set_browser_player_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and persist admin browser-player keys."""
    cleaned = normalize_browser_player_settings(
        {**get_browser_player_settings(), **(payload or {})},
    )
    row = _ensure_settings_row()
    current = dict(row.settings) if isinstance(row.settings, dict) else {}
    stored = {
        'browser_player_default': cleaned['browser_player_default'],
        'browser_player_emulatorjs_enabled': cleaned['browser_player_emulatorjs_enabled'],
        'browser_player_allow_member_choice': cleaned['browser_player_allow_member_choice'],
        'nostalgist_nes_pilot': cleaned['nostalgist_nes_pilot'],
        'webrcade_sidecar_url': cleaned['webrcade_sidecar_url'],
        'webrcade_feed_export': cleaned['webrcade_feed_export'],
    }
    current[STORAGE_KEY] = stored
    row.settings = current
    db.session.commit()
    # Drop both caches: a default that just changed must not be read from a
    # stale blob, and an engine that just became (un)installed must re-probe.
    if has_request_context():
        for key in ('_browser_player_settings', '_browser_player_available'):
            if hasattr(g, key):
                delattr(g, key)
    return cleaned


ENGINE_LABELS = {
    'webretro': 'WebRetro',
    'emulatorjs': 'EmulatorJS',
}


def engine_label(engine: str) -> str:
    return ENGINE_LABELS.get(str(engine or '').strip().lower(), str(engine or ''))


def member_engine_preference() -> str | None:
    """The signed-in member's stored engine choice, or None. Never raises."""
    try:
        from flask_login import current_user

        if not has_request_context() or not getattr(current_user, 'is_authenticated', False):
            return None
        prefs = getattr(current_user, 'preferences', None)
        value = str(getattr(prefs, 'browser_player_engine', '') or '').strip().lower()
        return value if value in KNOWN_ENGINES else None
    except Exception:
        return None


def resolve_engine(
    *,
    settings: dict[str, Any] | None = None,
    preference: str | None = None,
    available: tuple[str, ...] | None = None,
) -> str:
    """Engine that actually launches for this request.

    Member preference wins only when the admin allows member choice *and* the
    engine is installed here; otherwise the admin default, and if even that is
    not installed, WebRetro (always shipped). Pure — callers pass the inputs.
    """
    installed = available if available is not None else available_engines()
    if settings is None:
        try:
            settings = get_browser_player_settings()
        except Exception:
            settings = dict(DEFAULTS)
    allow = bool(settings.get('browser_player_allow_member_choice'))
    if allow and preference in installed:
        return str(preference)
    default = str(settings.get('browser_player_default') or 'webretro')
    return default if default in installed else 'webretro'


def play_engine_fields() -> dict[str, Any]:
    """Fields for browse/details play payloads. Never lists an unwired engine.

    ``browser_player`` is the engine this member's Play link will open — the
    resolved one, not the admin default — so the tile and the launch agree.
    ``browser_player_member_choice`` / ``browser_player_preference`` let the
    member surface offer a choice and show which one is theirs.
    """
    try:
        settings = get_browser_player_settings()
    except Exception:
        settings = dict(DEFAULTS)
    pilot = bool(settings.get('nostalgist_nes_pilot'))
    available = available_engines()
    preference = member_engine_preference()
    allow = bool(settings.get('browser_player_allow_member_choice')) and len(available) > 1
    return {
        'browser_player': resolve_engine(settings=settings, preference=preference, available=available),
        'browser_player_default': (
            settings.get('browser_player_default')
            if settings.get('browser_player_default') in available
            else 'webretro'
        ),
        'browser_players_available': list(available),
        'browser_player_member_choice': allow,
        'browser_player_preference': preference if allow else None,
        'nostalgist_nes_pilot': pilot,
    }


def nostalgist_nes_pilot_enabled() -> bool:
    """True when the BP-1 NES Nostalgist host may replace WebRetro for NES."""
    try:
        return bool(get_browser_player_settings().get('nostalgist_nes_pilot'))
    except Exception:
        return False


def browser_play_href(
    *,
    game_uuid: str,
    core: str,
    platform_key: str | None = None,
    cheat_surface: str | None = None,
) -> str:
    """Build the member Play href for a guid/core (WebRetro or NES pilot)."""
    guid = str(game_uuid or '').strip()
    core_id = str(core or '').strip()
    key = str(platform_key or '').strip().upper() or None
    if not guid or not core_id:
        return ''
    params = [f'guid={guid}', f'core={core_id}']
    if key:
        params.append(f'platform={key}')
    if cheat_surface:
        params.append(f'cheat_surface={cheat_surface}')
    query = '&'.join(params)
    if key == 'NES' and nostalgist_nes_pilot_enabled():
        return f'/static/vendor/nostalgist/play.html?{query}'
    # BP-2: engine B when the resolved engine (member choice if allowed, else
    # the admin default) is EmulatorJS AND it is installed AND it has a core
    # for this system. Any of those false -> WebRetro, silently; the honesty
    # badges are per capability, not per engine.
    if key and play_engine_fields()['browser_player'] == 'emulatorjs':
        from oneirodex.utils.emulatorjs import emulatorjs_play_href

        href = emulatorjs_play_href(game_uuid=guid, platform_key=key, cheat_surface=cheat_surface)
        if href:
            return href
    return f'/static/vendor/webretro/webretro.html?{query}'
