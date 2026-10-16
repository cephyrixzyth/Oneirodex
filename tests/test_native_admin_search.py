from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_search import create_admin_search_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeSearchData:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [{'uuid': 'g-1', 'name': 'Alpha Quest', 'full_disk_path': '/games/alpha'}]


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-search-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=81, user_id='search-user', name='search-admin', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeSearchData()
    router = create_admin_search_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 81 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '81' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set(
        'session',
        dump_session_cookie(
            {'_user_id': '81:fingerprint', '_fresh': True},
            flask_app.config['SECRET_KEY'],
        ),
    )
    return client, data


def test_admin_search_keeps_bare_list_contract_and_path_projection():
    client, data = _client()
    response = client.get('/api/admin/games_search?q=%20Alpha%20')

    assert response.status_code == 200
    assert response.json() == [
        {'uuid': 'g-1', 'name': 'Alpha Quest', 'full_disk_path': '/games/alpha'},
    ]
    assert data.queries == ['Alpha']


def test_admin_search_empty_and_oversize_queries_keep_responses():
    client, data = _client()

    assert client.get('/api/admin/games_search').json() == []
    too_long = client.get('/api/admin/games_search', params={'q': 'x' * 101})

    assert too_long.status_code == 400
    assert too_long.json()['error_code'] == 'bad_request'
    assert data.queries == []


def test_non_admin_cannot_search_full_disk_paths():
    client, data = _client(role='user')
    response = client.get('/api/admin/games_search?q=Alpha', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert data.queries == []
