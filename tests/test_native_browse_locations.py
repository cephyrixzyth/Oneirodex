from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.browse_locations import create_browse_locations_router
from oneirodex.runtime_native.session_compat import dump_session_cookie

BASE = os.path.abspath(os.path.join(os.sep, 'allowed'))
SUB = os.path.join(BASE, 'sub')


class FakeBrowseLocationsData:
    def __init__(self):
        self.calls = []
        self.root = {'id': 'main', 'path': BASE, 'label': 'Main library'}
        self.entries = {
            BASE: [{'name': 'sub', 'isDir': True, 'ext': None, 'size': None}],
            SUB: [{'name': 'game.rom', 'isDir': False, 'ext': 'rom', 'size': 8}],
        }

    def roots(self, _app):
        return [self.root]

    def root_availability(self, root):
        return {**root, 'exists': True, 'readable': True, 'writable': False}

    def resolve_root(self, root_id, _app):
        self.calls.append(('resolve_root', root_id))
        return self.root if root_id == 'main' else None

    def allowed_bases(self, _app):
        return [BASE]

    def is_safe_path(self, path, bases, _logger):
        self.calls.append(('safe', path, tuple(bases)))
        return (path == BASE or path.startswith(BASE + os.sep), None)

    def join(self, base, child):
        return os.path.abspath(os.path.join(base, child))

    def absolute(self, path):
        return os.path.abspath(path)

    def directory_exists(self, path):
        return path in self.entries

    def list_directory(self, path):
        self.calls.append(('list', path))
        return self.entries[path]

    def parent(self, path):
        return os.path.dirname(path)

    def relative(self, path, base):
        return os.path.relpath(path, base)

    def is_parent_relative(self, relative):
        return relative == os.pardir or relative.startswith(os.pardir + os.sep)


@pytest.fixture
def runtime():
    flask_app = Flask('browse-locations-test')
    flask_app.config.update(
        SECRET_KEY='browse-locations-secret',
        SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True,
        BASE_FOLDER_POSIX=BASE,
        BASE_FOLDER_WINDOWS=BASE,
    )
    user = SimpleNamespace(
        id=7, role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fp',
    )
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: user if identity == '7:fp' else None)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeBrowseLocationsData()
    app = FastAPI()
    app.include_router(create_browse_locations_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: user if identity == '7:fp' else None,
        login_manager=manager,
        data_access=data,
    ))
    cookie = dump_session_cookie(
        {'_user_id': '7:fp', '_fresh': True}, 'browse-locations-secret',
    )
    return app, flask_app, data, cookie


def _request(app, path, *, cookie=None, method='GET'):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, follow_redirects=False)

    return asyncio.run(perform())


def test_roots_requires_admin_and_returns_availability(runtime):
    app, _flask_app, _data, cookie = runtime

    response = _request(app, '/api/library_roots', cookie=cookie)

    assert response.status_code == 200
    payload = response.json()
    assert payload['roots'] == [{
        'id': 'main', 'path': BASE, 'label': 'Main library',
        'exists': True, 'readable': True, 'writable': False,
    }]
    assert payload['ok'] is True
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_browse_roots_and_first_query_value(runtime):
    app, _flask_app, data, cookie = runtime

    response = _request(app, '/api/browse_folders_ss?root=main&root=unknown', cookie=cookie)

    assert response.status_code == 200
    assert response.json() == [{'name': 'sub', 'isDir': True, 'ext': None, 'size': None}]
    assert ('resolve_root', 'main') in data.calls
    assert ('list', BASE) in data.calls


def test_browse_path_traversal_is_denied_before_listing(runtime):
    app, _flask_app, data, cookie = runtime

    response = _request(app, '/api/browse_folders_ss?path=..%2Fsecret', cookie=cookie)

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert not any(call[0] == 'list' for call in data.calls)


def test_browse_absolute_path_reports_resolved_location_and_head_is_bodyless(runtime):
    app, _flask_app, _data, cookie = runtime

    response = _request(
        app, f'/api/browse_folders_ss?{httpx.QueryParams({"abs_path": SUB})}', cookie=cookie,
    )
    head = _request(app, '/api/library_roots', cookie=cookie, method='HEAD')

    assert response.status_code == 200
    assert response.json()['resolved_path'] == 'sub/'
    assert response.json()['outside_base'] is False
    assert response.json()['absolute_path'] == SUB
    assert head.status_code == 200
    assert head.content == b''


def test_browse_rejects_unknown_root_and_anonymous_user(runtime):
    app, _flask_app, _data, cookie = runtime

    unknown = _request(app, '/api/browse_folders_ss?root=missing', cookie=cookie)
    anonymous = _request(app, '/api/library_roots')

    assert unknown.status_code == 404
    assert anonymous.status_code == 302
    assert anonymous.headers['location'] == '/login?next=%2Fapi%2Flibrary_roots'
