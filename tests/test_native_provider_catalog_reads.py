from __future__ import annotations

from contextlib import nullcontext
import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.provider_catalog_reads import (
    create_provider_catalog_reads_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeProviderCatalogData:
    def __init__(self):
        self.artwork_calls = 0
        self.patch_configs = []

    def artwork_providers(self):
        self.artwork_calls += 1
        return [{'id': 'fake-art', 'enabled': False, 'config_hint': 'fake setting'}]

    def patch_catalog(self, config):
        # Capture a copy of config without reading provider registries or paths.
        self.patch_configs.append(dict(config))
        return {
            'module_enabled': config.get('ENABLE_PATCH_CATALOG') == 'true',
            'catalog_path': config.get('PATCH_CATALOG_PATH') or None,
            'providers': [{'id': 'fake-patch', 'enabled': False}],
        }


def _client(*, role='admin', token=None, patch_enabled='true'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-provider-catalog-secret',
        CSP_ENABLED=False,
        ENABLE_PATCH_CATALOG=patch_enabled,
        PATCH_CATALOG_PATH='/private/test/catalog.yaml',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=41,
        user_id='provider-admin',
        name='provider-admin',
        role=role,
        is_active=True,
        state=True,
        is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    data = FakeProviderCatalogData()
    router = create_provider_catalog_reads_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 41 else None,
        find_token=lambda _prefix: token,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '41' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '41:fingerprint', '_fresh': True}
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, flask_app


def test_artwork_provider_list_keeps_legacy_shape_and_uses_adapter():
    client, data, _flask_app = _client()

    response = client.get('/api/providers')

    assert response.status_code == 200
    assert response.json() == {
        'providers': [{'id': 'fake-art', 'enabled': False, 'config_hint': 'fake setting'}]
    }
    assert data.artwork_calls == 1
    assert response.headers.get('X-Content-Type-Options') == 'nosniff'


def test_patch_provider_list_keeps_module_state_fields_and_absolute_path_parity():
    client, data, flask_app = _client()

    response = client.get('/api/patch-catalog/providers')

    assert response.status_code == 200
    assert response.json() == {
        'module_enabled': True,
        'catalog_path': '/private/test/catalog.yaml',
        'providers': [{'id': 'fake-patch', 'enabled': False}],
    }
    assert data.patch_configs == [dict(flask_app.config)]
    # Compatibility preserves the legacy absolute-path field; callers can learn
    # a server-local path from this admin-only endpoint.
    assert response.json()['catalog_path'].startswith('/')


def test_patch_provider_list_preserves_disabled_module_state():
    client, data, _flask_app = _client(patch_enabled='false')

    response = client.get('/api/patch-catalog/providers')

    assert response.status_code == 200
    assert response.json()['module_enabled'] is False
    assert len(data.patch_configs) == 1


def test_provider_catalog_routes_require_admin_before_adapter_reads():
    client, data, _flask_app = _client(role='user')

    artwork = client.get('/api/providers', follow_redirects=False)
    patch_catalog = client.get('/api/patch-catalog/providers', follow_redirects=False)

    assert artwork.status_code == 302
    assert patch_catalog.status_code == 302
    assert data.artwork_calls == 0
    assert data.patch_configs == []


def test_bearer_token_without_admin_scope_is_forbidden_before_adapter_reads():
    secret = 'catalog-read-secret'
    token = SimpleNamespace(
        user_id=41,
        token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        revoked_at=None,
        expires_at=None,
        scopes=[],
    )
    client, data, _flask_app = _client(token=token)
    client.cookies.clear()

    response = client.get('/api/providers', headers={'Authorization': f'Bearer gt_prefix_{secret}'})

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.artwork_calls == 0


def test_provider_catalog_routes_preserve_head_support():
    client, data, _flask_app = _client()

    response = client.head('/api/providers')

    assert response.status_code == 200
    assert response.content == b''
    assert data.artwork_calls == 1
