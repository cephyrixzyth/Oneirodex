"""Ollama-backed AI assist (suggestions by default; apply is double-gated)."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from flask import current_app
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GlobalSettings
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.http_safe import BlockedOutboundUrl, safe_request
from oneirodex.utils.security import validate_connector_http_url, validate_outbound_http_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30

#: Fixed client-facing text. ``requests`` exception strings name the host, port
#: and sometimes the resolver's failure; the detail goes to the server log.
_OLLAMA_UNREACHABLE = 'Ollama unreachable'
_OLLAMA_BLOCKED = 'Ollama URL is not allowed by the outbound policy'


def _operator_ollama_url(url: str) -> tuple[bool, str]:
    """Env / built-in default Ollama URL: the operator's own choice.

    ``OLLAMA_BASE_URL`` (and the loopback default) were never validated, and
    ``http://host.docker.internal:11434`` is the documented Docker value, so the
    private/loopback range stays reachable regardless of the LAN flag. Cloud
    metadata still is not.
    """
    return validate_outbound_http_url(url, allow_http=True, allow_private_lan=True)


def _ollama_url_validator():
    """The policy the effective Ollama base URL must pass on every request.

    An admin-saved URL was validated with ``validate_connector_http_url`` at
    save time and is held to that same LAN-aware policy at use time -- and on
    every redirect hop, which a one-shot save check never covered.
    """
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if settings is not None and getattr(settings, 'ollama_base_url', None):
        return validate_connector_http_url
    return _operator_ollama_url


def _ollama_failure_text(exc: BaseException) -> str:
    """Fixed text for a failed Ollama call; the detail is logged, not returned."""
    logger.warning('Ollama request failed: %s', type(exc).__name__)
    return _OLLAMA_BLOCKED if isinstance(exc, BlockedOutboundUrl) else _OLLAMA_UNREACHABLE


def ai_enabled() -> bool:
    if str(current_app.config.get('ENABLE_AI_ASSIST', '')).lower() in (
        '1', 'true', 'yes', 'on',
    ):
        return True
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    return bool(getattr(settings, 'enable_ai_assist', False)) if settings else False


def ai_auto_apply_enabled() -> bool:
    """Requires AI assist + explicit ENABLE_AI_AUTO_APPLY (never silent)."""
    if not ai_enabled():
        return False
    return str(current_app.config.get('ENABLE_AI_AUTO_APPLY', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def _ollama_config() -> tuple[str, str]:
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    base = (
        (getattr(settings, 'ollama_base_url', None) if settings else None)
        or current_app.config.get('OLLAMA_BASE_URL')
        or 'http://127.0.0.1:11434'
    ).rstrip('/')
    model = (
        (getattr(settings, 'ollama_model', None) if settings else None)
        or current_app.config.get('OLLAMA_MODEL')
        or 'llama3.2'
    )
    return base, model


def ollama_status() -> dict[str, Any]:
    enabled = ai_enabled()
    base, model = _ollama_config()
    reachable = False
    error = None
    if enabled:
        try:
            resp = safe_request(
                'GET',
                f'{base}/api/tags',
                validator=_ollama_url_validator(),
                timeout=5,
            )
            reachable = resp.status_code < 500
            if resp.status_code >= 400:
                error = f'Ollama returned {resp.status_code}'
        except requests.RequestException as exc:
            error = _ollama_failure_text(exc)
    return {
        'enabled': enabled,
        'auto_apply_enabled': ai_auto_apply_enabled(),
        'reachable': reachable,
        'base_url': base,
        'model': model,
        'error': error,
    }


def get_ai_config() -> dict[str, Any]:
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    base, model = _ollama_config()
    return {
        'enabled': ai_enabled(),
        'db_enabled': bool(getattr(settings, 'enable_ai_assist', False)) if settings else False,
        'env_enabled': str(current_app.config.get('ENABLE_AI_ASSIST', '')).lower() in (
            '1', 'true', 'yes', 'on',
        ),
        'ollama_base_url': base,
        'ollama_model': model,
        'auto_apply_enabled': ai_auto_apply_enabled(),
    }


def save_ai_config(payload: dict[str, Any]) -> dict[str, Any]:
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if settings is None:
        settings = GlobalSettings()
        db.session.add(settings)
    if 'enabled' in payload or 'enable_ai_assist' in payload:
        settings.enable_ai_assist = bool(
            payload.get('enabled', payload.get('enable_ai_assist')),
        )
    if 'ollama_base_url' in payload and payload['ollama_base_url'] is not None:
        url = str(payload['ollama_base_url']).strip().rstrip('/')
        if url:
            from oneirodex.utils.security import validate_connector_http_url

            ok, result = validate_connector_http_url(url)
            if not ok:
                raise ValueError(result)
            url = result.rstrip('/')
        settings.ollama_base_url = url or None
    if 'ollama_model' in payload and payload['ollama_model'] is not None:
        model = str(payload['ollama_model']).strip()
        settings.ollama_model = model or None
    db.session.commit()
    return get_ai_config()


def _chat(system: str, user: str) -> str:
    if not ai_enabled():
        raise PermissionError('AI assist is disabled')
    base, model = _ollama_config()
    try:
        resp = safe_request(
            'POST',
            f'{base}/api/chat',
            validator=_ollama_url_validator(),
            json={
                'model': model,
                'stream': False,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ConnectionError(_ollama_failure_text(exc)) from exc
    if resp.status_code >= 400:
        raise ConnectionError(f'Ollama error ({resp.status_code})')
    payload = resp.json() if resp.content else {}
    message = payload.get('message') or {}
    content = message.get('content') or payload.get('response') or ''
    return str(content).strip()


def _parse_ranked_titles(text: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for line in (text or '').splitlines():
        match = re.match(r'^\s*(?:\d+[\).:-]|[-*])\s*(.+)$', line.strip())
        if not match:
            continue
        title = match.group(1).strip().strip('"\'')
        if title:
            suggestions.append({'rank': len(suggestions) + 1, 'title': title[:200]})
        if len(suggestions) >= 5:
            break
    if not suggestions and text.strip():
        suggestions.append({'rank': 1, 'title': text.strip().splitlines()[0][:200]})
    return suggestions


def triage_folder(name: str, platform: str | None = None) -> dict[str, Any]:
    folder = (name or '').strip()
    if not folder:
        raise ValueError('folder name is required')
    system = (
        'You suggest likely game titles for a DRM-free self-hosted library. '
        'Reply with a numbered list of up to 5 clean game titles only. No downloads.'
    )
    user = f'Folder name: {folder}\nPlatform: {platform or "unknown"}'
    content = _chat(system, user)
    return {
        'query': folder,
        'platform': platform,
        'raw': content,
        'suggestions': _parse_ranked_titles(content),
        'auto_apply_enabled': ai_auto_apply_enabled(),
    }


def doctor_notes(context: dict[str, Any]) -> dict[str, Any]:
    game_name = (context.get('game_name') or context.get('name') or 'Unknown').strip()
    issues = context.get('issues') or context.get('issue_codes') or []
    if isinstance(issues, str):
        issues = [issues]
    issue_text = ', '.join(str(i) for i in issues) if issues else 'general health review'
    system = (
        'You are a library doctor assistant for a self-hosted game library. '
        'Explain issues in plain language and suggest next steps. Do not invent '
        'file paths. Do not claim you modified anything.'
    )
    user = (
        f'Game: {game_name}\n'
        f'Issues: {issue_text}\n'
        f'Extra: {context.get("summary") or context.get("extra") or "n/a"}'
    )
    content = _chat(system, user)
    return {
        'game_name': game_name,
        'issues': list(issues),
        'notes': content,
    }


def apply_triage_title(game_uuid: str, title: str) -> dict[str, Any]:
    """Apply a triage suggestion by renaming an existing library game (admin action)."""
    if not ai_auto_apply_enabled():
        raise PermissionError(
            'AI auto-apply is disabled. Set ENABLE_AI_AUTO_APPLY=true (and ENABLE_AI_ASSIST).',
        )
    uuid = (game_uuid or '').strip()
    new_name = (title or '').strip()[:200]
    if not uuid:
        raise ValueError('game_uuid is required')
    if not new_name:
        raise ValueError('title is required')
    game = db.session.execute(select(Game).filter_by(uuid=uuid)).scalars().first()
    if not game:
        raise LookupError('Game not found')
    old_name = game.name
    if old_name == new_name:
        return {
            'applied': False,
            'unchanged': True,
            'game_uuid': uuid,
            'name': new_name,
        }
    game.name = new_name
    db.session.commit()
    try:
        log_system_event(
            f'AI triage apply: renamed "{old_name}" → "{new_name}" ({uuid})',
            event_type='audit',
            event_level='information',
        )
    except Exception:
        pass
    return {
        'applied': True,
        'unchanged': False,
        'game_uuid': uuid,
        'old_name': old_name,
        'name': new_name,
    }
