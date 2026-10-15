from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.launcher_import_reads import create_launcher_import_read_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


def test_authenticated_launcher_format_catalogue_is_returned_as_api_envelope():
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-launcher-read-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role='user', is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_launcher_import_read_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('7:') else None,
        login_manager=manager,
        data_access=SimpleNamespace(formats=lambda: [{'id': 'fixture', 'name': 'Fixture', 'store': 'playnite'}]),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-launcher-read-secret'))

    response = client.get('/api/imports/launchers')

    assert response.status_code == 200
    assert response.json()['launchers'][0]['id'] == 'fixture'
    assert response.json()['ok'] is True
