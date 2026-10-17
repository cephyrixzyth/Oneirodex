from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
import pytest
from werkzeug.exceptions import NotFound
from werkzeug.utils import redirect

from oneirodex.runtime_native.admin_whitelist import create_admin_whitelist_router
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token,
)


class FakeWhitelist:
    def __init__(self):
        self.calls = []
        self.add_error = None
        self.delete_error = None

    def list(self):
        return {'entries': [{'id': 3, 'email': 'member@example.org', 'is_registered': True}]}

    def add(self, body, actor):
        self.calls.append(('add', body.email, actor.id))
        return (({'id': 8, 'email': body.email}, None) if self.add_error is None
                else (None, self.add_error))

    def delete(self, whitelist_id, actor):
        self.calls.append(('delete', whitelist_id, actor.id))
        return (({'message': 'Entry deleted successfully'}, None)
                if self.delete_error is None else (None, self.delete_error))

    def rollback(self):
        self.calls.append(('rollback',))


def _client(shell_path=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-whitelist-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='whitelist-admin', role='admin', is_active=True,
        state=True, is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
        name='Admin fixture',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeWhitelist()
    router = create_admin_whitelist_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, data_access=data,
        database_scope=lambda _app: nullcontext(),
        shell_path=shell_path,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, csrf


def test_whitelist_read_and_head_keep_api_envelope():
    client, data, _csrf = _client()
    response = client.get('/admin/api/whitelist')
    head = client.head('/admin/api/whitelist')
    assert response.status_code == 200
    assert response.json()['entries'][0]['is_registered'] is True
    assert response.json()['success'] is True
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200 and head.content == b''
    assert data.calls == []


def test_whitelist_create_and_delete_require_csrf_and_preserve_results():
    denied_client, _denied_data, _denied_csrf = _client()
    body = {'email': ' Person@Example.org '}
    denied = denied_client.post('/admin/api/whitelist', json=body)
    assert denied.status_code == 400
    client, data, csrf = _client()
    invalid = client.post(
        '/admin/api/whitelist', json={'email': 'bad'}, headers={'X-CSRFToken': csrf},
    )
    created = client.post(
        '/admin/api/whitelist', json=body, headers={'X-CSRFToken': csrf},
    )
    deleted = client.delete('/admin/whitelist/8', headers={'X-CSRFToken': csrf})
    assert invalid.status_code == 422 and invalid.json()['error_code'] == 'unprocessable'
    assert created.status_code == 201 and created.json()['email'] == 'person@example.org'
    assert deleted.status_code == 200 and deleted.json()['message'] == 'Entry deleted successfully'
    assert data.calls == [
        ('add', 'person@example.org', 18), ('delete', 8, 18),
    ]


def test_whitelist_conflict_and_missing_delete_use_error_contracts():
    client, data, csrf = _client()
    data.add_error = ('The email is already in the whitelist.', 'conflict', None)
    duplicate = client.post(
        '/admin/api/whitelist', json={'email': 'member@example.org'},
        headers={'X-CSRFToken': csrf},
    )
    data.delete_error = ('Not found', 'not_found', 404)
    missing = client.delete(
        '/admin/whitelist/55',
        headers={'X-CSRFToken': csrf, 'Accept': 'application/json'},
    )
    assert duplicate.status_code == 409 and duplicate.json()['error_code'] == 'conflict'
    assert missing.status_code == 404 and missing.json()['error_code'] == 'not_found'
    assert missing.json()['error'] == NotFound().description
    assert missing.json()['message'] == NotFound().description


def test_missing_whitelist_delete_keeps_legacy_html_for_browser_requests():
    client, data, csrf = _client()
    data.delete_error = ('Not found', 'not_found', 404)
    response = client.delete('/admin/whitelist/55', headers={'X-CSRFToken': csrf})
    expected = NotFound().get_response()

    assert response.status_code == expected.status_code == 404
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.headers['content-length'] == expected.headers['Content-Length']
    assert response.content == expected.get_data()


@pytest.mark.parametrize(('extra_headers', 'expects_json'), [
    ({'X-Requested-With': 'XMLHttpRequest'}, True),
    ({'Accept': 'text/html, application/json;q=0.9'}, False),
    ({'Accept': 'application/json, text/html;q=0.5'}, True),
    ({'Accept': 'application/json;q=0, text/html'}, False),
])
def test_missing_whitelist_delete_matches_legacy_error_negotiation(extra_headers, expects_json):
    client, data, csrf = _client()
    data.delete_error = ('Not found', 'not_found', 404)
    headers = {'X-CSRFToken': csrf, **extra_headers}
    response = client.delete('/admin/whitelist/55', headers=headers)

    assert response.status_code == 404
    if expects_json:
        assert response.headers['content-type'].startswith('application/json')
        assert response.json()['error_code'] == 'not_found'
        assert response.json()['error'] == NotFound().description
        assert response.json()['message'] == NotFound().description
    else:
        assert response.headers['content-type'].startswith('text/html')
        assert response.content == NotFound().get_response().get_data()


def test_legacy_whitelist_form_uses_hidden_csrf_and_redirects():
    client, data, csrf = _client()
    response = client.post(
        '/admin/whitelist',
        data={'csrf_token': csrf, 'email': 'Person@Example.org'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/whitelist'
    expected = redirect('/admin/whitelist')
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.headers['content-length'] == expected.headers['Content-Length']
    assert response.content == expected.get_data()
    assert data.calls == [('add', 'person@example.org', 18)]


@pytest.mark.parametrize('email', [' person@example.org ', 'person@example.org\n'])
def test_legacy_whitelist_form_rejects_email_whitespace_before_normalization(email, tmp_path):
    shell_path = tmp_path / 'admin.html'
    shell_path.write_text('<!doctype html><div id="admin-app-root"></div>', encoding='utf-8')
    client, data, csrf = _client(shell_path)
    response = client.post(
        '/admin/whitelist', data={'csrf_token': csrf, 'email': email},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert 'data-error="Invalid email address."' in response.text
    assert data.calls == []


@pytest.mark.parametrize(('email', 'message'), [
    ('', 'This field is required.'),
    ('not-an-email', 'Invalid email address.'),
    ('person@' + 'a' * 60 + '.' + 'b' * 60 + '.com',
     'Email address is too long (maximum 120 characters)'),
])
def test_legacy_whitelist_form_preserves_field_validation_messages(email, message, tmp_path):
    shell_path = tmp_path / 'admin.html'
    shell_path.write_text('<!doctype html><div id="admin-app-root"></div>', encoding='utf-8')
    client, data, csrf = _client(shell_path)
    response = client.post(
        '/admin/whitelist', data={'csrf_token': csrf, 'email': email},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert f'data-error="{message}"' in response.text
    assert f'data-email="{email}"' in response.text
    assert data.calls == []


def test_legacy_whitelist_form_escapes_invalid_value_in_react_shell(tmp_path):
    shell_path = tmp_path / 'admin.html'
    shell_path.write_text('<!doctype html><div id="admin-app-root"></div>', encoding='utf-8')
    client, data, csrf = _client(shell_path)
    malicious_value = '" autofocus onfocus="alert(1)'
    response = client.post(
        '/admin/whitelist',
        data={'csrf_token': csrf, 'email': malicious_value},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert 'data-email="&quot; autofocus onfocus=&quot;alert(1)"' in response.text
    assert 'data-email="" autofocus' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert 'cookie' in {
        value.strip().lower() for value in response.headers['vary'].split(',')
    }
    assert data.calls == []
