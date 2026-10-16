"""BYO Sunshine / Wolf remote play host (Moonlight clients — GOW-1/GOW-2)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.security import validate_connector_http_url

_VALID_PROVIDERS = frozenset({'sunshine', 'wolf'})
_DEFAULT_MOONLIGHT_PORT = 47989


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _cfg_dict() -> dict[str, Any]:
    row = _settings_row()
    cfg = getattr(row, 'remote_play_settings', None) if row else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def remote_play_enabled(*, config=None) -> bool:
    """Opt-in: env flag OR admin DB toggle."""
    settings = config if config is not None else get_runtime_config()
    raw = settings.get('ENABLE_REMOTE_PLAY', False)
    if isinstance(raw, bool):
        env_on = raw
    else:
        env_on = str(raw).lower() in ('1', 'true', 'yes', 'on')
    if env_on:
        return True
    row = _settings_row()
    return bool(getattr(row, 'enable_remote_play', False))


def _env_flag(name: str, *, config=None) -> bool:
    settings = config if config is not None else get_runtime_config()
    raw = settings.get(name, False)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ('1', 'true', 'yes', 'on')


def _moonlight_endpoint(base_url: str) -> tuple[str | None, int]:
    if not base_url:
        return None, _DEFAULT_MOONLIGHT_PORT
    try:
        parsed = urlparse(base_url.strip())
    except Exception:
        return None, _DEFAULT_MOONLIGHT_PORT
    host = (parsed.hostname or '').strip() or None
    port = parsed.port or _DEFAULT_MOONLIGHT_PORT
    return host, port


def _primary_base_url(cfg: dict[str, Any]) -> str:
    sunshine = (cfg.get('sunshine_base_url') or '').strip().rstrip('/')
    wolf = (cfg.get('wolf_base_url') or '').strip().rstrip('/')
    provider = (cfg.get('provider') or 'sunshine').strip().lower()
    if provider == 'wolf' and wolf:
        return wolf
    if provider == 'sunshine' and sunshine:
        return sunshine
    return sunshine or wolf


def get_remote_play_config(*, admin: bool = False, config=None) -> dict[str, Any]:
    settings = config if config is not None else get_runtime_config()
    cfg = _cfg_dict()
    sunshine = (
        (cfg.get('sunshine_base_url') or '').strip().rstrip('/')
        or str(settings.get('SUNSHINE_BASE_URL') or '').strip().rstrip('/')
    )
    wolf = (
        (cfg.get('wolf_base_url') or '').strip().rstrip('/')
        or str(settings.get('WOLF_BASE_URL') or '').strip().rstrip('/')
    )
    provider = (cfg.get('provider') or settings.get('REMOTE_PLAY_PROVIDER') or 'sunshine').strip().lower()
    if provider not in _VALID_PROVIDERS:
        provider = 'sunshine'
    merged = {
        **cfg,
        'sunshine_base_url': sunshine,
        'wolf_base_url': wolf,
        'provider': provider,
        'token_hint': (cfg.get('token_hint') or settings.get('REMOTE_PLAY_TOKEN_HINT') or '').strip(),
        'pin_hint': (cfg.get('pin_hint') or settings.get('REMOTE_PLAY_PIN_HINT') or '').strip(),
        'app_hint': (cfg.get('app_hint') or settings.get('REMOTE_PLAY_APP_HINT') or '').strip(),
        'host_label': (cfg.get('host_label') or settings.get('REMOTE_PLAY_HOST_LABEL') or '').strip(),
    }
    base = _primary_base_url(merged)
    host, port = _moonlight_endpoint(base)
    row = _settings_row()
    payload: dict[str, Any] = {
        'enabled': remote_play_enabled(config=settings),
        'env_enabled': _env_flag('ENABLE_REMOTE_PLAY', config=settings),
        'db_enabled': bool(getattr(row, 'enable_remote_play', False)) if row else False,
        'provider': provider,
        'sunshine_base_url': sunshine,
        'wolf_base_url': wolf,
        'token_hint': merged['token_hint'] or None,
        'pin_hint': merged['pin_hint'] or None,
        'app_hint': merged['app_hint'] or None,
        'host_label': merged['host_label'] or None,
        'configured': bool(base),
        'moonlight_host': host,
        'moonlight_port': port,
    }
    if admin:
        token = (cfg.get('remote_play_token') or settings.get('REMOTE_PLAY_TOKEN') or '').strip()
        payload['token_set'] = bool(token)
    return payload


def build_copy_hint(cfg: dict[str, Any] | None = None) -> str | None:
    data = cfg or get_remote_play_config()
    if not data.get('configured'):
        return None
    host = data.get('moonlight_host')
    if not host:
        return None
    port = data.get('moonlight_port') or _DEFAULT_MOONLIGHT_PORT
    parts = [f'{host}:{port}']
    if data.get('host_label'):
        parts.insert(0, str(data['host_label']))
    if data.get('app_hint'):
        parts.append(f'App: {data["app_hint"]}')
    if data.get('pin_hint'):
        parts.append(f'PIN: {data["pin_hint"]}')
    if data.get('token_hint'):
        parts.append(f'Token: {data["token_hint"]}')
    return ' — '.join(parts)


def member_remote_play_status(*, config=None) -> dict[str, Any]:
    if not remote_play_enabled(config=config):
        return {'enabled': False, 'configured': False}
    cfg = get_remote_play_config(config=config)
    return {
        'enabled': True,
        'configured': bool(cfg.get('configured')),
        'provider': cfg.get('provider') if cfg.get('configured') else None,
        'moonlight_host': cfg.get('moonlight_host'),
        'moonlight_port': cfg.get('moonlight_port'),
        'host_label': cfg.get('host_label'),
        'app_hint': cfg.get('app_hint'),
        'pin_hint': cfg.get('pin_hint'),
        'token_hint': cfg.get('token_hint'),
        'copy_hint': build_copy_hint(cfg),
    }


def save_remote_play_config(payload: dict[str, Any]) -> dict[str, Any]:
    row = _settings_row()
    if row is None:
        row = GlobalSettings()
        db.session.add(row)
    current = _cfg_dict()

    if 'enabled' in payload or 'enable_remote_play' in payload:
        row.enable_remote_play = bool(payload.get('enabled', payload.get('enable_remote_play')))

    if 'provider' in payload or 'remote_play_provider' in payload:
        provider = str(payload.get('provider', payload.get('remote_play_provider')) or 'sunshine').strip().lower()
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f'Invalid provider: {provider}')
        current['provider'] = provider

    for key, payload_key in (
        ('sunshine_base_url', 'sunshine_base_url'),
        ('wolf_base_url', 'wolf_base_url'),
        ('token_hint', 'token_hint'),
        ('pin_hint', 'pin_hint'),
        ('app_hint', 'app_hint'),
        ('host_label', 'host_label'),
    ):
        if payload_key in payload and payload[payload_key] is not None:
            current[key] = str(payload[payload_key]).strip()

    for url_key in ('sunshine_base_url', 'wolf_base_url'):
        value = (current.get(url_key) or '').strip()
        if not value:
            current[url_key] = ''
            continue
        ok, result = validate_connector_http_url(value)
        if not ok:
            raise ValueError(f'{url_key}: {result} (set ALLOW_PRIVATE_LAN_URLS=true for LAN hosts)')
        current[url_key] = result.rstrip('/')

    if 'remote_play_token' in payload or 'token' in payload:
        token = str(payload.get('remote_play_token', payload.get('token')) or '').strip()
        if token and token != '***':
            current['remote_play_token'] = token

    enabling = bool(row.enable_remote_play) or _env_flag('ENABLE_REMOTE_PLAY')
    if enabling and not (current.get('sunshine_base_url') or current.get('wolf_base_url')):
        raise ValueError('Set at least one Sunshine or Wolf base URL')

    row.remote_play_settings = current
    db.session.commit()
    return get_remote_play_config(admin=True)
