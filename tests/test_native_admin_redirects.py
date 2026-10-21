"""DB-free route compatibility checks for native admin redirects."""
import asyncio
from contextlib import nullcontext
from urllib.parse import urlsplit

import httpx
from flask import Flask, redirect as flask_redirect
from flask_login import LoginManager, UserMixin

from oneirodex.runtime_native.admin_redirects import create_admin_redirect_router
from fastapi import FastAPI


class RedirectUser(UserMixin):
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role

    def session_fingerprint(self):
        return f'{self.id}-fingerprint'

    def get_id(self):
        return f'{self.id}:{self.session_fingerprint()}'


def make_app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='test-admin-redirect-secret',
        SESSION_COOKIE_SECURE=False,
        CSP_ENABLED=False,
        HSTS_SECONDS=0,
    )
    login_manager = LoginManager(flask_app)
    login_manager.login_view = 'login'
    flask_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login')
    users = {7: RedirectUser(7, 'admin'), 8: RedirectUser(8, 'member')}
    adapter = FastAPI()
    adapter.include_router(create_admin_redirect_router(
        flask_app,
        find_user=lambda user_id: users.get(user_id),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        login_manager=login_manager,
        database_scope=lambda _app: nullcontext(),
        filter_exists=lambda filter_id: filter_id == 42,
    ))
    return flask_app, adapter, users


def signed_cookie(flask_app, user):
    return flask_app.session_interface.get_signing_serializer(flask_app).dumps({
        '_user_id': user.get_id(), '_fresh': True,
    })


def fetch(app, path, cookie=None, method='GET'):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://localhost',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path)
    return asyncio.run(perform())


def test_admin_redirect_targets_and_query_compatibility():
    flask_app, app, users = make_app()
    cookie = signed_cookie(flask_app, users[7])
    cases = {
        '/admin/library_tools': '/scan_management?active_tab=tools',
        '/admin/server_logs': '/admin/ops?open=full-log',
        '/admin/system_logs': '/admin/ops?open=full-log',
        '/admin/server_status_page': '/admin/ops',
        '/admin/scan_management': '/scan_management?active_tab=jobs',
        '/admin/scan_management?other=x': '/scan_management?other=x&active_tab=jobs',
        '/admin/scan_management?active_tab=manual&other=x': '/scan_management?active_tab=manual&other=x',
    }

    for path, expected in cases.items():
        response = fetch(app, path, cookie)
        expected_response = flask_redirect(expected, code=302)
        assert response.status_code == 302
        assert response.headers['location'] == expected
        assert response.headers['content-type'] == expected_response.headers['Content-Type']
        assert response.content == expected_response.get_data()
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['vary'] == 'Cookie'


def test_admin_redirect_head_has_empty_body():
    flask_app, app, users = make_app()
    response = fetch(
        app, '/admin/server_status_page', signed_cookie(flask_app, users[7]), method='HEAD',
    )
    assert response.status_code == 302
    assert response.content == b''
    assert response.headers['location'] == '/admin/ops'

    scan_jobs = fetch(
        app, '/admin/scan_management', signed_cookie(flask_app, users[7]), method='HEAD',
    )
    assert scan_jobs.status_code == 302
    assert scan_jobs.content == b''
    assert scan_jobs.headers['location'] == '/scan_management?active_tab=jobs'


def test_get_delete_filter_redirects_admin_to_confirm_and_keeps_guards():
    flask_app, app, users = make_app()
    admin = fetch(app, '/delete_filter/42', signed_cookie(flask_app, users[7]))
    assert admin.status_code == 302
    assert admin.headers['location'] == '/admin/edit_filters'
    assert admin.headers['cache-control'] == 'no-store'
    saved = flask_app.session_interface.get_signing_serializer(flask_app).loads(
        admin.cookies.get('session'), max_age=None,
    )
    assert saved['_flashes'] == [(
        'warning', 'Open Scan Filters and confirm removal there.',
    )]

    head = fetch(app, '/delete_filter/42', signed_cookie(flask_app, users[7]), method='HEAD')
    assert head.status_code == 302
    assert head.headers['location'] == '/admin/edit_filters'
    assert head.content == b''

    anonymous = fetch(app, '/delete_filter/42')
    assert anonymous.status_code == 302
    assert urlsplit(anonymous.headers['location']).path == '/login'
    assert anonymous.headers['content-type'] == 'text/html; charset=utf-8'
    assert len(anonymous.headers.get_list('set-cookie')) == 1
    member = fetch(app, '/delete_filter/42', signed_cookie(flask_app, users[8]))
    assert member.status_code == 302
    assert member.headers['location'] == '/login'


def test_get_delete_filter_missing_id_matches_legacy_not_found_without_deleting():
    flask_app, app, users = make_app()
    cookie = signed_cookie(flask_app, users[7])

    get_response = fetch(app, '/delete_filter/43', cookie)
    head_response = fetch(app, '/delete_filter/43', cookie, method='HEAD')

    assert get_response.status_code == head_response.status_code == 404
    assert get_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert head_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
