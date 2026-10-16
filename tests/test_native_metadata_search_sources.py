from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.metadata_search_sources import (
    create_metadata_search_sources_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeSources:
    def __init__(self):
        self.reads = 0

    def read(self):
        self.reads += 1
        return {'sources': [{'id': 'steam'}, {'id': 'meta_quest'}]}


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-sources-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=93, user_id='sources-user', role=role, is_active=True,
        state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeSources()
    router = create_metadata_search_sources_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 93 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '93' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '93:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
    ))
    return client, data


def test_metadata_search_sources_preserves_bare_projection_and_head():
    client, data = _client()
    response = client.get('/api/search_metadata/sources')
    head = client.head('/api/search_metadata/sources')

    assert response.status_code == 200
    assert response.json() == {'sources': [{'id': 'steam'}, {'id': 'meta_quest'}]}
    assert data.reads == 2
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_metadata_search_sources_remains_admin_only():
    client, data = _client(role='user')
    response = client.get('/api/search_metadata/sources', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert data.reads == 0
