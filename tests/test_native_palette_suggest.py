from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.palette_suggest import create_palette_suggest_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeSuggestions:
    def __init__(self):
        self.calls = []

    def suggest(self, user, limit):
        self.calls.append((user.id, limit))
        return {'recent': [{'uuid': 'g-1', 'name': 'Played'}], 'popular': []}


def _setup(*, authenticated=True):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-palette-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=91, user_id='palette-user', role='user', state=True,
        is_active=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeSuggestions()
    router = create_palette_suggest_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 91 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '91' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set('session', dump_session_cookie(
            {'_user_id': '91:fingerprint', '_fresh': True},
            flask_app.config['SECRET_KEY'],
        ))
    return client, data


def test_palette_suggestions_keep_envelope_limit_and_head_contract():
    client, data = _setup()
    get = client.get('/api/palette/suggest?limit=99')
    head = client.head('/api/palette/suggest?limit=99')

    assert get.status_code == 200
    assert get.json()['ok'] is True
    assert get.json()['recent'][0]['uuid'] == 'g-1'
    assert data.calls == [(91, 12), (91, 12)]
    assert head.status_code == 200
    assert head.content == b''


def test_palette_suggestions_reject_anonymous_without_reading_data():
    client, data = _setup(authenticated=False)
    response = client.get('/api/palette/suggest', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert data.calls == []
