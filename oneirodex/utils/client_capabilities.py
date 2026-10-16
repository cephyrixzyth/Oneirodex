"""Thin-client capability advertisement (TC-1)."""

from __future__ import annotations

from oneirodex.models import ApiToken
from oneirodex.runtime_native.auth_resolver import token_has_scope

DEVICE_KINDS = frozenset({'companion', 'thin', 'browser'})
DEFAULT_DEVICE_KIND = 'companion'

BROWSE_CAPS = frozenset({'browse', 'browser_play'})
SOCIAL_CAP = 'social'
PRESENCE_CAP = 'presence'
LIFECYCLE_CAPS = frozenset({
    'download',
    'install',
    'update',
    'uninstall',
    'native_play',
})
ALL_LIFECYCLE_DENIES = sorted(LIFECYCLE_CAPS)


def normalize_device_kind(value: str | None) -> str:
    kind = (value or DEFAULT_DEVICE_KIND).strip().lower()
    if kind not in DEVICE_KINDS:
        return DEFAULT_DEVICE_KIND
    return kind


def _token_has_social(token: ApiToken | None) -> bool:
    if token is None:
        return True
    return token.has_scope('read:social')


def _token_has_presence(token: ApiToken | None) -> bool:
    if token is None:
        return True
    return token.has_scope('write:presence')


def _token_has_lifecycle(token: ApiToken | None, user=None) -> bool:
    if token is None or user is None:
        return False
    return token_has_scope(user, token, 'write:download') or token_has_scope(
        user, token, 'write:library'
    )


def resolve_client_capabilities(
    device_kind: str | None,
    *,
    api_token: ApiToken | None = None,
    user=None,
) -> dict:
    """Return allows/denies for the current client seat."""
    kind = normalize_device_kind(device_kind)
    allows: list[str] = sorted(BROWSE_CAPS)
    denies = list(ALL_LIFECYCLE_DENIES)

    if _token_has_social(api_token):
        allows.append(SOCIAL_CAP)
    if _token_has_presence(api_token):
        allows.append(PRESENCE_CAP)

    if kind == 'companion' and _token_has_lifecycle(api_token, user):
        for cap in sorted(LIFECYCLE_CAPS):
            if cap not in allows:
                allows.append(cap)
            if cap in denies:
                denies.remove(cap)

    return {
        'device_kind': kind,
        'allows': allows,
        'denies': denies,
    }


def should_deliver_install_commands(
    device_kind: str | None,
    *,
    api_token: ApiToken | None,
    user=None,
) -> bool:
    """Install/update queue is companion-only and requires download/lifecycle scopes."""
    if api_token is None:
        return False
    if normalize_device_kind(device_kind) != 'companion':
        return False
    return _token_has_lifecycle(api_token, user)
