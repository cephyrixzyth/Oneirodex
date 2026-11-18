"""DB-free checks for key-ring readiness and connect error contracts."""
import pytest

from oneirodex.utils.store_connection_status import _derive


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


