from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_cover_batch import create_admin_cover_batch_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeCoverBatch:
    def __init__(self):
        self.calls = []

    def path_status(self, config):
        return {'path': config['IMAGE_SAVE_PATH'], 'writable': True}

    def apply(self, app, **kwargs):
        self.calls.append(kwargs)
        return {
            'applied': 1, 'failed': 0, 'results': [{'game_uuid': 'g1'}],
            'policy': [kwargs['policy']],
            'image_save_path': {'path': app.config['IMAGE_SAVE_PATH'], 'writable': True},
        }


def _client():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-cover-batch', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
        IMAGE_SAVE_PATH='/images',
    )
    user = SimpleNamespace(
        id=10, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '10:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    data = FakeCoverBatch()
    app = FastAPI()
    app.include_router(create_admin_cover_batch_router(
        flask_app, find_user=lambda uid: user if uid == 10 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '10' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=data,
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, data


def test_cover_batch_apply_normalizes_filters_and_keeps_raw_result():
    client, data = _client()
    response = client.post('/admin/api/covers/batch/apply', json={
        'game_uuids': 'g1, g2,,', 'limit_games': 500, 'policy': 'igdb_only',
    })
    assert response.status_code == 200
    assert response.json()['applied'] == 1
    assert data.calls[0]['game_uuids'] == ['g1', 'g2']
    assert data.calls[0]['limit_games'] == 100
    assert data.calls[0]['policy'] == 'igdb_only'


def test_artwork_auto_pick_maps_downloaded_filter_and_uses_envelope():
    client, data = _client()
    response = client.post('/admin/api/artwork/auto-pick', json={
        'status': 'downloaded', 'limit': 5,
    })
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert 'Auto-pick finished' in response.json()['message']
    assert data.calls[0]['missing_cover'] is False
    assert data.calls[0]['limit_games'] == 5
    assert data.calls[0]['policy'] == 'best_available'
