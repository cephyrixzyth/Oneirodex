from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_art_studio_reads import (
    create_admin_art_studio_read_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeArtStudioReads:
    def stock_catalog(self):
        return [{'id': 'stock-one'}]

    def system_marks_catalog(self):
        return [{'theme': 'default', 'generated': 1}], [{'id': 'nes'}]

    def system_marks_lab(self, *, theme, platform):
        return {'theme': theme, 'platform': platform, 'exists': True}


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-art-studio-read', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_admin_art_studio_read_router(
        flask_app, find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, data_access=FakeArtStudioReads(),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie(
            {'_user_id': '18:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
        ),
    )
    return client


def test_art_studio_stock_keeps_bare_catalog_payload_and_head():
    client = _client()
    response = client.get('/admin/api/art-studio/stock')
    head = client.head('/admin/api/art-studio/stock')
    assert response.status_code == 200
    assert response.json() == {'items': [{'id': 'stock-one'}], 'count': 1}
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_art_studio_system_marks_reads_keep_envelope_and_validate_lab_query():
    client = _client()
    catalog = client.get('/admin/api/art-studio/system-marks')
    missing = client.get('/admin/api/art-studio/system-marks/lab')
    lab = client.get(
        '/admin/api/art-studio/system-marks/lab?theme=default&platform=nes',
    )
    assert catalog.status_code == 200 and catalog.json()['ok'] is True
    assert catalog.json()['items'] == [{'theme': 'default', 'generated': 1}]
    assert missing.status_code == 400 and missing.json()['error_code'] == 'bad_request'
    assert lab.status_code == 200 and lab.json()['ok'] is True
    assert lab.json()['platform'] == 'nes'


def test_art_studio_read_routes_require_admin():
    response = _client(role='user').get('/admin/api/art-studio/stock', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
