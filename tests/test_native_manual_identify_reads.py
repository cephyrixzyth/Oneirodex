from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.manual_identify_reads import create_manual_identify_read_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeManualIdentify:
    def options(self):
        return {'libraries': [{'uuid': 'lib-1'}], 'taxonomies': {'genres': []}, 'categories': [], 'statuses': []}

    def game_state(self, game_uuid):
        return {'game': {'uuid': game_uuid}, 'scan_running': False} if game_uuid == 'game-1' else None


def make_client(data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-manual-identify-read-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role='admin', is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_manual_identify_read_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager, data_access=data or FakeManualIdentify(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-manual-identify-read-secret'))
    return client


def test_options_returns_shared_api_envelope_and_no_store():
    response = make_client().get('/api/admin/manual-identify/options')

    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['libraries'] == [{'uuid': 'lib-1'}]
    assert response.json()['ok'] is True


def test_game_state_returns_not_found_without_leaking_database_details():
    response = make_client().get('/api/admin/manual-identify/missing')

    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'


def test_game_state_keeps_editor_payload():
    response = make_client().get('/api/admin/manual-identify/game-1')

    assert response.status_code == 200
    assert response.json()['game']['uuid'] == 'game-1'
    assert response.json()['scan_running'] is False
