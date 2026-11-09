"""Real Chromium lifecycle checks; requires optional Playwright/browser tooling.

These are synthetic worker fixtures, not full app-account or headset acceptance.
"""
import pytest

from tests.fixtures.browser_workers import exercise_worker_upgrade, exercise_first_load_logout


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def browser_tooling():
    pytest.importorskip('playwright.sync_api', reason='Browser integration fixture requires Playwright')


def test_exact_legacy_worker_controls_browser_and_retains_parent_fixture_offline():
    result = exercise_worker_upgrade(legacy_only=True)
    assert result['legacy_controlled'] is True
    assert 'adult-fixture' in result['offline_dom']
    assert result['offline_catalog']['titles'] == ['restricted-fixture-title']


@pytest.mark.parametrize('root_preinstalled,legacy_scope,query,logout', [
    (False, '/vr', '', 'button'),
    (True, '/vr', '?v=old', 'link'),
    (True, '/vr/', '', 'button'),
    (False, '/vr/', '?v=old', 'link'),
])
def test_current_startup_retires_owned_legacy_control_and_private_cache(
    root_preinstalled, legacy_scope, query, logout,
):
    result = exercise_worker_upgrade(
        root_preinstalled=root_preinstalled, legacy_scope=legacy_scope,
        query=query, logout=logout,
    )
    assert result['offline_catalog_after_logout'] == {'network_failed': True}
    assert result['safe_control_policy'] in {'od-vr-retired', 'od-privacy-claim'}
    assert result['controller_after_navigation'] == '/sw.js'
    assert '/vr' not in result['registration_scopes']
    assert '/vr/' not in result['registration_scopes']
    assert '/unrelated/' in result['registration_scopes']
    assert result['unrelated_cache_body'] == 'unrelated-data'
    entries = result['cache_entries']
    assert not any(item['cache'] == 'oneirodex-vr-v1' for item in entries)
    assert any(item['path'] == '/static/js/fixture.js?v=1' for item in entries)
    assert not any(item['path'].startswith(('/api/', '/vr', '/static/library/images/')) for item in entries)
    assert not any(item['path'] == '/static/js/fixture.js' for item in entries)
    assert result['caches_after_logout'] == ['unrelated-fixture']
    assert result['offline_shell_before_logout'] == 'Offline fixture'
    assert 'adult-fixture' not in result['offline_dom_after_logout']
    assert 'restricted-fixture-title' not in result['offline_dom_after_logout']


def test_old_inflight_response_finishes_before_privacy_boundary_is_released():
    result = exercise_worker_upgrade(root_preinstalled=True, delayed=True)
    assert result['ready_while_old_fetch_pending'] is False
    assert result['delayed_response']['identity'] == 'adult-fixture'
    assert result['ready'] is True
    assert result['safe_control_policy'] in {'od-vr-retired', 'od-privacy-claim'}
    assert result['controller_after_navigation'] == '/sw.js'
    assert not any(item['cache'] == 'oneirodex-vr-v1' for item in result['cache_entries'])
    assert result['offline_catalog_after_logout'] == {'network_failed': True}


@pytest.mark.parametrize('unsupported', [False, True])
def test_first_load_and_logout_purge_without_prior_controller(unsupported):
    result = exercise_first_load_logout(unsupported=unsupported)
    assert result == {'ready': True, 'caches': ['unrelated-fixture']}


def test_failed_worker_update_does_not_release_private_read_gate():
    result = exercise_worker_upgrade(update_failure=True)
    assert result['ready'] is False
    assert result['controller'].endswith('/vr/sw.js')


@pytest.mark.parametrize('root_failure', ['reject', 'hang'])
def test_optional_root_install_failure_does_not_block_uncontrolled_browser(root_failure):
    result = exercise_first_load_logout(root_failure=root_failure)
    assert result == {'ready': True, 'caches': ['unrelated-fixture']}


def test_optional_root_install_failure_does_not_block_acknowledged_retirement():
    result = exercise_worker_upgrade(root_failure='reject')
    assert result['ready'] is True
