from __future__ import annotations

import hashlib
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.artwork_provider_search import (
    create_artwork_provider_search_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.utils.providers import ProviderDisabledError


class FakeResult:
    def to_dict(self):
        return {'id': 'art-1', 'url': 'https://images.invalid/art.jpg'}


class FakeProvider:
    def __init__(self, provider_id, *, enabled=True, fail=None):
        self.id = provider_id
        self.enabled = enabled
        self.fail = fail
        self.calls = []

    def is_enabled(self):
        return self.enabled

    def config_hint(self):
        return 'configure test credentials'

    def search_covers(self, query, *, limit):
        self.calls.append(('covers', query, limit))
        self._raise_if_needed()
        return [FakeResult()]

    def search_artwork(self, query, *, limit, art_kind):
        self.calls.append(('artwork', query, limit, art_kind))
        self._raise_if_needed()
        return [FakeResult()]

    def _raise_if_needed(self):
        if isinstance(self.fail, Exception):
            raise self.fail


class FakeSearchData:
    def __init__(self, *, disabled=(), failures=None):
        self.providers = {
            provider_id: FakeProvider(
                provider_id,
                enabled=provider_id not in disabled,
                fail=(failures or {}).get(provider_id),
            )
            for provider_id in ('steamgriddb', 'igdb', 'giantbomb', 'meta_quest')
        }
        self.pc_calls = []

    def provider(self, provider_id):
        return self.providers[provider_id]

    def pcgamingwiki(self, query):
        self.pc_calls.append(query)
        return {'query': query, 'results': [{'title': 'Example'}]}


def _client(*, role='admin', authenticated=True, data=None, token_scopes=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-artwork-search-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=94, user_id='artwork-search-user', role=role, is_active=True,
        state=True, is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = data or FakeSearchData()
    token = None
    if token_scopes is not None:
        token = SimpleNamespace(
            user_id=94, token_hash=hashlib.sha256(b'artwork-secret').hexdigest(),
            token_prefix='artwork-prefix', scopes=token_scopes, revoked_at=None,
            expires_at=None, last_used_at=None,
        )
    router = create_artwork_provider_search_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 94 else None,
        find_token=lambda prefix: token if token and prefix == token.token_prefix else None,
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
    if token_scopes is not None:
        client.headers['Authorization'] = 'Bearer gt_artwork-prefix_artwork-secret'
    return client, data


def test_artwork_provider_search_aliases_and_legacy_shapes():
    client, data = _client()
    sgdb = client.get('/api/providers/steamgriddb/search?query=%20Doom%20&limit=90&kind=logo')
    igdb = client.get('/api/providers/igdb/search?q=Zelda&limit=invalid')
    giantbomb = client.get('/api/providers/giantbomb/search?q=Metroid')
    quest = client.get('/api/providers/meta_quest/search?q=Quest')
    wiki = client.get('/api/providers/pcgamingwiki/search?query=%20Half-Life%202%20')

    assert sgdb.status_code == 200
    assert sgdb.json() == {
        'provider': 'steamgriddb', 'query': 'Doom', 'image_type': 'logo',
        'results': [{'id': 'art-1', 'url': 'https://images.invalid/art.jpg'}],
    }
    assert data.providers['steamgriddb'].calls == [('artwork', 'Doom', 50, 'logo')]
    assert igdb.json()['query'] == 'Zelda'
    assert data.providers['igdb'].calls == [('covers', 'Zelda', 20)]
    assert giantbomb.json()['provider'] == 'giantbomb'
    assert quest.json()['ownership_only'] is True
    assert wiki.json() == {'query': 'Half-Life 2', 'results': [{'title': 'Example'}]}
    assert data.pc_calls == ['Half-Life 2']


def test_artwork_provider_search_validation_and_admin_gate_precede_adapter():
    client, data = _client()
    missing = client.get('/api/providers/igdb/search?q=%20')
    invalid_kind = client.get('/api/providers/steamgriddb/search?q=Doom&image_type=screenshot')
    member, member_data = _client(role='user')
    denied = member.get('/api/providers/igdb/search?q=Doom', follow_redirects=False)
    wiki_member = member.get('/api/providers/pcgamingwiki/search?q=Doom')

    assert missing.status_code == 400
    assert missing.json()['error_code'] == 'bad_request'
    assert invalid_kind.status_code == 400
    assert invalid_kind.json()['error'] == 'image_type must be cover, logo, or hero'
    assert denied.status_code == 302
    assert member_data.providers['igdb'].calls == []
    assert wiki_member.status_code == 200
    assert member_data.pc_calls == ['Doom']
    assert data.providers['igdb'].calls == []
    assert data.providers['steamgriddb'].calls == []


def test_artwork_provider_disabled_and_provider_error_shapes():
    data = FakeSearchData(disabled=('steamgriddb', 'meta_quest'), failures={
        'igdb': RuntimeError('upstream unavailable'),
        'giantbomb': ProviderDisabledError('giantbomb', 'provider disabled'),
    })
    client, _ = _client(data=data)
    sgdb = client.get('/api/providers/steamgriddb/search?q=Doom')
    quest = client.get('/api/providers/meta_quest/search?q=Quest')
    igdb = client.get('/api/providers/igdb/search?q=Doom')
    giantbomb = client.get('/api/providers/giantbomb/search?q=Doom')

    assert (sgdb.status_code, sgdb.json()['error'], sgdb.json()['provider']) == (
        503, 'SteamGridDB is not configured. Set STEAMGRIDDB_API_KEY.', 'steamgriddb'
    )
    assert (quest.status_code, quest.json()['hint']) == (
        503, 'configure test credentials'
    )
    assert (igdb.status_code, igdb.json()['error_code'], igdb.json()['provider']) == (
        502, 'bad_gateway', 'igdb'
    )
    assert (giantbomb.status_code, giantbomb.json()['error'], giantbomb.json()['provider']) == (
        503, 'provider disabled', 'giantbomb'
    )


def test_artwork_provider_search_head_and_login_required():
    client, _data = _client()
    get = client.get('/api/providers/igdb/search?q=Doom')
    head = client.head('/api/providers/igdb/search?q=Doom')
    anonymous, anon_data = _client(authenticated=False)
    denied = anonymous.get('/api/providers/pcgamingwiki/search?q=Doom', follow_redirects=False)

    assert get.status_code == head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
    assert denied.status_code == 302
    assert anon_data.pc_calls == []


def test_artwork_provider_admin_token_requires_admin_scope():
    client, data = _client(token_scopes=['read:library'])
    client.cookies.clear()
    denied = client.get('/api/providers/igdb/search?q=Doom')

    assert denied.status_code == 403
    assert denied.json()['error_code'] == 'forbidden'
    assert denied.json()['error'] == 'This token does not have the admin scope'
    assert data.providers['igdb'].calls == []
