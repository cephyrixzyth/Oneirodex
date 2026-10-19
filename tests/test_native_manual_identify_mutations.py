"""DB-free outer-router checks for manual-identify writes."""
import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from oneirodex.runtime_native import manual_identify_mutations


class MutationFake:
    def __init__(self):
        self.calls = []

    def create(self, app, body, actor, *, from_unmatched):
        self.calls.append(('create', body.name, actor.id, from_unmatched))
        return {'game_uuid': 'game-created', 'redirect_url': '/admin/unmatched' if from_unmatched else '/libraries'}

    def update(self, app, game_uuid, body, actor):
        self.calls.append(('update', game_uuid, body.name, actor.id))
        return {'game_uuid': game_uuid, 'redirect_url': '/libraries'}


def _request(app, method, path, **kwargs):
    async def perform():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(perform())


def _admin():
    return SimpleNamespace(
        user=SimpleNamespace(id=17, name='Admin', role='admin', is_authenticated=True),
        token=None, session_data={}, should_set_session_cookie=False,
        has_scope=lambda _scope: True,
    )


def _build(monkeypatch, *, csrf=False):
    config = {'SECRET_KEY': 'manual-identify-test', 'WTF_CSRF_ENABLED': csrf}
    app = SimpleNamespace(config=config, logger=SimpleNamespace(exception=lambda *_: None))
    data = MutationFake()
    monkeypatch.setattr(manual_identify_mutations, 'request_auth_context', lambda *a, **k: _admin())
    api = FastAPI()
    manual_identify_mutations.mount_manual_identify_mutation_routes(
        api, app, find_user=lambda _id: None, find_token=lambda _token: None,
        commit_token_touch=lambda _token: None, data_access=data,
    )
    return api, data


def _valid_payload():
    return {
        'igdb_id': 2_000_000_420,
        'name': 'Test Game',
        'full_disk_path': 'C:/games/test',
        'library_uuid': 'library-1',
        'summary': '', 'storyline': '', 'url': '', 'video_urls': '',
        'aggregated_rating': None, 'first_release_date': None,
        'status': '', 'category': '', 'item_kind': 'game',
        'developer': '', 'publisher': '',
        'genre_ids': [], 'game_mode_ids': [], 'theme_ids': [],
        'platform_ids': [], 'player_perspective_ids': [], 'provider_urls': {},
    }


def test_manual_identify_create_and_update_keep_contract_and_route_arguments(monkeypatch):
    app, data = _build(monkeypatch)
    created = _request(app, 'POST', '/api/admin/manual-identify?from_unmatched=true', json=_valid_payload())
    updated = _request(app, 'PUT', '/api/admin/manual-identify/game-42', json=_valid_payload())

    assert created.status_code == 201
    assert created.json()['ok'] is True
    assert created.json()['game_uuid'] == 'game-created'
    assert created.json()['redirect_url'] == '/admin/unmatched'
    assert updated.status_code == 200
    assert updated.json()['ok'] is True
    assert updated.json()['game_uuid'] == 'game-42'
    assert data.calls == [
        ('create', 'Test Game', 17, True),
        ('update', 'game-42', 'Test Game', 17),
    ]


def test_manual_identify_invalid_payload_and_csrf_never_call_mutation_data(monkeypatch):
    app, data = _build(monkeypatch)
    invalid = _request(app, 'POST', '/api/admin/manual-identify', json={})
    assert invalid.status_code == 422
    assert invalid.json()['ok'] is False
    assert data.calls == []

    csrf_app, csrf_data = _build(monkeypatch, csrf=True)
    rejected = _request(csrf_app, 'PUT', '/api/admin/manual-identify/game-42', json=_valid_payload())
    assert rejected.status_code == 400
    assert csrf_data.calls == []


def test_manual_identify_image_refresh_uses_owned_worker_app_context(monkeypatch):
    import oneirodex.utils.background as background
    import oneirodex.utils.scanning as scanning

    app = object()
    game_uuid = '12345678-90ab-cdef-1234-567890abcdef'
    sentinel = object()
    calls = []

    def fake_run_in_background(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(background, 'run_in_background', fake_run_in_background)
    monkeypatch.setattr(scanning, 'refresh_images_in_background', sentinel)

    result = manual_identify_mutations._queue_image_refresh(app, game_uuid)

    assert result is sentinel
    assert calls == [((app, sentinel, game_uuid), {
        'app': app,
        'name': 'oneirodex-refresh-images-12345678',
    })]


def test_background_worker_accepts_app_keyword_for_native_callbacks():
    from contextlib import contextmanager

    from oneirodex.utils.background import run_in_background

    class NativeApp:
        @contextmanager
        def app_context(self):
            yield self

    app = NativeApp()
    seen = {}

    def callback(game_uuid, *, app):
        seen['game_uuid'] = game_uuid
        seen['app'] = app

    thread = run_in_background(
        app, callback, 'game-uuid', app=app, name='test-native-callback',
    )
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert seen == {'game_uuid': 'game-uuid', 'app': app}


def test_filesystem_helpers_accept_explicit_roots_without_flask_context(tmp_path, monkeypatch):
    from oneirodex.utils.helpers.fs import get_folder_size_in_bytes_updates, read_first_nfo_content
    from oneirodex.utils.local_metadata import write_local_metadata
    from oneirodex.utils.helpers import fs

    monkeypatch.setattr(fs, 'global_settings_row', lambda: None)

    root = tmp_path / 'games'
    game = root / 'Fixture'
    game.mkdir(parents=True)
    (game / 'info.nfo').write_text('fixture metadata', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'info.nfo').write_text('outside metadata', encoding='utf-8')

    assert read_first_nfo_content(str(game), allowed_bases=[str(root)]) == 'fixture metadata'
    assert read_first_nfo_content(str(outside), allowed_bases=[str(root)]) is None
    assert get_folder_size_in_bytes_updates(str(game), allowed_bases=[str(root)]) > 0
    assert get_folder_size_in_bytes_updates(str(outside), allowed_bases=[str(root)]) == 0
    assert write_local_metadata(str(game), 17, game_title='Fixture', allowed_bases=[str(root)]) is True
    assert write_local_metadata(str(outside), 17, game_title='Outside', allowed_bases=[str(root)]) is False
