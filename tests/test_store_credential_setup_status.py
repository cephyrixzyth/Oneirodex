"""DB-free checks for key-ring readiness and connect error contracts."""
from types import SimpleNamespace

import pytest
from flask import Flask

from oneirodex.routes_apis import ownership
from oneirodex.utils.store_connection_status import _derive
from oneirodex.utils.store_credentials import (
    StoreCredentialKeyUnavailable,
    StoreCredentialMigrationRequired,
)


def _provider(store):
    unofficial = store in {'xbox', 'psn'}
    return {
        'id': store,
        'name': store.title(),
        'authority': 'unofficial_opt_in' if unofficial else 'unofficial',
        'requires_unofficial_opt_in': unofficial,
        'unofficial_opted_in': True,
        'capabilities': {
            'csv_import': 'snapshot',
            'file_import': 'unavailable',
            'library_listing': 'live',
        },
    }


def _env(*, household=(), refresh_writes=(), keyring=False):
    return {
        'enabled': True,
        'steam_key': True,
        'household': {store: store in household for store in ('gog', 'epic', 'amazon', 'xbox', 'psn')},
        'household_refresh_persists': {
            store: store in refresh_writes for store in ('gog', 'epic', 'amazon', 'xbox', 'psn')
        },
        'credential_keyring': keyring,
        'packages': {'xbox': True, 'psn': True},
    }


@pytest.mark.parametrize('store', ['gog', 'epic', 'amazon', 'xbox', 'psn'])
def test_unlinked_token_store_signals_key_setup_before_token_submission(store):
    entry = _derive(_provider(store), None, None, None, _env(), None)

    assert entry['state'] == 'not_configured'
    assert entry['setup'] == {'ready': False, 'missing': 'credential_keyring'}
    assert entry['actions'][0] == 'connect'


@pytest.mark.parametrize('store', ['epic', 'psn'])
def test_household_credentials_without_refresh_writes_remain_usable(store):
    entry = _derive(
        _provider(store), None, None, None,
        _env(household={store}), None,
    )

    assert entry['state'] == 'not_connected'
    assert entry['setup'] == {'ready': True, 'missing': None}
    assert entry['credential']['keyring_available'] is False
    assert entry['actions'][0] == 'connect'


@pytest.mark.parametrize('store', ['gog', 'amazon'])
def test_access_only_household_paths_remain_usable_without_keyring(store):
    entry = _derive(
        _provider(store), None, None, None,
        _env(household={store}), None,
    )

    assert entry['state'] == 'not_connected'
    assert entry['setup'] == {'ready': True, 'missing': None}
    assert entry['credential']['keyring_available'] is False


@pytest.mark.parametrize('store', ['gog', 'amazon', 'xbox'])
def test_household_paths_that_persist_refreshes_require_keyring(store):
    entry = _derive(
        _provider(store), None, None, None,
        _env(household={store}, refresh_writes={store}), None,
    )

    assert entry['state'] == 'not_configured'
    assert entry['setup']['missing'] == 'credential_keyring'


@pytest.mark.parametrize(
    'error,expected_reason',
    [
        (StoreCredentialKeyUnavailable('private keyring path'), 'credential_storage_unavailable'),
        (StoreCredentialMigrationRequired('legacy credential value'), 'credential_migration_required'),
    ],
)
def test_connect_errors_use_redacted_storage_setup_contract(monkeypatch, error, expected_reason):
    app = Flask(__name__)
    monkeypatch.setattr(ownership, 'current_user', SimpleNamespace(id=42))
    monkeypatch.setattr(ownership, 'is_ownership_sync_enabled', lambda: True)
    monkeypatch.setattr(
        ownership,
        'exclusive_link_change',
        lambda user_id, store, action, connect: connect(),
    )

    def fail_connect():
        raise error

    with app.test_request_context('/api/ownership/gog'):
        response, status = ownership._connect_response('gog', fail_connect)

    payload = response.get_json()
    assert status == 400
    assert payload['detail']['reason'] == expected_reason
    assert payload['error_code'] == 'bad_request'
    assert 'private keyring path' not in str(payload)
    assert 'legacy credential value' not in str(payload)
