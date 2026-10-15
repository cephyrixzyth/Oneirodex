from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.integrations_inventory import (
    create_integrations_inventory_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeInventory:
    def __init__(self):
        self.calls = 0
        self.rows = [{
            'id': 'igdb',
            'name': 'IGDB',
            'category': 'metadata',
            'status': 'configured',
            'configured': True,
            'enabled': None,
            'admin_href': '/admin/integrations#igdb',
            'settings_href': '/admin/igdb_settings',
            'notes': 'Primary game metadata',
        }]

    def inventory(self):
        self.calls += 1
        return self.rows


def make_client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-inventory-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=23, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_integrations_inventory_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 23 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '23' else None,
        login_manager=manager,
        data_access=data if data is not None else FakeInventory(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '23:fp'}, 'native-inventory-secret')
    )
    return client


def test_get_preserves_plain_legacy_payload_and_safe_inventory_projection():
    data = FakeInventory()
    response = make_client(data=data).get('/api/admin/integrations/inventory')

    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        'integrations': data.rows,
        'count': 1,
        'hub_href': '/admin/integrations',
    }
    assert not {'client_secret', 'api_key', 'token', 'password'} & set(data.rows[0])
    assert data.calls == 1


def test_head_has_no_body_but_matches_get_headers():
    data = FakeInventory()
    client = make_client(data=data)
    get_response = client.get('/api/admin/integrations/inventory')
    head_response = client.head('/api/admin/integrations/inventory')

    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == 2


def test_non_admin_is_denied_before_inventory_adapter_runs():
    data = FakeInventory()
    response = make_client(role='user', data=data).get(
        '/api/admin/integrations/inventory', follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    assert data.calls == 0


def test_admin_bearer_without_admin_scope_is_forbidden(monkeypatch):
    from oneirodex.runtime_native import integrations_inventory as native_inventory

    auth = SimpleNamespace(
        user=SimpleNamespace(role='admin', is_authenticated=True),
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(native_inventory, 'request_auth_context', lambda *_args, **_kwargs: auth)
    data = FakeInventory()
    response = make_client(data=data).get('/api/admin/integrations/inventory')

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == 0
