"""DB-free contract checks for the FastAPI IGDB company-role read."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.igdb_company_role import (
    IGDBCompanyRoleData,
    create_igdb_company_role_router,
)


class CompanyRoleData:
    def __init__(self, rows, search_results=None, name_search_results=None):
        self.rows = rows
        self.search_results = search_results or []
        self.name_search_results = name_search_results or []
        self.calls = []
        self.search_calls = []
        self.name_search_calls = []

    def lookup(self, game_id, company_id):
        self.calls.append((game_id, company_id))
        return self.rows

    def search_game_by_id(self, igdb_id):
        self.search_calls.append(igdb_id)
        return self.search_results

    def search_games_by_name(self, game_name, platform_id):
        self.name_search_calls.append((game_name, platform_id))
        if game_name == 'provider-error':
            return {'error': 'Search failed'}
        return self.name_search_results


def make_client(rows, search_results=None, name_search_results=None):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='test-igdb-company-role',
        SESSION_COOKIE_SECURE=False,
        CSP_ENABLED=False,
        HSTS_SECONDS=0,
    )
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=11, role='member', is_active=True, is_authenticated=True,
        session_fingerprint=lambda: 'company-role-fingerprint',
    )
    data = CompanyRoleData(rows, search_results, name_search_results)
    app = FastAPI()
    app.include_router(create_igdb_company_role_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 11 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(app)
    cookie = flask_app.session_interface.get_signing_serializer(flask_app).dumps({
        '_user_id': '11:company-role-fingerprint', '_fresh': True,
    })
    client.cookies.set('session', cookie)
    return client, data


def test_company_role_lookup_preserves_legacy_payload_and_head():
    client, data = make_client([{
        'company': {'name': 'Studio'}, 'developer': True, 'publisher': False,
    }])
    get = client.get('/api/get_company_role?game_igdb_id=123&company_id=44')
    head = client.head('/api/get_company_role?game_igdb_id=123&company_id=44')

    assert get.status_code == 200
    assert get.json() == {
        'game_igdb_id': '123', 'company_id': '44',
        'company_name': 'Studio', 'role': 'Developer',
    }
    assert data.calls == [('123', '44'), ('123', '44')]
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))


def test_company_role_rejects_non_numeric_ids_before_provider_call():
    client, data = make_client([])
    response = client.get('/api/get_company_role?game_igdb_id=123%20OR%201=1&company_id=x')

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert response.json()['error'] == (
        'Invalid input. Both game_igdb_id and company_id must be provided and numeric.'
    )
    assert data.calls == []


def test_company_role_not_found_and_auth_redirect():
    client, _data = make_client([{'company': 'malformed'}])
    response = client.get('/api/get_company_role?game_igdb_id=123&company_id=404')
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'

    client.cookies.clear()
    anonymous = client.get(
        '/api/get_company_role?game_igdb_id=123&company_id=44', follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert urlsplit(anonymous.headers['location']).path == '/login'
    assert parse_qs(urlsplit(anonymous.headers['location']).query)['next'] == [
        '/api/get_company_role?game_igdb_id=123&company_id=44',
    ]


def test_igdb_game_id_search_payload_and_head():
    result = {'id': 123, 'name': 'Sample Game'}
    client, data = make_client([], [result])
    get = client.get('/api/search_igdb_by_id?igdb_id=123')
    head = client.head('/api/search_igdb_by_id?igdb_id=123')

    assert get.status_code == 200
    assert get.json() == result
    assert data.search_calls == ['123', '123']
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))


def test_igdb_game_id_search_rejects_query_injection_before_provider_call():
    client, data = make_client([])
    response = client.get('/api/search_igdb_by_id?igdb_id=123%3B+delete')

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.search_calls == []


def test_igdb_name_search_preserves_payload_first_query_values_and_head():
    result = {'id': 123, 'name': 'Sample Game'}
    client, data = make_client([], name_search_results=[result])
    query = (
        '/api/search_igdb_by_name?name=First&name=Second'
        '&platform_id=invalid&platform_id=6'
    )
    get = client.get(query)
    head = client.head('/api/search_igdb_by_name?name=Sample')
    missing = client.get('/api/search_igdb_by_name')

    assert get.status_code == 200 and get.json() == {'results': [result]}
    assert data.name_search_calls == [
        ('First', 'invalid'), ('Sample', None),
    ]
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
    assert missing.status_code == 400
    assert missing.json()['error_code'] == 'bad_request'


def test_igdb_name_search_provider_errors_and_anonymous_redirect():
    client, data = make_client([])
    failed = client.get('/api/search_igdb_by_name?name=provider-error')
    assert failed.status_code == 502
    assert failed.json()['error_code'] == 'bad_gateway'
    assert data.name_search_calls == [('provider-error', None)]

    client.cookies.clear()
    anonymous = client.get(
        '/api/search_igdb_by_name?name=Sample', follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert urlsplit(anonymous.headers['location']).path == '/login'


def test_igdb_name_search_adapter_builds_optional_platform_filter(monkeypatch):
    from oneirodex.utils import igdb_api

    calls = []
    monkeypatch.setattr(
        igdb_api, 'make_igdb_api_request',
        lambda endpoint, query: calls.append((endpoint, query)) or [],
    )
    data = IGDBCompanyRoleData()

    data.search_games_by_name('Sample Game', '6')
    data.search_games_by_name('Sample Game', 'invalid')

    assert calls[0][0] == 'https://api.igdb.com/v4/games'
    assert 'search "Sample Game";' in calls[0][1]
    assert 'where platforms = (6);' in calls[0][1]
    assert calls[0][1].endswith(' limit 10;')
    assert 'where platforms' not in calls[1][1]
