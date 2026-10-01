"""Ambient lighting bridge — Hyperion.ng JSON-RPC and Home Assistant REST.

Fire-and-forget on play session start/stop; never blocks play launch.
Child accounts are ignored (no lighting control).
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any
from urllib.parse import urljoin

import requests
from flask import current_app
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import GlobalSettings, User
from oneirodex.utils.http_safe import BlockedOutboundUrl, safe_request
from oneirodex.utils.rbac import normalize_role
from oneirodex.utils.security import validate_connector_http_url

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = frozenset({'off', 'hyperion', 'homeassistant'})
_DEFAULT_ACCENT = (255, 128, 32)
_ORIGIN = 'Oneirodex'
_LAST_ERROR: str | None = None
_TAN_COUNTER = 0
_TAN_LOCK = threading.Lock()


def _next_tan() -> int:
    global _TAN_COUNTER
    with _TAN_LOCK:
        _TAN_COUNTER = (_TAN_COUNTER + 1) % 1_000_000
        return _TAN_COUNTER


def _set_last_error(message: str | None) -> None:
    global _LAST_ERROR
    _LAST_ERROR = message


def _failure_text(exc: BaseException) -> str:
    """Fixed wording for transport failures; our own RuntimeErrors pass through.

    ``requests`` exception strings carry the request URL and resolver detail, and
    ``last_error`` is surfaced on the admin status payload.
    """
    if isinstance(exc, BlockedOutboundUrl):
        return 'Lighting URL is not allowed by the outbound policy'
    if isinstance(exc, requests.RequestException):
        return 'Lighting bridge unreachable'
    return str(exc)


def _post(session, url: str, **kwargs) -> requests.Response:
    """POST to an admin-configured bridge, revalidating every redirect hop.

    The base URL is validated once at save time; a bridge that later answers
    ``302 Location: http://169.254.169.254/`` used to be followed blindly.
    ``validate_connector_http_url`` is the policy these URLs were saved under
    (LAN allowed while ALLOW_PRIVATE_LAN_URLS is on, cloud metadata never).
    """
    return safe_request(
        'POST', url, validator=validate_connector_http_url, session=session, **kwargs,
    )


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _lighting_cfg() -> dict[str, Any]:
    row = _settings_row()
    cfg = getattr(row, 'arr_settings', None) if row else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def _env_bool(key: str, default: bool = False) -> bool:
    raw = current_app.config.get(key, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ('1', 'true', 'yes', 'on')


def ambient_lighting_enabled() -> bool:
    """Opt-in: env flag OR admin DB toggle (either enables)."""
    if _env_bool('ENABLE_AMBIENT_LIGHTING', False):
        return True
    return bool(_lighting_cfg().get('ambient_lighting_enabled'))


def _resolve_provider() -> str:
    cfg = _lighting_cfg()
    # Prefer explicit DB provider when set; otherwise env / default.
    raw = cfg.get('lighting_provider')
    if raw is None or str(raw).strip() == '':
        raw = current_app.config.get('LIGHTING_PROVIDER') or 'off'
    provider = str(raw).strip().lower()
    if provider not in _VALID_PROVIDERS:
        provider = 'off'
    if not ambient_lighting_enabled():
        return 'off'
    return provider


def _parse_rgb(value: str | list | tuple | None) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            pass
    text = str(value or '').strip()
    if not text:
        return _DEFAULT_ACCENT
    if text.startswith('#') and len(text) >= 7:
        try:
            r = int(text[1:3], 16)
            g = int(text[3:5], 16)
            b = int(text[5:7], 16)
            return (r, g, b)
        except ValueError:
            return _DEFAULT_ACCENT
    parts = re.split(r'[,\s]+', text)
    if len(parts) >= 3:
        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            pass
    return _DEFAULT_ACCENT


def _split_entities(raw: str | list | None) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or '').strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r'[,\s]+', text) if part.strip()]


def get_ambient_config() -> dict[str, Any]:
    cfg = _lighting_cfg()
    hyperion_url = (
        (cfg.get('hyperion_url') or '').strip().rstrip('/')
        or str(current_app.config.get('HYPERION_URL') or '').strip().rstrip('/')
    )
    ha_url = (
        (cfg.get('ha_url') or '').strip().rstrip('/')
        or str(current_app.config.get('HA_URL') or current_app.config.get('HOME_ASSISTANT_URL') or '').strip().rstrip('/')
    )
    provider = _resolve_provider() if ambient_lighting_enabled() else (
        str(cfg.get('lighting_provider') or current_app.config.get('LIGHTING_PROVIDER') or 'off').strip().lower()
    )
    if provider not in _VALID_PROVIDERS:
        provider = 'off'
    accent = cfg.get('ambient_accent_color') or current_app.config.get('AMBIENT_ACCENT_COLOR') or '255,128,32'
    entities = cfg.get('ha_light_entities')
    if entities is None:
        entities = current_app.config.get('HA_LIGHT_ENTITIES') or ''
    priority = cfg.get('hyperion_priority')
    if priority is None:
        priority = current_app.config.get('HYPERION_PRIORITY', 50)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        priority = 50
    ha_play_scene = (
        cfg.get('ha_play_scene')
        or current_app.config.get('HA_PLAY_SCENE')
        or ''
    )
    ha_stop_scene = (
        cfg.get('ha_stop_scene')
        or current_app.config.get('HA_STOP_SCENE')
        or ''
    )
    token_configured = bool(
        cfg.get('hyperion_token')
        or current_app.config.get('HYPERION_TOKEN')
    )
    ha_token_configured = bool(
        cfg.get('ha_token')
        or current_app.config.get('HA_TOKEN')
        or current_app.config.get('HOME_ASSISTANT_TOKEN')
    )
    return {
        'enabled': ambient_lighting_enabled(),
        'env_enabled': _env_bool('ENABLE_AMBIENT_LIGHTING', False),
        'db_enabled': bool(cfg.get('ambient_lighting_enabled')),
        'provider': provider,
        'hyperion_url': hyperion_url,
        'hyperion_token_configured': token_configured,
        'hyperion_priority': priority,
        'ambient_accent_color': accent,
        'ha_url': ha_url,
        'ha_token_configured': ha_token_configured,
        'ha_light_entities': _split_entities(entities),
        'ha_play_scene': str(ha_play_scene or '').strip(),
        'ha_stop_scene': str(ha_stop_scene or '').strip(),
    }


def save_ambient_config(payload: dict[str, Any]) -> dict[str, Any]:
    row = _settings_row()
    if row is None:
        row = GlobalSettings()
        db.session.add(row)
    current = _lighting_cfg()
    if 'enabled' in payload or 'ambient_lighting_enabled' in payload:
        current['ambient_lighting_enabled'] = bool(
            payload.get('enabled', payload.get('ambient_lighting_enabled')),
        )
    if 'provider' in payload or 'lighting_provider' in payload:
        provider = str(
            payload.get('provider', payload.get('lighting_provider')) or 'off',
        ).strip().lower()
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f'Invalid provider: {provider}')
        current['lighting_provider'] = provider
    if 'hyperion_url' in payload:
        url = str(payload.get('hyperion_url') or '').strip().rstrip('/')
        if url:
            ok, result = validate_connector_http_url(url)
            if not ok:
                raise ValueError(result)
            url = result.rstrip('/')
        current['hyperion_url'] = url
    if 'hyperion_token' in payload:
        token = str(payload.get('hyperion_token') or '').strip()
        if token and token != '***':
            current['hyperion_token'] = token
    if 'hyperion_priority' in payload:
        try:
            priority = int(payload.get('hyperion_priority'))
        except (TypeError, ValueError) as exc:
            raise ValueError('hyperion_priority must be an integer') from exc
        if priority < 0 or priority > 255:
            raise ValueError('hyperion_priority must be 0–255')
        current['hyperion_priority'] = priority
    if 'ambient_accent_color' in payload:
        current['ambient_accent_color'] = str(payload.get('ambient_accent_color') or '').strip()
    if 'ha_url' in payload:
        url = str(payload.get('ha_url') or '').strip().rstrip('/')
        if url:
            ok, result = validate_connector_http_url(url)
            if not ok:
                raise ValueError(result)
            url = result.rstrip('/')
        current['ha_url'] = url
    if 'ha_token' in payload:
        token = str(payload.get('ha_token') or '').strip()
        if token and token != '***':
            current['ha_token'] = token
    if 'ha_light_entities' in payload:
        raw = payload.get('ha_light_entities')
        current['ha_light_entities'] = _split_entities(raw)
    if 'ha_play_scene' in payload:
        current['ha_play_scene'] = str(payload.get('ha_play_scene') or '').strip()
    if 'ha_stop_scene' in payload:
        current['ha_stop_scene'] = str(payload.get('ha_stop_scene') or '').strip()
    row.arr_settings = current
    db.session.commit()
    return get_ambient_config()


class HyperionClient:
    """Hyperion.ng JSON-RPC client — set color / clear priority."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = '',
        priority: int = 50,
        session: requests.Session | None = None,
        timeout_sec: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        if not self.base_url.endswith('/json-rpc'):
            self.rpc_url = urljoin(self.base_url + '/', 'json-rpc')
        else:
            self.rpc_url = self.base_url
        self.token = token
        self.priority = max(0, min(255, int(priority)))
        self._session = session or requests.Session()
        self.timeout_sec = timeout_sec

    def _post_command(self, command: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'command': command,
            'tan': _next_tan(),
            'priority': self.priority,
            **extra,
        }
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        resp = _post(
            self._session,
            self.rpc_url,
            json=payload,
            headers=headers,
            timeout=self.timeout_sec,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f'Hyperion HTTP {resp.status_code}')
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and data.get('success') is False:
            raise RuntimeError(str(data.get('error') or 'Hyperion command failed'))
        return data if isinstance(data, dict) else {}

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        self._post_command(
            'color',
            color=[max(0, min(255, c)) for c in rgb],
            origin=_ORIGIN,
            duration=0,
        )

    def clear_priority(self) -> None:
        self._post_command('clear', origin=_ORIGIN)


class HomeAssistantClient:
    """Home Assistant REST — light.turn_on / scene.turn_on."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout_sec: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.token = token
        self._session = session or requests.Session()
        self.timeout_sec = timeout_sec

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }

    def _call_service(self, domain: str, service: str, body: dict[str, Any]) -> None:
        url = urljoin(self.base_url + '/', f'api/services/{domain}/{service}')
        resp = _post(
            self._session,
            url,
            json=body,
            headers=self._headers(),
            timeout=self.timeout_sec,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f'Home Assistant HTTP {resp.status_code}')

    def turn_on_lights(self, entity_ids: list[str], rgb: tuple[int, int, int]) -> None:
        if not entity_ids:
            raise RuntimeError('No HA light entities configured')
        self._call_service(
            'light',
            'turn_on',
            {
                'entity_id': entity_ids,
                'rgb_color': list(rgb),
            },
        )

    def turn_on_scene(self, entity_id: str) -> None:
        if not entity_id:
            raise RuntimeError('No HA scene entity configured')
        self._call_service('scene', 'turn_on', {'entity_id': entity_id})


def _hyperion_client(cfg: dict[str, Any]) -> HyperionClient | None:
    url = cfg.get('hyperion_url') or ''
    if not url:
        return None
    ok, cleaned = validate_connector_http_url(url)
    if not ok:
        _set_last_error(cleaned)
        return None
    arr = _lighting_cfg()
    token = str(
        arr.get('hyperion_token')
        or current_app.config.get('HYPERION_TOKEN')
        or '',
    )
    return HyperionClient(
        cleaned,
        token=token,
        priority=int(cfg.get('hyperion_priority') or 50),
    )


def _ha_client(cfg: dict[str, Any]) -> HomeAssistantClient | None:
    url = cfg.get('ha_url') or ''
    if not url:
        return None
    ok, cleaned = validate_connector_http_url(url)
    if not ok:
        _set_last_error(cleaned)
        return None
    arr = _lighting_cfg()
    token = str(
        arr.get('ha_token')
        or current_app.config.get('HA_TOKEN')
        or current_app.config.get('HOME_ASSISTANT_TOKEN')
        or '',
    )
    if not token:
        _set_last_error('Home Assistant token not configured')
        return None
    return HomeAssistantClient(cleaned, token)


def _apply_play_accent(cfg: dict[str, Any]) -> None:
    provider = cfg.get('provider') or 'off'
    rgb = _parse_rgb(cfg.get('ambient_accent_color'))
    if provider == 'hyperion':
        client = _hyperion_client(cfg)
        if client is None:
            return
        client.set_color(rgb)
        _set_last_error(None)
    elif provider == 'homeassistant':
        client = _ha_client(cfg)
        if client is None:
            return
        play_scene = cfg.get('ha_play_scene') or ''
        if play_scene:
            client.turn_on_scene(play_scene)
        else:
            client.turn_on_lights(cfg.get('ha_light_entities') or [], rgb)
        _set_last_error(None)


def _apply_play_clear(cfg: dict[str, Any]) -> None:
    provider = cfg.get('provider') or 'off'
    if provider == 'hyperion':
        client = _hyperion_client(cfg)
        if client is None:
            return
        client.clear_priority()
        _set_last_error(None)
    elif provider == 'homeassistant':
        client = _ha_client(cfg)
        if client is None:
            return
        stop_scene = cfg.get('ha_stop_scene') or ''
        if stop_scene:
            client.turn_on_scene(stop_scene)
        else:
            entities = cfg.get('ha_light_entities') or []
            if entities:
                client._call_service('light', 'turn_off', {'entity_id': entities})
        _set_last_error(None)


def _run_async(fn, *args) -> None:
    """Fire-and-forget worker with Flask app context."""
    try:
        app = current_app._get_current_object()
    except Exception:
        return

    def worker() -> None:
        with app.app_context():
            try:
                fn(*args)
            except Exception as exc:
                text = _failure_text(exc)
                _set_last_error(text)
                logger.warning('Ambient lighting async failed: %s', text)

    threading.Thread(target=worker, daemon=True, name='oneirodex-ambient-lighting').start()


def _should_skip_user(user: User | None) -> bool:
    if user is None:
        return True
    return normalize_role(getattr(user, 'role', None)) == 'child'


def notify_play_session_started(user: User | None, game: Any | None = None) -> None:
    """Hook: play session start — async accent color / scene."""
    if _should_skip_user(user):
        return
    cfg = get_ambient_config()
    if cfg.get('provider') == 'off' or not cfg.get('enabled'):
        return
    _run_async(_apply_play_accent, cfg)


def notify_play_session_stopped(user_id: int | None = None, *, user: User | None = None) -> None:
    """Hook: play session stop — async clear priority / off scene."""
    if user is None and user_id is not None:
        user = db.session.get(User, user_id)
    if _should_skip_user(user):
        return
    cfg = get_ambient_config()
    if cfg.get('provider') == 'off' or not cfg.get('enabled'):
        return
    _run_async(_apply_play_clear, cfg)


def ambient_lighting_status(*, probe: bool = False) -> dict[str, Any]:
    cfg = get_ambient_config()
    reachable = False
    probe_ok = False
    error = _LAST_ERROR
    provider = cfg.get('provider') or 'off'
    if cfg.get('enabled') and provider != 'off':
        if provider == 'hyperion' and cfg.get('hyperion_url'):
            ok, _ = validate_connector_http_url(cfg['hyperion_url'])
            reachable = ok
            if probe and ok:
                try:
                    client = _hyperion_client(cfg)
                    if client:
                        client.set_color(_parse_rgb(cfg.get('ambient_accent_color')))
                        client.clear_priority()
                        probe_ok = True
                        _set_last_error(None)
                except Exception as exc:
                    error = _failure_text(exc)
                    _set_last_error(error)
        elif provider == 'homeassistant' and cfg.get('ha_url'):
            ok, _ = validate_connector_http_url(cfg['ha_url'])
            reachable = ok and cfg.get('ha_token_configured')
            if probe and reachable:
                try:
                    client = _ha_client(cfg)
                    if client:
                        play_scene = cfg.get('ha_play_scene') or ''
                        if play_scene:
                            client.turn_on_scene(play_scene)
                        elif cfg.get('ha_light_entities'):
                            client.turn_on_lights(
                                cfg['ha_light_entities'],
                                _parse_rgb(cfg.get('ambient_accent_color')),
                            )
                        else:
                            raise RuntimeError('Configure ha_light_entities or ha_play_scene')
                        probe_ok = True
                        _set_last_error(None)
                except Exception as exc:
                    error = _failure_text(exc)
                    _set_last_error(error)
    return {
        'enabled': cfg.get('enabled'),
        'env_enabled': cfg.get('env_enabled'),
        'db_enabled': cfg.get('db_enabled'),
        'provider': provider,
        'hyperion_url': cfg.get('hyperion_url') or None,
        'hyperion_token_configured': cfg.get('hyperion_token_configured'),
        'hyperion_priority': cfg.get('hyperion_priority'),
        'ambient_accent_color': cfg.get('ambient_accent_color'),
        'ha_url': cfg.get('ha_url') or None,
        'ha_token_configured': cfg.get('ha_token_configured'),
        'ha_light_entities': cfg.get('ha_light_entities'),
        'ha_play_scene': cfg.get('ha_play_scene') or None,
        'ha_stop_scene': cfg.get('ha_stop_scene') or None,
        'reachable': reachable,
        'probe_ok': probe_ok if probe else None,
        'last_error': error,
        'note': 'Opt-in ambient bridge — child accounts never trigger lighting.',
    }
