from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_image_queue_read import (
    create_admin_image_queue_read_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeQueue:
    def list_queue(self, config, params):
        assert config['IMAGE_SAVE_PATH'] == '/library/images'
        assert params.get('kind') == 'cover'
        return {
            'images': [{'id': 2, 'status': 'pending'}],
            'image_save_path': {'path': '/library/images', 'writable': True},
            'allowed_kinds': ['cover'], 'kind_filter': 'cover',
            'pagination': {
                'page': 1, 'pages': 1, 'per_page': 20, 'total': 1,
                'has_next': False, 'has_prev': False,
            },
        }


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-image-queue', CSP_ENABLED=False,
        IMAGE_SAVE_PATH='/library/images',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=9, user_id='operator', role=role, state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_admin_image_queue_read_router(
        flask_app, find_user=lambda uid: user if uid == 9 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '9' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=FakeQueue(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '9:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
    ))
    return client


def test_image_queue_keeps_bare_payload_and_head_behavior():
    client = _client()
    response = client.get('/admin/api/image_queue_list?kind=cover')
    head = client.head('/admin/api/image_queue_list?kind=cover')
    assert response.status_code == 200
    assert response.json() == {
        'images': [{'id': 2, 'status': 'pending'}],
        'image_save_path': {'path': '/library/images', 'writable': True},
        'allowed_kinds': ['cover'], 'kind_filter': 'cover',
        'pagination': {
            'page': 1, 'pages': 1, 'per_page': 20, 'total': 1,
            'has_next': False, 'has_prev': False,
        },
    }
    assert head.status_code == 200 and head.content == b''


def test_image_queue_requires_admin_session():
    response = _client(role='user').get('/admin/api/image_queue_list', follow_redirects=False)
    assert response.status_code == 403
