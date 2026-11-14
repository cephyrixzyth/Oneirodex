"""BYO notification bus (INSP-6, v11 cycle H4d).

Oneirodex already tells people things in-app (``UserNotification``) and, for
a few social kinds, by e-mail. This module fans the same events out to
endpoints the household already runs -- an **Apprise API** server and/or an
**ntfy** topic -- so a phone buzzes when a scan finishes or a friend asks.

Rules:

* **Nothing bundled.** No Apprise library, no push service of ours. The
  operator names an Apprise API notify URL (``NOTIFY_APPRISE_URLS``, comma
  list) and/or an ntfy topic URL (``NOTIFY_NTFY_URL``); we POST to them
  through :func:`~oneirodex.utils.http_safe.safe_request`.
* **Admin alerts ride the existing flags.** ``notify_admins`` publishes one
  bus event per alert (not one per admin) and only when the matching
  ``admin_notify_*`` setting is on -- the bus adds a channel, never a new
  kind of noise.
* **Social kinds are opt-in twice.** They reach the bus only when the
  operator sets ``NOTIFY_SOCIAL_TO_BUS=true`` *and* the member's in-app
  preference for that kind is on. A per-member topic (each phone its own
  channel) needs a schema column and is sized in H-I; today the household
  topic is the channel and the docs say so.
* **Never raises, never blocks a request path badly.** Failures are logged
  once and the in-app notification stands. Timeouts are short.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit

from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import validate_user_outbound_http_url

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5
# In-app kinds that count as "social" for the opt-in rule.
SOCIAL_KINDS = frozenset({'friend_request', 'friend_accept', 'mention', 'dm', 'channel', 'free_game'})
# ntfy priorities; anything else is default.
_PRIORITY = {'error': 'high', 'warning': 'default', 'success': 'default', 'info': 'low'}


def _truthy(raw: str | None, default: bool = False) -> bool:
    text = (raw or '').strip().lower()
    if not text:
        return default
    return text in ('1', 'true', 'yes', 'on')


def apprise_urls() -> list[str]:
    raw = os.getenv('NOTIFY_APPRISE_URLS') or ''
    return [u.strip() for u in raw.replace(';', ',').split(',') if u.strip()]


def ntfy_url() -> str:
    return (os.getenv('NOTIFY_NTFY_URL') or '').strip()


def social_to_bus() -> bool:
    return _truthy(os.getenv('NOTIFY_SOCIAL_TO_BUS'), False)


def configured() -> bool:
    return bool(apprise_urls() or ntfy_url())


def status_summary() -> dict[str, Any]:
    return {
        'configured': configured(),
        'apprise': len(apprise_urls()),
        'ntfy': bool(ntfy_url()),
        'social_to_bus': social_to_bus(),
    }


def _kind_type(kind: str) -> str:
    key = (kind or '').lower()
    if 'error' in key or 'fail' in key or 'malware' in key:
        return 'error'
    if 'warn' in key or 'support' in key or 'request' in key:
        return 'warning'
    if 'done' in key or 'complete' in key or 'added' in key or 'new_game' in key:
        return 'success'
    return 'info'


def _post_apprise(url: str, *, title: str, body: str, kind: str) -> bool:
    resp = safe_request(
        'POST',
        url,
        validator=validate_user_outbound_http_url,
        timeout=TIMEOUT_SECONDS,
        json={'title': title, 'body': body, 'type': _kind_type(kind), 'format': 'text'},
        headers={'Content-Type': 'application/json'},
    )
    return 200 <= resp.status_code < 300


def _post_ntfy(url: str, *, title: str, body: str, kind: str, link: str | None) -> bool:
    headers = {
        'Title': title.encode('ascii', 'replace').decode('ascii')[:200],
        'Priority': _PRIORITY.get(_kind_type(kind), 'default'),
        'Tags': (kind or 'oneirodex')[:60],
    }
    if link:
        headers['Click'] = link[:1024]
    resp = safe_request(
        'POST',
        url,
        validator=validate_user_outbound_http_url,
        timeout=TIMEOUT_SECONDS,
        data=body.encode('utf-8'),
        headers=headers,
    )
    return 200 <= resp.status_code < 300


def _safe_endpoint_origin(url: str) -> str:
    """Return a diagnostic origin without URL userinfo, path, query or fragment."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host:
            return '<invalid endpoint>'
        display_host = f'[{host}]' if ':' in host else host
        port = f':{parsed.port}' if parsed.port is not None else ''
        return f'{parsed.scheme}://{display_host}{port}'
    except (TypeError, ValueError):
        return '<invalid endpoint>'


def emit(*, kind: str, title: str, body: str | None = None, link: str | None = None) -> dict[str, int]:
    """Fan one event out to every configured endpoint. Returns per-channel
    delivered counts; a failure is logged and counted as zero, never raised."""
    sent = {'apprise': 0, 'ntfy': 0}
    if not configured():
        return sent
    text = (body or title or '')[:2000]
    for url in apprise_urls():
        try:
            if _post_apprise(url, title=title, body=text, kind=kind):
                sent['apprise'] += 1
        except Exception as exc:  # noqa: BLE001 -- a dead endpoint must not break the app
            logger.warning('[NOTIFY BUS] apprise %s failed: %s', _safe_endpoint_origin(url), type(exc).__name__)
    topic = ntfy_url()
    if topic:
        try:
            if _post_ntfy(topic, title=title, body=text, kind=kind, link=link):
                sent['ntfy'] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('[NOTIFY BUS] ntfy failed: %s', type(exc).__name__)
    return sent


def publish_admin_event(*, kind: str, title: str, body: str | None = None, link: str | None = None) -> dict[str, int]:
    """Admin alerts: one bus event per alert. The caller already checked the
    ``admin_notify_*`` flag; this just adds the channel."""
    return emit(kind=kind, title=title, body=body, link=link)


def publish_user_event(*, kind: str, title: str, body: str | None = None, link: str | None = None) -> dict[str, int]:
    """Social / member kinds reach the bus only when the operator opted in.
    The caller already applied the member's in-app preference."""
    if (kind or '').lower() in SOCIAL_KINDS and not social_to_bus():
        return {'apprise': 0, 'ntfy': 0}
    if (kind or '').lower() not in SOCIAL_KINDS:
        return {'apprise': 0, 'ntfy': 0}
    return emit(kind=kind, title=title, body=body, link=link)
