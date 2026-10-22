from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect, request as flask_request

from oneirodex.runtime_native.admin_themes_read import create_admin_themes_read_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeThemeInventory:
    def __init__(self):
        self.calls = []
        self.write_calls = []
        self.reset_result = (True, 'Default theme reset and 2 preset themes installed. Pick a theme under Preferences.')

    def payload(self, _app, user):
        self.calls.append(user.id)
        return {
            'themes': [{'folder': 'default', 'name': 'Default'}],
            'default_theme': {'name': 'Default'},
            'active_theme': 'default',
        }

    def upload(self, _app, user, filename, content):
        self.write_calls.append(('upload', user.id, filename, content))
        return {'status': 'uploaded', 'theme': {'name': 'Aurora'}}, None

    def delete(self, _app, user, theme_name):
        self.write_calls.append(('delete', user.id, theme_name))
        return {'status': 'deleted', 'theme_name': theme_name}, None

    def reset(self, _app, user):
        self.write_calls.append(('reset', user.id))
        return self.reset_result


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-themes-read-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=95, user_id='theme-user', role=role, is_active=True,
        state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeThemeInventory()
    router = create_admin_themes_read_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 95 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '95' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '95:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
    ))
    return client, data


def test_admin_theme_inventory_preserves_envelope_and_head():
    client, data = _client()
    get = client.get('/api/admin/themes')
    head = client.head('/api/admin/themes')

    assert get.status_code == 200
    assert get.json()['ok'] is True
    assert get.json()['themes'][0]['folder'] == 'default'
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
    assert data.calls == [95, 95]


def test_member_cannot_read_admin_theme_inventory():
    client, data = _client(role='user')
    response = client.get('/api/admin/themes', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert data.calls == []


def test_theme_writes_require_csrf_before_data_access():
    client, data = _client()
    response = client.delete('/api/admin/themes/custom')
    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.write_calls == []


def test_theme_upload_and_delete_use_native_adapter_after_csrf():
    client, data = _client()
    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))
    upload = client.post(
        '/api/admin/themes', files={'theme_zip': ('theme.zip', b'fake zip payload')},
        headers={'X-CSRFToken': csrf},
    )
    deleted = client.delete('/api/admin/themes/custom', headers={'X-CSRFToken': csrf})
    assert upload.status_code == 200
    assert upload.json()['status'] == 'uploaded'
    assert deleted.status_code == 200
    assert deleted.json()['theme_name'] == 'custom'
    assert data.write_calls == [
        ('upload', 95, 'theme.zip', b'fake zip payload'), ('delete', 95, 'custom'),
    ]


def test_default_theme_reset_preserves_json_contract_and_actor():
    client, data = _client()
    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))

    response = client.post('/admin/themes/reset', json={}, headers={'X-CSRFToken': csrf})

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['status'] == 'reset'
    assert response.json()['message'].startswith('Default theme reset')
    assert data.write_calls == [('reset', 95)]


def test_default_theme_reset_checks_csrf_before_auth_and_redacts_filesystem_errors():
    client, data = _client()
    missing_csrf = client.post('/admin/themes/reset', json={})
    assert missing_csrf.status_code == 400
    assert data.write_calls == []

    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    # The first rejected request may refresh or clear the browser session.
    # Start the authorized retry with the explicit signed session fixture.
    client.cookies.clear()
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))
    data.reset_result = (False, 'copy failed at C:\\private\\theme.zip')
    failed = client.post('/admin/themes/reset', json={}, headers={'X-CSRFToken': csrf})
    assert failed.status_code == 500, failed.text
    assert failed.json()['error_code'] == 'internal'
    assert 'private' not in failed.text


def test_default_theme_reset_form_request_redirects_with_flash():
    client, data = _client()
    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))

    response = client.post('/admin/themes/reset', data={'csrf_token': csrf}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/themes'
    expected = flask_redirect('/admin/themes', code=302)
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()
    assert 'session=' in response.headers.get('set-cookie', '')
    assert data.write_calls == [('reset', 95)]


def test_default_theme_reset_uses_flask_json_media_type_classification():
    legacy = Flask('legacy-theme-reset')
    with legacy.test_request_context(
        '/admin/themes/reset', method='POST', content_type='application/vnd.oneirodex+json',
    ):
        assert flask_request.is_json is True
    with legacy.test_request_context(
        '/admin/themes/reset', method='POST', content_type='text/plain+json',
    ):
        assert flask_request.is_json is False

    client, data = _client()
    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))
    headers = {'X-CSRFToken': csrf}

    vendor_json = client.post(
        '/admin/themes/reset', content=b'{}',
        headers={**headers, 'Content-Type': 'application/vnd.oneirodex+json'},
        follow_redirects=False,
    )
    text_json_suffix = client.post(
        '/admin/themes/reset', content=b'{}',
        headers={**headers, 'Content-Type': 'text/plain+json'},
        follow_redirects=False,
    )

    assert vendor_json.status_code == 200
    assert vendor_json.json()['status'] == 'reset'
    assert text_json_suffix.status_code == 302
    assert text_json_suffix.headers['location'] == '/admin/themes'
    assert data.write_calls == [('reset', 95), ('reset', 95)]


def test_classic_theme_upload_and_delete_forms_dispatch_natively():
    client, data = _client()
    session = {'_user_id': '95:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-themes-read-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-themes-read-secret'))

    uploaded = client.post(
        '/admin/themes', data={'csrf_token': csrf},
        files={'theme_zip': ('custom.zip', b'fake archive')}, follow_redirects=False,
    )
    deleted = client.post(
        '/admin/themes/delete/custom', data={'csrf_token': csrf}, follow_redirects=False,
    )

    assert uploaded.status_code == 302
    assert uploaded.headers['location'] == '/admin/themes'
    expected = flask_redirect('/admin/themes', code=302)
    assert uploaded.headers['content-type'] == expected.headers['Content-Type']
    assert uploaded.content == expected.get_data()
    assert 'session=' in uploaded.headers.get('set-cookie', '')
    assert deleted.status_code == 302
    assert deleted.headers['location'] == '/admin/themes'
    assert deleted.headers['content-type'] == expected.headers['Content-Type']
    assert deleted.content == expected.get_data()
    assert data.write_calls == [
        ('upload', 95, 'custom.zip', b'fake archive'), ('delete', 95, 'custom'),
    ]


def test_classic_theme_mutation_forms_reject_missing_csrf_before_data_access():
    client, data = _client()

    upload = client.post(
        '/admin/themes', files={'theme_zip': ('custom.zip', b'fake archive')},
    )
    deleted = client.post('/admin/themes/delete/custom', data={'csrf_token': 'invalid'})

    assert upload.status_code == 400
    assert deleted.status_code == 400
    assert data.write_calls == []
