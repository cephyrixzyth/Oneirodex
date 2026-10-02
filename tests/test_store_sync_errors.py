"""Redacted provider-error catalogue (LIB-04). DB-free; never loads the app factory."""
import json

import pytest
import requests

from oneirodex.utils.api_response import ERROR_CODES
from oneirodex.utils.http_safe import BlockedOutboundUrl
from oneirodex.utils.store_sync_errors import (
    REASONS,
    StoreSyncError,
    StoreSyncPermissionError,
    classify_sync_exception,
    reason_payload,
)

SECRET = 'SECRETKEY0123456789ABCDEF'
URL = f'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={SECRET}&steamid=76561198000000000'


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    response.url = URL
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        return exc
    raise AssertionError('expected an HTTP error')


@pytest.mark.parametrize('status,reason', [
    (401, 'credential_rejected'), (403, 'access_denied'), (429, 'rate_limited'),
    (500, 'upstream_unavailable'), (503, 'upstream_unavailable'), (404, 'invalid_response'),
])
def test_http_errors_become_reasons_without_the_request_url(status, reason):
    exc = _http_error(status)
    assert SECRET in str(exc), 'precondition: requests puts the full URL in the message'
    assert classify_sync_exception(exc) == reason
    assert SECRET not in json.dumps(reason_payload(reason, 'Steam'))


@pytest.mark.parametrize('exc,reason', [
    (requests.ConnectTimeout(f'Max retries exceeded with url: /v0001/?key={SECRET}'), 'network_error'),
    (requests.ConnectionError(f'Max retries exceeded with url: /v0001/?key={SECRET}'), 'network_error'),
    (requests.ReadTimeout('read timed out'), 'network_error'),
    (BlockedOutboundUrl(URL, 'private address'), 'blocked_by_policy'),
    (requests.exceptions.JSONDecodeError('Expecting value', '<html>', 0), 'invalid_response'),
    (ValueError('untyped adapter sentence'), 'invalid_response'),
    (RuntimeError(f'boom {SECRET}'), 'internal_error'),
    (PermissionError('Store ownership sync is disabled by administrator'), 'sync_disabled'),
    (StoreSyncError('GOG rejected the saved token', 'credential_rejected'), 'credential_rejected'),
    (StoreSyncPermissionError('opt-in', 'opt_in_required'), 'opt_in_required'),
    (StoreSyncError('unknown reason keeps ValueError semantics', 'no_such_reason'), 'invalid_response'),
])
def test_other_failures_classify_and_stay_redacted(exc, reason):
    assert classify_sync_exception(exc) == reason
    assert SECRET not in json.dumps(reason_payload(reason, 'Steam'))


def test_typed_errors_keep_the_existing_contracts():
    # Callers that catch ValueError / PermissionError keep working.
    assert isinstance(StoreSyncError('m', 'credential_missing'), ValueError)
    assert isinstance(StoreSyncPermissionError('m', 'sync_disabled'), PermissionError)
    assert str(StoreSyncError('GOG rejected the saved token', 'credential_rejected')) == 'GOG rejected the saved token'


@pytest.mark.parametrize('reason', sorted(REASONS))
def test_every_reason_is_envelope_safe_and_actionable(reason):
    entry = REASONS[reason]
    assert entry.envelope_code in ERROR_CODES
    assert entry.http_status == ERROR_CODES[entry.envelope_code]
    assert entry.action in {'reconnect', 'retry', 'retry_later', 'contact_admin', 'import_csv', 'check_privacy', 'none'}
    assert entry.audience in {'member', 'admin'}
    payload = reason_payload(reason, 'GOG')
    assert '{' not in payload['message'] and payload['reason'] == reason
    assert set(payload) == {'reason', 'message', 'action', 'retryable', 'audience'}


def test_unknown_stored_reason_degrades_to_internal_error():
    assert reason_payload('not-a-reason', 'Epic Games')['reason'] == 'internal_error'
