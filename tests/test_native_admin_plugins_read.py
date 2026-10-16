from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_plugins_read import create_admin_plugins_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakePlugins:
    def list(self, category=None):
        rows = [{'id': 'sample', 'category': 'tools'}]
        return [row for row in rows if category is None or row['category'] == category]

    def get(self, plugin_id):
        return {'id': plugin_id, 'category': 'tools'} if plugin_id == 'sample' else None


def make_client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-plugins-secret')
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=21, role=role, is_active=True, state=True, is_authenticated=True, session_fingerprint=lambda: 'fp')
    manager = SimpleNamespace(login_view='login.login', blueprint_login_views={}, login_message='Please log in.', login_message_category='message', localize_callback=None, session_protection='basic')
    app = FastAPI()
    app.include_router(create_admin_plugins_router(
        flask_app, find_user=lambda value: user if value == 21 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('21:') else None,
        login_manager=manager, data_access=data or FakePlugins(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '21:fp', '_fresh': True}, 'native-admin-plugins-secret'))
    return client


def test_plugin_catalog_filter_detail_and_not_found():
    client = make_client()
    catalog = client.get('/api/plugins?category=tools')
    detail = client.get('/api/plugins/sample')
    missing = client.get('/api/plugins/missing')
    head = client.head('/api/plugins/sample')

    assert catalog.json() == {'plugins': [{'id': 'sample', 'category': 'tools'}]}
    assert detail.json()['id'] == 'sample'
    assert missing.status_code == 404
    assert head.status_code == 200 and head.content == b''


def test_plugin_catalog_requires_administrator():
    response = make_client(role='user').get('/api/plugins', follow_redirects=False)

    assert response.status_code == 302
