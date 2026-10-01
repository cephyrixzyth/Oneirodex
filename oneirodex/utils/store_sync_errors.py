"""Redacted, actionable store-sync outcomes (LIB-04).

A provider failure reaches a member or an administrator as a fixed reason code
and a fixed sentence from this catalogue, never as exception text. That is not
fastidiousness: ``requests`` error strings contain the full request URL, and the
Steam owned-games URL carries the household's server key in its query string,
so ``f'Steam sync failed: {exc}'`` handed that key to whichever member's sync
hit an upstream 5xx. Upstream bodies, device-auth JSON, tokens and account IDs
are equally out of bounds.

Each reason says who can fix it (``audience``), what to do (``action``) and
whether trying again unchanged can help (``retryable``). The HTTP status and
envelope ``error_code`` keep the contract the sync routes already had:
PermissionError-shaped refusals are 403, member-fixable problems are 400 and
upstream trouble is 502.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from oneirodex.utils.http_safe import BlockedOutboundUrl

__all__ = [
    'REASONS', 'AUTH_REASONS', 'RECONNECT_CLEARS', 'CONFIG_REASONS', 'StoreSyncError',
    'StoreSyncPermissionError', 'SyncOutcomeError', 'classify_sync_exception',
    'reason_payload', 'rejected_reason',
]


@dataclass(frozen=True)
class Reason:
    envelope_code: str
    http_status: int
    action: str  # reconnect | retry | retry_later | contact_admin | import_csv | check_privacy | none
    retryable: bool
    audience: str  # member | admin
    message: str  # may contain {provider} only


REASONS: dict[str, Reason] = {
    'sync_disabled': Reason('forbidden', 403, 'contact_admin', False, 'admin',
                            'Store ownership sync is disabled by administrator'),
    'opt_in_required': Reason('forbidden', 403, 'contact_admin', False, 'admin',
                              '{provider} live sync is opt-in and is off on this server. CSV import works without it.'),
    'client_package_missing': Reason('bad_request', 400, 'contact_admin', False, 'admin',
                                     '{provider} live sync needs an optional server package the administrator has not installed. CSV import works without it.'),
    'server_key_missing': Reason('bad_request', 400, 'contact_admin', False, 'admin',
                                 '{provider} sync needs a server key the administrator has not configured. CSV import works without it.'),
    'not_connected': Reason('bad_request', 400, 'reconnect', False, 'member',
                            '{provider} account not connected'),
    'credential_missing': Reason('bad_request', 400, 'reconnect', False, 'member',
                                 '{provider} live sync needs a sign-in token. Reconnect with one; CSV import still works.'),
    'credential_rejected': Reason('bad_request', 400, 'reconnect', False, 'member',
                                  '{provider} rejected the saved sign-in (expired or revoked). Reconnect with a fresh one; CSV import still works.'),
    # The member never saved a sign-in; the operator's household one failed.
    'household_credential_rejected': Reason('bad_request', 400, 'contact_admin', True, 'admin',
                                            '{provider} refused the household sign-in your server operator set up (expired or revoked). Ask your administrator to replace it, or reconnect with your own sign-in.'),
    'device_serial_missing': Reason('bad_request', 400, 'reconnect', False, 'member',
                                    '{provider} live sync needs the device serial that comes with the Nile/Heroic sign-in. Reconnect and include it; CSV import still works.'),
    'access_denied': Reason('bad_gateway', 502, 'contact_admin', False, 'admin',
                            '{provider} refused the request. The server key or account permissions may need attention.'),
    'library_not_visible': Reason('bad_request', 400, 'check_privacy', True, 'member',
                                  '{provider} returned no library for this account. If you own games there, make the game list visible to the sign-in and sync again.'),
    'rate_limited': Reason('bad_gateway', 502, 'retry_later', True, 'member',
                           '{provider} is limiting requests right now. Try again later.'),
    'upstream_unavailable': Reason('bad_gateway', 502, 'retry_later', True, 'member',
                                   '{provider} did not answer correctly. Try again later.'),
    'network_error': Reason('bad_gateway', 502, 'retry', True, 'member',
                            '{provider} could not be reached from the server. Try again shortly.'),
    'blocked_by_policy': Reason('bad_gateway', 502, 'contact_admin', False, 'admin',
                                'The server refused to contact {provider} under its outbound network policy.'),
    'invalid_response': Reason('bad_gateway', 502, 'retry_later', True, 'member',
                               '{provider} answered in a way Oneirodex could not read. Try again later; CSV import still works.'),
    'page_limit': Reason('bad_gateway', 502, 'import_csv', False, 'member',
                         '{provider} returned more pages than one sync reads, so the list is incomplete. CSV import can fill the rest.'),
    'names_incomplete': Reason('bad_gateway', 502, 'retry_later', True, 'member',
                               'Every {provider} title was recorded, but some names could not be looked up. Sync again later to fill them in.'),
    'sync_in_progress': Reason('conflict', 409, 'none', True, 'member',
                               'A {provider} sync is already running'),
    'store_busy': Reason('conflict', 409, 'retry', True, 'member',
                         'Another change to your {provider} link is in progress. Try again in a moment.'),
    'not_cancellable': Reason('conflict', 409, 'none', False, 'member',
                              '{provider} sync is a single request and cannot be stopped once it starts'),
    'nothing_to_cancel': Reason('conflict', 409, 'none', False, 'member',
                                'No {provider} sync is running'),
    'cancelled': Reason('conflict', 409, 'retry', True, 'member',
                        '{provider} sync was cancelled before anything was saved'),
    'interrupted': Reason('internal', 500, 'retry', True, 'member',
                          '{provider} sync stopped without finishing (the server restarted or the request was lost). Sync again.'),
    'internal_error': Reason('internal', 500, 'retry', True, 'admin',
                             '{provider} sync failed inside Oneirodex. Try again; if it repeats, report it.'),
}

#: Failures that only a new member sign-in fixes. Retrying unchanged cannot help.
AUTH_REASONS = frozenset({'credential_missing', 'credential_rejected', 'not_connected', 'device_serial_missing'})
#: Failures a member reconnect makes obsolete (their own sign-in replaces the one that failed).
RECONNECT_CLEARS = AUTH_REASONS | {'household_credential_rejected'}
#: Operator configuration problems; once the configuration is fixed they no longer describe the account.
CONFIG_REASONS = frozenset({'sync_disabled', 'opt_in_required', 'client_package_missing', 'server_key_missing'})


def rejected_reason(origin):
    """Which catalogue reason a refused sign-in is, given where it came from."""
    return 'household_credential_rejected' if origin == 'household' else 'credential_rejected'


class StoreSyncError(ValueError):
    """A classified adapter failure. Subclasses ValueError so existing callers
    that catch ValueError keep working; the message stays the adapter's own
    sentence and never includes upstream data."""

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


class StoreSyncPermissionError(PermissionError):
    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


class SyncOutcomeError(Exception):
    """Raised by the job layer (in progress / not cancellable / nothing to cancel)."""

    def __init__(self, reason, job=None):
        super().__init__(reason)
        self.reason = reason
        self.job = job


_INVALID_JSON = tuple(t for t in (
    getattr(requests.exceptions, 'InvalidJSONError', None),
    getattr(requests.exceptions, 'JSONDecodeError', None),
) if t is not None) or (ValueError,)


def _http_reason(status):
    if status in (401,):
        return 'credential_rejected'
    if status == 403:
        return 'access_denied'
    if status == 429:
        return 'rate_limited'
    if status is not None and status >= 500:
        return 'upstream_unavailable'
    return 'invalid_response'


def classify_sync_exception(exc):
    """Map any exception raised by a sync to a catalogue reason. Never inspects
    ``str(exc)`` for anything but typed adapter errors."""
    reason = getattr(exc, 'reason', None)
    if isinstance(exc, (StoreSyncError, StoreSyncPermissionError)) and reason in REASONS:
        return reason
    if isinstance(exc, PermissionError):
        return 'sync_disabled'
    if isinstance(exc, BlockedOutboundUrl):
        return 'blocked_by_policy'
    # resp.json() on a garbled body: requests' JSONDecodeError is also a
    # RequestException, so it must be recognised before the network branch.
    if isinstance(exc, _INVALID_JSON):
        return 'invalid_response'
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, 'response', None)
        return _http_reason(getattr(response, 'status_code', None))
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return 'network_error'
    if isinstance(exc, requests.RequestException):
        return 'network_error'
    if isinstance(exc, ValueError):
        # JSON decode errors from resp.json() and untyped adapter sentences.
        return 'invalid_response'
    return 'internal_error'


def reason_payload(reason, provider_name):
    """JSON-safe description; the only strings are catalogue text."""
    if reason not in REASONS:
        reason = 'internal_error'
    entry = REASONS[reason]
    return {
        'reason': reason,
        'message': entry.message.format(provider=provider_name),
        'action': entry.action,
        'retryable': entry.retryable,
        'audience': entry.audience,
    }
