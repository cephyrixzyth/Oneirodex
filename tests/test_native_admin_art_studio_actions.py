from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_art_studio_actions import (
    create_admin_art_studio_action_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeActions:
    def __init__(self):
        self.calls = []

    def generate(self, body, package_root):
        self.calls.append(('generate', body.title, body.title_scale, package_root))
        return {'pack_id': 'abc123', 'files': ['tile_400x600.webp']}

    def generate_stock(self, ids, fmt, package_root):
        self.calls.append(('stock', ids, fmt, package_root))
        return {'generated': [], 'count': 0}

    def download(self, pack_id, package_root):
        self.calls.append(('download', pack_id, package_root))
        return b'zip-bytes'

    def generate_system_marks(self, **kwargs):
        self.calls.append(('system-marks', kwargs))
        return {'generated': 0, 'skipped': 1, 'errors': [], 'count': 1, 'results': []}

    def apply(self, app, pack_id, mode, game_uuid, library_uuid, filename):
        self.calls.append(('apply', pack_id, mode, game_uuid, library_uuid, filename))
        return {'mode': mode, 'game_uuid': game_uuid, 'pack_id': pack_id}

    def batch_generate(self, app, body):
        self.calls.append(('batch-generate', body))
        return {'applied': 1, 'failed': 0, 'results': [], 'errors': []}


def _client():
    flask_app = Flask(__name__)
    flask_app.root_path = '/app/oneirodex'
    flask_app.config.update(
        SECRET_KEY='native-art-actions', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=18, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    actions = FakeActions()
    events = []
    app = FastAPI()
    app.include_router(create_admin_art_studio_action_router(
        flask_app, find_user=lambda uid: user if uid == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        actions=actions, event_logger=lambda *args: events.append(args),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, actions, events


def test_art_pack_generation_preserves_status_and_preview_url():
    client, actions, events = _client()
    response = client.post('/admin/api/art-studio/generate', json={
        'title': 'Game cover', 'title_scale': 0.8,
    })
    assert response.status_code == 201
    assert response.json()['preview_url'] == '/static/library/generated/abc123/tile_400x600.webp'
    assert actions.calls[0][0:3] == ('generate', 'Game cover', 0.8)
    assert events and 'abc123' in events[0][0]


def test_stock_pack_generation_normalizes_ids_and_format():
    client, actions, _events = _client()
    response = client.post('/admin/api/art-studio/stock/generate', json={
        'ids': 'nes, snes,,', 'format': 'bmp',
    })
    assert response.status_code == 201
    assert response.json()['count'] == 0
    assert actions.calls[0][0:3] == ('stock', ['nes', 'snes'], 'webp')


def test_art_pack_download_is_an_attachment_and_validates_pack_id():
    client, actions, _events = _client()
    response = client.get('/admin/api/art-studio/download/abc123')
    assert response.status_code == 200 and response.content == b'zip-bytes'
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['content-disposition'] == 'attachment; filename="oneirodex-art-abc123.zip"'
    assert actions.calls[0][0:2] == ('download', 'abc123')


def test_system_mark_generation_preserves_validation_and_uses_fake_adapter():
    client, actions, events = _client()
    response = client.post('/admin/api/art-studio/system-marks/generate', json={
        'themes': 'default', 'platforms': 'nes', 'limit': '1', 'prompt': 'a cabinet mark',
    })
    assert response.status_code == 201
    assert response.json()['generated'] == 0
    assert actions.calls[0][0] == 'system-marks'
    assert actions.calls[0][1]['themes'] == ['default']
    assert actions.calls[0][1]['platforms'] == ['nes']
    assert actions.calls[0][1]['limit'] == 1
    assert actions.calls[0][1]['prompt'] == 'a cabinet mark'
    assert events


def test_system_mark_prompt_override_requires_one_theme_and_platform():
    client, actions, _events = _client()
    response = client.post('/admin/api/art-studio/system-marks/generate', json={
        'themes': ['default', 'arcade'], 'platforms': ['nes'], 'prompt': 'custom',
    })
    assert response.status_code == 400
    assert actions.calls == []


def test_art_studio_apply_and_batch_alias_keep_validations_and_results():
    client, actions, events = _client()
    missing = client.post('/admin/api/art-studio/apply', json={'pack_id': 'pack'})
    applied = client.post('/admin/api/art-studio/apply', json={
        'pack_id': 'pack', 'mode': 'game', 'game_uuid': 'g1',
    })
    batch = client.post('/admin/api/art-studio/apply-batch', json={'limit_games': 2})
    alias = client.post('/admin/api/art-studio/batch-generate', json={'limit': 3})
    assert missing.status_code == 400
    assert applied.status_code == 200 and applied.json()['pack_id'] == 'pack'
    assert batch.status_code == 200 and batch.json()['applied'] == 1
    assert alias.status_code == 200 and alias.json()['failed'] == 0
    assert [row[0] for row in actions.calls] == ['apply', 'batch-generate', 'batch-generate']
    assert events
