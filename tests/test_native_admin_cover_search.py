from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_cover_search import create_admin_cover_search_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeCoverSearch:
    def __init__(self):
        self.calls = []

    def game_name(self, game_uuid):
        return 'Found game' if game_uuid == 'found' else None

    def search(self, query, providers, limit):
        self.calls.append(('search', query, providers, limit))
        return {'query': query, 'candidates': [{'provider': 'fake', 'url': 'https://img/1'}], 'errors': []}

    def image_path(self, config):
        return {'path': config['IMAGE_SAVE_PATH'], 'writable': True}

    def batch_search(self, **kwargs):
        self.calls.append(('batch', kwargs))
        return {
            'count': 0, 'games': [],
            'filters': {key: value for key, value in kwargs.items() if key != 'config'},
        }


def _client():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-cover-search', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
        IMAGE_SAVE_PATH='/library/images',
    )
    user = SimpleNamespace(
        id=8, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '8:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    service = FakeCoverSearch()
    app = FastAPI()
    app.include_router(create_admin_cover_search_router(
        flask_app, find_user=lambda uid: user if uid == 8 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '8' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=service,
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, service


def test_single_cover_search_keeps_bare_payload_and_game_lookup():
    client, service = _client()
    response = client.post('/admin/api/covers/search', json={
        'game_uuid': 'found', 'providers': 'steamgriddb,igdb', 'limit': 100,
    })
    assert response.status_code == 200
    assert response.json()['query'] == 'Found game'
    assert response.json()['game_uuid'] == 'found'
    assert response.json()['image_save_path']['writable'] is True
    assert service.calls == [('search', 'Found game', ['steamgriddb', 'igdb'], 20)]


def test_single_cover_search_errors_and_batch_search_bounds():
    client, service = _client()
    missing = client.post('/admin/api/covers/search', json={'game_uuid': 'missing'})
    batch = client.post('/admin/api/covers/batch/search', json={
        'limit_games': 500, 'limit_per_provider': 100, 'system': 'nes',
    })
    assert missing.status_code == 404 and missing.json()['game_uuid'] == 'missing'
    assert batch.status_code == 200 and batch.json()['count'] == 0
    kwargs = service.calls[0][1]
    assert kwargs['limit_games'] == 100
    assert kwargs['limit_per_provider'] == 15
    assert kwargs['platform'] == 'nes'
    assert kwargs['config']['IMAGE_SAVE_PATH'] == '/library/images'
