from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from werkzeug.exceptions import NotFound

from oneirodex.runtime_native.game_delete_mutations import (
    GameDeleteMutationData,
    create_game_delete_mutation_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeGameDeleteData:
    def __init__(self):
        self.running = False
        self.missing = False
        self.path_safe = True
        self.exists = True
        self.game_row = SimpleNamespace(full_disk_path='/safe/games/Game')
        self.calls = []

    def scan_running(self):
        return self.running

    def delete_game(self, game_uuid, *, config):
        self.calls.append((game_uuid, config))
        if self.missing:
            raise NotFound()

    def game(self, _game_uuid):
        return None if self.missing else self.game_row

    def allowed_bases(self, _app):
        return ['/safe']

    def safe_path(self, path, bases):
        self.calls.append(('safe', path, bases))
        return self.path_safe, 'denied' if not self.path_safe else None

    def folder_entry(self, path):
        self.calls.append(('entry', path))
        return SimpleNamespace(folder_path=path)

    def remove_folder_entry(self, entry):
        self.calls.append(('remove_entry', entry.folder_path))

    def restore_folder_entry(self, entry):
        self.calls.append(('restore_entry', entry.folder_path))
        return True

    def path_exists(self, _path):
        return self.exists

    def remove_path(self, path):
        self.calls.append(('remove_path', path))
        self.exists = False

    def path_is_directory(self, _path):
        return False

    def delete_image_record_and_file(self, image_id, *, config):
        self.calls.append(('delete_image', image_id, config['SECRET_KEY']))
        return None if self.missing else SimpleNamespace(id=image_id)


@pytest.fixture
def native_client():
    flask_app = Flask('native-game-delete-tests')
    flask_app.config.update(
        SECRET_KEY='game-delete-secret', SESSION_PROTECTION='none',
        WTF_CSRF_ENABLED=True, WTF_CSRF_SECRET_KEY='game-delete-secret',
    )
    admin = SimpleNamespace(id=7, name='Admin', role='admin', state=True, is_active=True)
    data = FakeGameDeleteData()
    data.admin = admin
    tokens = {}
    data.tokens = tokens
    runtime = FastAPI()
    runtime.include_router(create_game_delete_mutation_router(
        flask_app, find_user=lambda _id: admin, find_token=lambda prefix: tokens.get(prefix),
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: admin if user_id == '7:fp' else None,
        data_access=data, database_scope=lambda _app: nullcontext(),
    ))
    session = {'_user_id': '7:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'game-delete-secret')
    cookie = dump_session_cookie(session, 'game-delete-secret')
    return runtime, data, csrf, cookie


def _request(runtime, path, *, csrf=None, cookie=None):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            headers = {}
            if csrf:
                headers['X-CSRFToken'] = csrf
            if cookie:
                headers['Cookie'] = f'session={cookie}'
            return await client.post(path, headers=headers, json={})
    return asyncio.run(send())


def test_native_game_delete_preserves_auth_csrf_and_scan_guard(native_client):
    runtime, data, csrf, cookie = native_client
    no_csrf = _request(runtime, '/delete_game/game-1', cookie=cookie)
    assert no_csrf.status_code == 400
    assert no_csrf.headers['content-type'].startswith('application/json')
    assert data.calls == []

    data.running = True
    running = _request(runtime, '/delete_game/game-1', csrf=csrf, cookie=cookie)
    assert running.status_code == 403
    assert 'A scan is running' in running.json()['message']
    assert data.calls == []

    data.running = False
    deleted = _request(runtime, '/delete_game/game-1', csrf=csrf, cookie=cookie)
    assert deleted.status_code == 200
    assert deleted.json()['success'] is True
    assert deleted.json()['message'] == 'Game removed from library successfully.'
    assert data.calls[0][0] == 'game-1'
    assert data.calls[0][1]['SECRET_KEY'] == 'game-delete-secret'


def test_native_game_delete_not_found_is_404(native_client):
    runtime, data, csrf, cookie = native_client
    data.missing = True
    response = _request(runtime, '/delete_game/missing', csrf=csrf, cookie=cookie)
    assert response.status_code == 404
    assert response.json()['message'] == 'Game not found.'


def test_native_unmatched_folder_delete_keeps_path_guard_and_fake_side_effects(native_client):
    runtime, data, csrf, cookie = native_client
    response = _request_json(
        runtime, '/delete_folder', {'folder_path': '/safe/games/Unmatched'},
        csrf=csrf, cookie=cookie,
    )
    assert response.status_code == 200
    assert response.json()['status'] == 'success'
    assert any(call[0] == 'remove_path' and call[1].endswith('Unmatched') for call in data.calls)
    assert any(call[0] == 'remove_entry' for call in data.calls)

    data.calls.clear()
    data.path_safe = False
    denied = _request_json(
        runtime, '/delete_folder', {'folder_path': '/outside/item'},
        csrf=csrf, cookie=cookie,
    )
    assert denied.status_code == 403
    assert denied.json()['status'] == 'error'
    assert not any(call[0] == 'remove_path' for call in data.calls)


def test_native_unmatched_folder_delete_rejects_non_json_media_type(native_client):
    runtime, data, csrf, cookie = native_client

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_folder',
                content=b'{"folder_path":"/safe/games/Unmatched"}',
                headers={
                    'Content-Type': 'text/plain',
                    'X-CSRFToken': csrf,
                    'Cookie': f'session={cookie}',
                },
            )

    response = asyncio.run(send())
    assert response.status_code == 415
    assert response.json()['status'] == 'error'
    assert not any(call[0] in ('remove_path', 'remove_entry') for call in data.calls)


def test_native_unmatched_folder_delete_checks_permissions_before_staging(native_client):
    runtime, data, csrf, cookie = native_client
    data.ensure_path_removable = lambda _path: (_ for _ in ()).throw(
        PermissionError('synthetic read-only folder')
    )
    data.stage_path = lambda _path: pytest.fail('must not stage a protected folder')

    response = _request_json(
        runtime, '/delete_folder', {'folder_path': '/safe/games/Unmatched'},
        csrf=csrf, cookie=cookie,
    )

    assert response.status_code == 403
    assert response.json()['message'] == (
        'Failed to delete the item due to insufficient permissions. Database entry retained.'
    )
    assert not any(call[0] == 'remove_entry' for call in data.calls)


def test_game_delete_permission_preflight_checks_directories(monkeypatch, tmp_path):
    folder = tmp_path / 'read-only'
    folder.mkdir()
    (folder / 'marker.txt').write_text('keep', encoding='utf-8')
    access = lambda path, _mode: Path(path) != folder
    monkeypatch.setattr('oneirodex.runtime_native.game_delete_mutations.os.access', access)

    with pytest.raises(PermissionError):
        GameDeleteMutationData().ensure_path_removable(str(folder))


@pytest.mark.parametrize(
    ('failure', 'expected_status'),
    [(RuntimeError, 500), (PermissionError, 403)],
)
def test_native_unmatched_folder_delete_restores_path_when_database_delete_fails(
    native_client, tmp_path, failure, expected_status,
):
    runtime, data, csrf, cookie = native_client
    folder = tmp_path / 'unmatched'
    folder.mkdir()
    marker = folder / 'keep.txt'
    marker.write_text('restore after commit failure', encoding='utf-8')

    data.path_exists = lambda path: Path(path).exists()
    data.folder_entry = lambda path: SimpleNamespace(folder_path=path)
    data.rollback = lambda: data.calls.append(('rollback',))
    data.stage_path = lambda path: _stage_test_path(path)
    data.restore_staged_path = lambda staged, path: os.replace(staged, path)
    data.discard_staged_path = lambda staged: shutil.rmtree(staged)

    def fail_database_delete(_entry):
        raise failure('synthetic database commit failure')

    data.remove_folder_entry = fail_database_delete

    response = _request_json(
        runtime, '/delete_folder', {'folder_path': str(folder)},
        csrf=csrf, cookie=cookie,
    )

    assert response.status_code == expected_status
    assert folder.is_dir()
    assert marker.read_text(encoding='utf-8') == 'restore after commit failure'
    assert not list(tmp_path.glob('*.delete-*'))


def test_native_unmatched_folder_delete_restores_folder_and_row_when_staged_cleanup_fails(
    native_client, tmp_path,
):
    runtime, data, csrf, cookie = native_client
    folder = tmp_path / 'unmatched'
    nested = folder / 'nested'
    nested.mkdir(parents=True)
    marker = nested / 'keep.txt'
    marker.write_text('restore after staged cleanup failure', encoding='utf-8')

    entry = SimpleNamespace(id='synthetic-row', folder_path=str(folder))
    data.path_exists = lambda path: Path(path).exists()
    data.folder_entry = lambda _path: entry
    data.stage_path = _stage_test_path
    data.restore_staged_path = lambda staged, path: os.replace(staged, path)
    data.discard_staged_path = lambda _staged: False

    response = _request_json(
        runtime, '/delete_folder', {'folder_path': str(folder)},
        csrf=csrf, cookie=cookie,
    )

    assert response.status_code == 500
    assert response.json()['message'] == (
        'Could not delete the item. The folder and database entry were restored.'
    )
    assert marker.read_text(encoding='utf-8') == 'restore after staged cleanup failure'
    assert not list(tmp_path.glob('*.delete-*'))
    assert ('restore_entry', str(folder)) in data.calls


def test_native_full_game_delete_checks_path_before_fake_disk_and_db_effects(native_client):
    runtime, data, csrf, cookie = native_client
    response = _request_json(
        runtime, '/delete_full_game', {'game_uuid': 'game-1'},
        csrf=csrf, cookie=cookie,
    )
    assert response.status_code == 200
    assert response.json()['message'] == 'Game file has been deleted successfully.'
    assert any(call[0] == 'remove_path' and call[1].endswith('Game') for call in data.calls)
    assert any(isinstance(call[1], dict) and call[0] == 'game-1' for call in data.calls)

    data.calls.clear()
    data.exists = True
    data.path_safe = False
    denied = _request_json(
        runtime, '/delete_full_game', {'game_uuid': 'game-1'},
        csrf=csrf, cookie=cookie,
    )
    assert denied.status_code == 403
    assert not any(call[0] == 'remove_path' for call in data.calls)


@pytest.mark.parametrize(
    ('body', 'expected_detail'),
    [
        ({}, {'game_uuid': 'Field required'}),
        ([], {'__root__': 'Input should be a valid dictionary or instance of DeleteFullGameBody'}),
        (None, {'game_uuid': 'Field required'}),
        (True, {'__root__': 'Input should be a valid dictionary or instance of DeleteFullGameBody'}),
        (1, {'__root__': 'Input should be a valid dictionary or instance of DeleteFullGameBody'}),
        ('invalid', {'__root__': 'Input should be a valid dictionary or instance of DeleteFullGameBody'}),
    ],
)
def test_native_full_game_delete_preserves_legacy_non_object_validation_detail(
    native_client, body, expected_detail,
):
    runtime, data, csrf, cookie = native_client

    response = _request_json(
        runtime, '/delete_full_game', body, csrf=csrf, cookie=cookie,
    )

    assert response.status_code == 422
    assert response.json()['detail'] == expected_detail
    assert data.calls == []


def test_native_full_game_delete_accepts_classic_form_submission(native_client):
    runtime, data, csrf, cookie = native_client

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_full_game',
                data={'csrf_token': csrf, 'game_uuid': 'game-1'},
                headers={'Cookie': f'session={cookie}'},
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()['message'] == 'Game file has been deleted successfully.'
    assert any(call[0] == 'game-1' for call in data.calls)


def test_native_full_game_delete_renders_classic_form_csrf_errors_as_html(native_client):
    runtime, data, csrf, cookie = native_client

    async def send(token):
        form = {'game_uuid': 'game-1'}
        if token is not None:
            form['csrf_token'] = token
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_full_game', data=form,
                headers={'Cookie': f'session={cookie}'},
            )

    missing = asyncio.run(send(None))
    invalid = asyncio.run(send('invalid-csrf-token'))

    assert missing.status_code == invalid.status_code == 400
    assert missing.headers['content-type'].startswith('text/html')
    assert invalid.headers['content-type'].startswith('text/html')
    assert '<p>The CSRF token is missing.</p>' in missing.text
    assert '<p>The CSRF token is invalid.</p>' in invalid.text
    assert data.calls == []


def test_native_full_game_delete_redirects_regular_user_form_to_login(native_client):
    runtime, data, csrf, cookie = native_client
    data.admin.role = 'user'

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_full_game',
                data={'csrf_token': csrf, 'game_uuid': 'game-1'},
                headers={'Cookie': f'session={cookie}'},
            )

    response = asyncio.run(send())

    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    assert response.headers['content-type'].startswith('text/html')
    assert 'session=' in response.headers['set-cookie']
    from oneirodex.runtime_native.session_compat import load_session_cookie

    set_cookie = response.headers['set-cookie'].split(';', 1)[0].split('=', 1)[1]
    saved_session = load_session_cookie(set_cookie, 'game-delete-secret', max_age=3600)
    assert saved_session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == []


@pytest.mark.parametrize(
    ('role', 'scopes', 'expected_status', 'expected_message'),
    [
        ('admin', ['admin'], 404, 'Game not found.'),
        ('admin', ['read:library'], 403, 'This token does not have the admin scope'),
        ('user', ['admin'], 403, 'Admin required'),
    ],
)
def test_native_full_game_delete_enforces_bearer_role_and_admin_scope(
    native_client, role, scopes, expected_status, expected_message,
):
    runtime, data, csrf, _cookie = native_client
    data.admin.role = role
    data.missing = True
    secret = 'scoped-delete-test-secret'
    data.tokens['delete-test'] = SimpleNamespace(
        user_id=7,
        token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=scopes,
        revoked_at=None,
        expires_at=None,
        is_expired=lambda _now: False,
        last_used_at=None,
    )

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_full_game', json={'game_uuid': 'game-1'},
                headers={
                    'Authorization': 'Bearer gt_delete-test_' + secret,
                    'X-CSRFToken': csrf,
                },
            )

    response = asyncio.run(send())

    assert response.status_code == expected_status
    assert response.json()['message'] == expected_message
    assert data.calls == []


def test_native_full_game_delete_treats_malformed_json_as_missing_body(native_client):
    runtime, data, csrf, cookie = native_client

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/delete_full_game', content=b'{not-json',
                headers={
                    'Cookie': f'session={cookie}',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrf,
                },
            )

    response = asyncio.run(send())

    assert response.status_code == 422
    assert response.json()['detail'] == {'game_uuid': 'Field required'}
    assert data.calls == []


def test_native_image_delete_preserves_validation_scan_guard_and_cover_fallback(native_client):
    runtime, data, csrf, cookie = native_client
    data.running = True
    running = _request_json(
        runtime, '/delete_image', {'image_id': 4}, csrf=csrf, cookie=cookie,
    )
    assert running.status_code == 403
    assert not any(call[0] == 'delete_image' for call in data.calls)

    data.running = False
    deleted = _request_json(
        runtime, '/delete_image', {'image_id': 4, 'is_cover': True},
        csrf=csrf, cookie=cookie,
    )
    assert deleted.status_code == 200
    assert deleted.json()['message'] == 'Image deleted successfully'
    assert deleted.json()['default_cover'] == '/static/newstyle/default_cover.jpg'
    assert ('delete_image', 4, 'game-delete-secret') in data.calls

    invalid = _request_json(
        runtime, '/delete_image', {}, csrf=csrf, cookie=cookie,
    )
    assert invalid.status_code == 422


def test_game_image_adapter_rejects_paths_outside_image_root(tmp_path, monkeypatch):
    from oneirodex.runtime_native.db_session import _native_session
    from oneirodex.runtime_native.game_delete_mutations import GameDeleteMutationData

    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'keep')
    session_calls = []
    fake_session = SimpleNamespace(
        get=lambda _model, _key: SimpleNamespace(url='../outside.png'),
        delete=lambda _image: session_calls.append('delete'),
        commit=lambda: session_calls.append('commit'),
    )
    token = _native_session.set(fake_session)
    try:
        with pytest.raises(ValueError, match='Invalid image path'):
            GameDeleteMutationData().delete_image_record_and_file(
                1, config={'IMAGE_SAVE_PATH': str(tmp_path / 'images')},
            )
    finally:
        _native_session.reset(token)
    assert outside.read_bytes() == b'keep'
    assert session_calls == []


def test_game_image_adapter_restores_file_when_database_commit_fails(tmp_path):
    from oneirodex.runtime_native.db_session import _native_session
    from oneirodex.runtime_native.game_delete_mutations import GameDeleteMutationData

    root = tmp_path / 'images'
    root.mkdir()
    image_path = root / 'commit-failure.png'
    image_path.write_bytes(b'keep-after-failed-commit')
    calls = []

    def fail_commit():
        calls.append('commit')
        raise RuntimeError('synthetic commit failure')

    fake_session = SimpleNamespace(
        get=lambda _model, _key: SimpleNamespace(url=image_path.name),
        delete=lambda _image: calls.append('delete'),
        commit=fail_commit,
    )
    token = _native_session.set(fake_session)
    try:
        with pytest.raises(RuntimeError, match='synthetic commit failure'):
            GameDeleteMutationData().delete_image_record_and_file(
                1, config={'IMAGE_SAVE_PATH': str(root)},
            )
    finally:
        _native_session.reset(token)

    assert calls == ['delete', 'commit']
    assert image_path.read_bytes() == b'keep-after-failed-commit'
    assert list(root.iterdir()) == [image_path]


def test_play_sessions_follow_game_database_delete_cascade():
    from oneirodex.models import Game
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
    assert Game.play_sessions.property.passive_deletes == 'all'


def _request_json(runtime, path, body, *, csrf=None, cookie=None):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            headers = {}
            if csrf:
                headers['X-CSRFToken'] = csrf
            if cookie:
                headers['Cookie'] = f'session={cookie}'
            return await client.post(path, headers=headers, json=body)
    return asyncio.run(send())


def _stage_test_path(path):
    staged = f'{path}.delete-{uuid4().hex}'
    os.replace(path, staged)
    return staged
