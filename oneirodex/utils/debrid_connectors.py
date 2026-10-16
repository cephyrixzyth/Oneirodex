"""Optional Real-Debrid / AllDebrid connectors (BYO API keys)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests
from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.challenge_solver import fetch_with_challenge_retry

DEFAULT_TIMEOUT = 30


def _settings() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def debrid_enabled(*, config=None) -> bool:
    config = config if config is not None else get_runtime_config()
    return str(config.get('ENABLE_DEBRID', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def get_debrid_config(*, config=None) -> dict[str, Any]:
    config = config if config is not None else get_runtime_config()
    row = _settings()
    cfg = getattr(row, 'arr_settings', None) if row else None
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        'real_debrid_token': cfg.get('real_debrid_token') or config.get('REAL_DEBRID_TOKEN') or '',
        'alldebrid_api_key': cfg.get('alldebrid_api_key') or config.get('ALLDEBRID_API_KEY') or '',
        'premiumize_api_key': cfg.get('premiumize_api_key') or config.get('PREMIUMIZE_API_KEY') or '',
        'torbox_api_key': cfg.get('torbox_api_key') or config.get('TORBOX_API_KEY') or '',
    }


def save_debrid_config(payload: dict[str, Any]) -> dict[str, Any]:
    row = _settings()
    if not row:
        row = GlobalSettings()
        db.session.add(row)
    current = dict(getattr(row, 'arr_settings', None) or {})
    for key in ('real_debrid_token', 'alldebrid_api_key', 'premiumize_api_key', 'torbox_api_key'):
        if key in payload and payload[key] is not None:
            current[key] = str(payload[key]).strip()
    row.arr_settings = current
    db.session.commit()
    return {
        'real_debrid_token': '***' if current.get('real_debrid_token') else '',
        'alldebrid_api_key': '***' if current.get('alldebrid_api_key') else '',
        'premiumize_api_key': '***' if current.get('premiumize_api_key') else '',
        'torbox_api_key': '***' if current.get('torbox_api_key') else '',
    }


def debrid_status(*, config=None) -> list[dict[str, Any]]:
    cfg = get_debrid_config(config=config)
    return [
        {
            'id': 'real_debrid',
            'configured': bool(cfg.get('real_debrid_token')),
            'enabled': debrid_enabled(config=config),
        },
        {
            'id': 'alldebrid',
            'configured': bool(cfg.get('alldebrid_api_key')),
            'enabled': debrid_enabled(config=config),
        },
        {
            'id': 'premiumize',
            'configured': bool(cfg.get('premiumize_api_key')),
            'enabled': debrid_enabled(config=config),
        },
        {
            'id': 'torbox',
            'configured': bool(cfg.get('torbox_api_key')),
            'enabled': debrid_enabled(config=config),
        },
    ]


def real_debrid_add_magnet(magnet: str) -> dict[str, Any]:
    token = get_debrid_config().get('real_debrid_token')
    if not token:
        raise RuntimeError('Real-Debrid token not configured')
    response = fetch_with_challenge_retry(
        'post',
        'https://api.real-debrid.com/rest/1.0/torrents/addMagnet',
        headers={'Authorization': f'Bearer {token}'},
        data={'magnet': magnet},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def alldebrid_upload_magnet(magnet: str) -> dict[str, Any]:
    key = get_debrid_config().get('alldebrid_api_key')
    if not key:
        raise RuntimeError('AllDebrid API key not configured')
    response = fetch_with_challenge_retry(
        'post',
        urljoin('https://api.alldebrid.com/', 'v4/magnet/upload'),
        params={'agent': 'Oneirodex', 'apikey': key},
        data={'magnets[]': magnet},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def premiumize_add_magnet(magnet: str) -> dict[str, Any]:
    key = get_debrid_config().get('premiumize_api_key')
    if not key:
        raise RuntimeError('Premiumize API key not configured')
    response = fetch_with_challenge_retry(
        'post',
        'https://www.premiumize.me/api/transfer/create',
        data={'apikey': key, 'src': magnet},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def torbox_add_magnet(magnet: str) -> dict[str, Any]:
    key = get_debrid_config().get('torbox_api_key')
    if not key:
        raise RuntimeError('TorBox API key not configured')
    response = fetch_with_challenge_retry(
        'post',
        'https://api.torbox.app/v1/api/torrents/createtorrent',
        headers={'Authorization': f'Bearer {key}'},
        data={'magnet': magnet},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
