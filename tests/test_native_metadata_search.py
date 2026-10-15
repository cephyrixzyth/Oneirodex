from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.metadata_search import create_metadata_search_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeMetadataSearch:
    def __init__(self):
        self.calls = []

    def search(self, source, name, *, limit, include_software, config):
        self.calls.append((source, name, limit, include_software, config.get('RAWG_API_KEY')))
        return {
            'source': source,
            'results': [{'name': name}],
            'ownership_only': source in ('meta_quest', 'epic'),
        }


def _client(*, role='admin', authenticated=True):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-metadata-search-secret',
        CSP_ENABLED=False,
        RAWG_API_KEY='rawg-test-key',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=94, user_id='metadata-search-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeMetadataSearch()
    router = create_metadata_search_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 94 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '94' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set('session', dump_session_cookie(
            {'_user_id': '94:fingerprint', '_fresh': True},
            flask_app.config['SECRET_KEY'],
        ))
    return client, data


def test_metadata_search_keeps_alias_query_bounds_and_bare_payload():
    client, data = _client()
    response = client.get(
        '/api/search_metadata?name=%20Doom%20&source=moby&limit=99&include_software=0'
    )

    assert response.status_code == 200
    assert response.json()['source'] == 'mobygames'
    assert response.json()['results'] == [{'name': 'Doom'}]
    assert data.calls == [('mobygames', 'Doom', 20, False, 'rawg-test-key')]


def test_metadata_search_validation_and_admin_gate_precede_provider_call():
    client, data = _client()
    missing_name = client.get('/api/search_metadata?source=steam')
    unsupported = client.get('/api/search_metadata?name=Doom&source=unknown')
    member, member_data = _client(role='user')
    denied = member.get('/api/search_metadata?name=Doom&source=steam', follow_redirects=False)

    assert missing_name.status_code == 400
    assert missing_name.json()['error_code'] == 'bad_request'
    assert unsupported.status_code == 400
    assert len(unsupported.json()['sources']) == 9
    assert denied.status_code == 302
    assert data.calls == []
    assert member_data.calls == []


def test_metadata_search_head_preserves_response_length():
    client, _data = _client()
    get = client.get('/api/search_metadata?name=Quest&source=meta')
    head = client.head('/api/search_metadata?name=Quest&source=meta')

    assert get.status_code == 200
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
