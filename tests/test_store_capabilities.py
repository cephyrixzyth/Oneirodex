"""Capability contracts independent of provider credentials and databases."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('store_capabilities', Path(__file__).resolve().parents[1]/'oneirodex/utils/store_capabilities.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


def test_unsupported_stores_do_not_gain_fake_operations():
    records = {p['id']: p for p in registry.provider_capabilities()}
    assert {'steam','gog','epic','humble','ea','battlenet','xbox','psn','ubisoft','itch','nintendo'} <= records.keys()
    for key in ['humble','ea','battlenet','ubisoft','itch','nintendo']:
        assert records[key]['capabilities']['library_listing'] == 'unavailable'
        assert records[key]['policy_enabled'] is False
    for p in records.values():
        assert p['account_readiness'] == 'not_checked'
        for operation in ['install','update','launch','cloud_save']:
            assert p['capabilities'][operation] == 'unavailable'
    for key in ['meta_quest', 'playnite']:
        assert records[key]['capabilities']['connect'] == 'unavailable'


@pytest.mark.parametrize('key', ['xbox','psn'])
def test_opt_in_changes_only_the_selected_live_listing(key):
    before = {p['id']: p for p in registry.provider_capabilities()}
    after = {p['id']: p for p in registry.provider_capabilities(unofficial_stores={key})}
    assert before[key]['capabilities']['library_listing'] == 'snapshot'
    assert after[key]['capabilities']['library_listing'] == 'live'
    assert after[key]['capabilities']['csv_import'] == 'snapshot'
    assert all(after[k] == before[k] for k in before if k != key)


def test_disabled_policy_and_mutation_isolation():
    records = registry.provider_capabilities(enabled=False)
    assert all(not p['policy_enabled'] for p in records)
    records[0]['capabilities']['install'] = 'live'
    records[0]['aliases'].append('bad')
    fresh = registry.provider_capabilities()
    assert fresh[0]['capabilities']['install'] == 'unavailable'
    assert fresh[0]['aliases'] == []


def test_route_authentication_and_policy(monkeypatch):
    from flask import Flask
    from flask_login import LoginManager, UserMixin
    from oneirodex.routes_apis import ownership
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='isolated-test-only')
    login = LoginManager(app)
    class User(UserMixin):
        id = 'test-member'
    login.user_loader(lambda user_id: User() if user_id == 'test-member' else None)
    monkeypatch.setattr(ownership, 'is_ownership_sync_enabled', lambda: False)
    monkeypatch.setattr(ownership, 'unofficial_store_opt_in', lambda: frozenset())
    app.add_url_rule('/api/ownership/providers', view_func=ownership.ownership_providers)
    client = app.test_client()
    assert client.get('/api/ownership/providers').status_code == 401
    with client.session_transaction() as session:
        session['_user_id'] = 'test-member'
        session['_fresh'] = True
    response = client.get('/api/ownership/providers')
    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] and body['schema_version'] == 1
    assert len(body['providers']) == 18
    assert all(not p['policy_enabled'] for p in body['providers'])
    assert not {'credential','external_account_id','user_id'} & set().union(*(p.keys() for p in body['providers']))
