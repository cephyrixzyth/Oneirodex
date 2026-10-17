from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from starlette.requests import Request

from oneirodex.runtime_native.admin_image_mutations import create_admin_image_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeImageMutations:
    def __init__(self):
        self.deleted = []
        self.rolled_back = 0

    def delete(self, config, image_id):
        self.deleted.append(image_id)
        return image_id == 4

    def rollback(self):
        self.rolled_back += 1

    def path_status(self, config):
        return {'path': config.get('IMAGE_SAVE_PATH'), 'writable': True}

    def download_images(self, app, body, path_status):
        self.download_body = body
        return {'downloaded': 0, 'failed': 0, 'errors': [], 'image_save_path': path_status}

    def upload_files(self, app, files, default_kind, explicit_uuid):
        self.uploads = ([item.filename for item in files], default_kind, explicit_uuid)
        return {'stored': len(files), 'failed': 0, 'images': [], 'errors': []}

    def upload_single(self, app, game_uuid, filename, image_type, content):
        self.single_upload = (game_uuid, filename, image_type, content)
        return {
            'message': 'File uploaded successfully',
            'url': '/static/library/images/fixture.jpg', 'flash': 'Image uploaded successfully!',
            'image_id': 11, 'image_type': image_type, 'kind': image_type,
        }


def _client():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-image-delete', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=8, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='/login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '8:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    data = FakeImageMutations()
    app = FastAPI()
    app.include_router(create_admin_image_mutation_router(
        flask_app, find_user=lambda uid: user if uid == 8 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '8' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=data,
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, data


def test_delete_image_returns_success_or_not_found_without_touching_real_files():
    client, data = _client()
    deleted = client.delete('/admin/api/delete_image/4')
    missing = client.delete('/admin/api/delete_image/9')
    assert deleted.status_code == 200 and deleted.json()['message'] == 'Image deleted successfully'
    assert missing.status_code == 404 and missing.json()['error_code'] == 'not_found'
    assert data.deleted == [4, 9]
    assert data.rolled_back == 0


def test_delete_image_path_helper_only_accepts_integer_delete_route():
    from asgi import _is_native_admin_delete_image_path
    assert _is_native_admin_delete_image_path('/admin/api/delete_image/42', 'DELETE')
    assert not _is_native_admin_delete_image_path('/admin/api/delete_image/nope', 'DELETE')
    assert not _is_native_admin_delete_image_path('/admin/api/delete_image/42', 'GET')


def test_image_refresh_progress_path_only_accepts_single_segment_reads():
    from asgi import _is_native_image_refresh_progress_path
    assert _is_native_image_refresh_progress_path('/check_image_refresh_progress/game-id', 'GET')
    assert _is_native_image_refresh_progress_path('/check_image_refresh_progress/game-id', 'HEAD')
    assert not _is_native_image_refresh_progress_path('/check_image_refresh_progress/a/b', 'GET')
    assert not _is_native_image_refresh_progress_path('/check_image_refresh_progress/game-id', 'POST')


def test_library_delete_progress_path_only_accepts_single_segment_reads():
    from asgi import _is_native_library_delete_progress_path
    assert _is_native_library_delete_progress_path('/check_deletion_progress/job-id', 'GET')
    assert _is_native_library_delete_progress_path('/check_deletion_progress/job-id', 'HEAD')
    assert not _is_native_library_delete_progress_path('/check_deletion_progress/a/b', 'GET')
    assert not _is_native_library_delete_progress_path('/check_deletion_progress/job-id', 'POST')


def test_library_delete_sse_path_only_accepts_single_segment_reads():
    from asgi import _is_native_library_delete_sse_path
    assert _is_native_library_delete_sse_path('/delete_library_progress/job-id', 'GET')
    assert _is_native_library_delete_sse_path('/delete_library_progress/job-id', 'HEAD')
    assert not _is_native_library_delete_sse_path('/delete_library_progress/a/b', 'GET')
    assert not _is_native_library_delete_sse_path('/delete_library_progress/job-id', 'POST')


def test_download_and_batch_upload_use_authenticated_csrf_routes_and_fake_storage():
    client, data = _client()
    download = client.post('/admin/api/download_images', json={'image_ids': [4]})
    upload = client.post(
        '/admin/api/images/batch_upload',
        files={'files': ('g1_cover.png', b'image-content', 'image/png')},
        data={'image_type': 'cover', 'game_uuid': 'g1'},
    )
    assert download.status_code == 200 and download.json()['ok'] is True
    assert data.download_body == {'image_ids': [4]}
    assert upload.status_code == 200 and upload.json()['stored'] == 1
    assert data.uploads == (['g1_cover.png'], 'cover', 'g1')


def test_image_batch_upload_rejects_missing_csrf():
    client, data = _client()
    response = client.post(
        '/admin/api/images/batch_upload',
        files={'files': ('g1_cover.png', b'image-content', 'image/png')},
        headers={'X-CSRFToken': ''},
    )
    assert response.status_code == 400
    assert not hasattr(data, 'uploads')


def test_single_game_image_upload_preserves_csrf_and_payload(monkeypatch):
    monkeypatch.setattr('oneirodex.utils.scanning.is_scan_job_running', lambda: False)
    client, data = _client()
    rejected = client.post(
        '/upload_image/game-1', files={'file': ('cover.jpg', b'image-bytes', 'image/jpeg')},
        data={'image_type': 'cover'}, headers={'X-CSRFToken': ''},
    )
    accepted = client.post(
        '/upload_image/game-1', files={'file': ('cover.jpg', b'image-bytes', 'image/jpeg')},
        data={'image_type': 'cover'},
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['image_id'] == 11
    assert accepted.json()['image_type'] == 'cover'
    assert data.single_upload == ('game-1', 'cover.jpg', 'cover', b'image-bytes')


def test_unauthenticated_single_image_upload_is_denied_before_form_parsing(monkeypatch):
    client, _data = _client()
    client.cookies.clear()
    client.headers.pop('X-CSRFToken', None)
    parse_calls = 0
    original_form = Request.form

    async def observe_form(self, *args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return await original_form(self, *args, **kwargs)

    monkeypatch.setattr(Request, 'form', observe_form)
    response = client.post(
        '/upload_image/game-1',
        files={'file': ('oversized.bin', b'x' * (2 * 1024 * 1024), 'application/octet-stream')},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303, 307, 308}
    assert parse_calls == 0


def test_single_image_upload_rejects_oversized_body():
    client, data = _client()
    response = client.post(
        '/upload_image/game-1',
        files={'file': ('cover.jpg', b'x' * (3 * 1024 * 1024 + 128 * 1024), 'image/jpeg')},
        data={'image_type': 'cover'},
    )

    assert response.status_code == 413
    assert not hasattr(data, 'single_upload')
