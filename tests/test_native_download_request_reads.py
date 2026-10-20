from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect
import pytest

from oneirodex.runtime_native.download_request_reads import create_download_request_read_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeDownloads:
    def __init__(self):
        self.deleted_by_user = []

    def my_downloads(self, user):
        return [{'id': 10, 'game_name': f'For {user.id}', 'file_name': 'fixture.zip'}]

    def admin_requests(self):
        return [{'id': 10, 'username': 'member', 'game_uuid': '12345678'}]

    def my_download_status(self, user, request_id):
        if user.id == 7 and request_id == 10:
            return SimpleNamespace(id=10, status='queued')
        return None

    def delete_for_user(self, user, request_id):
        self.deleted_by_user.append((user.id, request_id))
        return user.id == 7 and request_id == 10

    def delete_admin_form(self, request_id):
        return request_id == 10

    def delete(self, request_id):
        return request_id == 10


def make_client(*, role='admin', data=None, csrf_enabled=False):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-download-reads-secret', TESTING=True,
        WTF_CSRF_ENABLED=csrf_enabled,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role=role, is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_download_request_read_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager, data_access=data or FakeDownloads(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-download-reads-secret'))
    return client


def test_member_download_list_returns_only_adapter_projection():
    response = make_client(role='user').get('/api/my_downloads')

    assert response.status_code == 200
    assert response.json() == [{'id': 10, 'game_name': 'For 7', 'file_name': 'fixture.zip'}]
    assert response.headers['cache-control'] == 'no-store'


def test_admin_download_list_preserves_shared_envelope():
    response = make_client().get('/api/admin/download-requests')

    assert response.status_code == 200
    assert response.json()['requests'][0]['username'] == 'member'
    assert response.json()['ok'] is True


def test_non_admin_cannot_read_admin_download_queue():
    response = make_client(role='user').get('/api/admin/download-requests', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/login'


def test_admin_delete_uses_csrf_and_reports_missing_requests():
    client = make_client()
    accepted = client.delete('/api/delete_download/10')
    missing = client.delete('/api/delete_download/99')

    assert accepted.status_code == 200
    assert accepted.json()['message'] == 'Download request deleted successfully'
    assert missing.status_code == 404
    assert missing.json()['error_code'] == 'not_found'


@pytest.mark.parametrize('request_id', ['-1', 'not-an-id'])
def test_admin_delete_rejects_paths_outside_legacy_integer_converter(request_id):
    response = make_client().delete(f'/api/delete_download/{request_id}')

    assert response.status_code == 404


def test_admin_delete_zero_id_logs_invalid_id_and_returns_bad_request(monkeypatch):
    from oneirodex.utils import event_logging

    events = []
    monkeypatch.setattr(event_logging, 'log_system_event', lambda *args, **kwargs: events.append((args, kwargs)))

    response = make_client().delete('/api/delete_download/0')

    assert response.status_code == 400
    assert response.json()['error'] == 'Invalid request ID'
    assert events == [(('Invalid request ID: 0',), {'event_type': 'download_api', 'event_level': 'warning'})]


def test_admin_bearer_delete_bypasses_csrf_but_still_requires_admin_scope(monkeypatch):
    from oneirodex.runtime_native import download_request_reads

    user = SimpleNamespace(id=7, role='admin', is_active=True, state=True, is_authenticated=True)

    def set_bearer_scope(scope_allowed):
        monkeypatch.setattr(download_request_reads, 'request_auth_context', lambda *_args, **_kwargs: SimpleNamespace(
            user=user, token=object(), source='bearer', should_set_session_cookie=False,
            has_scope=lambda scope: scope == 'admin' and scope_allowed,
        ))

    set_bearer_scope(True)
    allowed = make_client(csrf_enabled=True)
    allowed.cookies.clear()
    deleted = allowed.delete('/api/delete_download/10', headers={'Authorization': 'Bearer synthetic-admin-token'})

    assert deleted.status_code == 200
    assert deleted.json()['message'] == 'Download request deleted successfully'

    set_bearer_scope(False)
    denied = make_client(csrf_enabled=True)
    denied.cookies.clear()
    rejected = denied.delete('/api/delete_download/10', headers={'Authorization': 'Bearer synthetic-read-token'})

    assert rejected.status_code == 403
    assert rejected.json()['error_code'] == 'forbidden'


def test_member_download_status_preserves_success_and_error_contracts(monkeypatch):
    from oneirodex.utils import event_logging

    monkeypatch.setattr(event_logging, 'log_system_event', lambda *_args, **_kwargs: None)
    client = make_client(role='user')

    found = client.get('/check_download_status/10')
    missing = client.get('/check_download_status/99')
    invalid = client.get('/check_download_status/not-an-id')

    assert found.status_code == 200
    assert found.json()['status'] == 'queued'
    assert found.json()['downloadId'] == 10
    assert found.json()['found'] is True
    assert found.headers['cache-control'] == 'no-store'
    assert missing.status_code == 404
    assert missing.json()['status'] == 'not_found'
    assert missing.json()['found'] is False
    assert invalid.status_code == 400
    assert invalid.json()['status'] == 'invalid'
    assert invalid.json()['downloadId'] == 'not-an-id'


def test_legacy_download_delete_form_is_user_scoped_and_redirects(monkeypatch):
    from oneirodex.utils import event_logging

    monkeypatch.setattr(event_logging, 'log_system_event', lambda *_args, **_kwargs: None)
    data = FakeDownloads()
    client = make_client(role='user', data=data)
    removed = client.post(
        '/delete_download/10', data={'csrf_token': 'form-token'}, follow_redirects=False,
    )
    missing = client.post(
        '/delete_download/99', data={'csrf_token': 'form-token'}, follow_redirects=False,
    )

    assert removed.status_code == 302
    assert removed.headers['location'] == '/downloads'
    expected = flask_redirect('/downloads', code=302)
    assert removed.headers['content-type'] == expected.headers['Content-Type']
    assert removed.content == expected.get_data()
    assert removed.headers['cache-control'] == 'no-store'
    assert removed.cookies.get('session')
    assert missing.status_code == 404
    assert data.deleted_by_user == [(7, 10), (7, 99)]


def test_legacy_admin_download_delete_form_keeps_admin_gate_and_flash(monkeypatch):
    from oneirodex.utils import event_logging

    monkeypatch.setattr(event_logging, 'log_system_event', lambda *_args, **_kwargs: None)
    client = make_client(role='admin')
    removed = client.post(
        '/delete_download_request/10', data={'csrf_token': 'form-token'},
        follow_redirects=False,
    )
    missing = client.post(
        '/delete_download_request/99', data={'csrf_token': 'form-token'},
        follow_redirects=False,
    )

    assert removed.status_code == 302
    assert removed.headers['location'] == '/admin/manage-downloads'
    expected = flask_redirect('/admin/manage-downloads', code=302)
    assert removed.headers['content-type'] == expected.headers['Content-Type']
    assert removed.content == expected.get_data()
    assert removed.headers['cache-control'] == 'no-store'
    assert missing.status_code == 302
    assert missing.headers['location'] == '/admin/manage-downloads'

    member = make_client(role='user').post(
        '/delete_download_request/10', data={'csrf_token': 'form-token'},
        follow_redirects=False,
    )
    assert member.status_code == 302
    assert member.headers['location'] == '/login'
