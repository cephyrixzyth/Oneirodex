from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from werkzeug.exceptions import NotFound

from oneirodex.runtime_native.game_delete_mutations import create_game_delete_mutation_router
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
    runtime = FastAPI()
    runtime.include_router(create_game_delete_mutation_router(
        flask_app, find_user=lambda _id: admin, find_token=lambda _prefix: None,
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
