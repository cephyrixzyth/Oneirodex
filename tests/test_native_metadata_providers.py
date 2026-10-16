from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.metadata_providers_read import (
    create_metadata_providers_read_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
)


class FakeMetadataData:
    def __init__(self):
        self.saved = []

    def read(self):
        return {'providers': {'steam': True}, 'notes': {}}

    def save(self, payload):
        self.saved.append(payload)
        return {'providers': payload.get('providers', payload), 'notes': {}}


def _client():
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-metadata-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=82, user_id='metadata-admin', name='metadata-admin', role='admin',
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeMetadataData()
    router = create_metadata_providers_read_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 82 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '82' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '82:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    cookie = dump_session_cookie(session, flask_app.config['SECRET_KEY'])
    return client, data, cookie, csrf


def test_metadata_provider_put_requires_csrf_before_auth_and_write():
    client, data, cookie, _csrf = _client()
    client.cookies.set('session', cookie)

    response = client.put(
        '/api/admin/integrations/metadata-providers',
        json={'providers': {'steam': False}},
    )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.saved == []


def test_metadata_provider_put_keeps_validated_admin_write_contract():
    client, data, cookie, csrf = _client()
    client.cookies.set('session', cookie)

    response = client.put(
        '/api/admin/integrations/metadata-providers',
        json={'providers': {'steam': False}},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['providers']['steam'] is False
    assert data.saved == [{'providers': {'steam': False}}]
