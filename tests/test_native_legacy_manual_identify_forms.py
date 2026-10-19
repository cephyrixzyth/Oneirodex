from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.legacy_manual_identify_forms import create_legacy_manual_identify_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeManualIdentifyData:
    def __init__(self):
        self.calls = []

    def create(self, app, body, actor, *, from_unmatched):
        self.calls.append(('create', body, from_unmatched))
        return {'game_uuid': 'new-game', 'redirect_url': '/libraries'}

    def update(self, app, game_uuid, body, actor):
        self.calls.append(('update', game_uuid, body))
        return {'game_uuid': game_uuid, 'redirect_url': '/libraries'}


@pytest.fixture
def native_client():
    app = Flask('legacy-manual-identify-tests')
    app.config.update(
        SECRET_KEY='manual-identify-secret', WTF_CSRF_ENABLED=True,
        WTF_CSRF_SECRET_KEY='manual-identify-secret', SESSION_PROTECTION='none',
        MAX_CONTENT_LENGTH=512 * 1024,
    )
    user = SimpleNamespace(id=9, name='Admin', role='admin', state=True, is_active=True)
    data = FakeManualIdentifyData()
    runtime = FastAPI()
    runtime.include_router(create_legacy_manual_identify_router(
        app, find_user=lambda _id: user, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id == '9:fp' else None,
        data_access=data, database_scope=lambda _app: nullcontext(),
    ))
    return runtime, data


def _request(runtime, path, fields, *, csrf=True):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            session = {'_user_id': '9:fp', '_fresh': True}
            token = generate_csrf_token(session, 'manual-identify-secret')
            cookie = dump_session_cookie(session, 'manual-identify-secret')
            values = {'csrf_token': token if csrf else 'invalid', **fields}
            headers = {'Cookie': f'session={cookie}'}
            if csrf:
                headers['X-CSRFToken'] = token
            return await client.post(path, data=values, headers=headers)
    return asyncio.run(send())


def _base_fields():
    return {
        'igdb_id': '101', 'name': 'Game', 'full_disk_path': '/safe/Game',
        'library_uuid': 'lib-1', 'summary': 'Summary', 'genres': ['1', '2'],
        'provider_url_steam': 'https://store.steampowered.com/app/101',
    }


def test_legacy_add_form_uses_native_adapter_and_unmatched_redirect(native_client):
    runtime, data = native_client
    response = _request(runtime, '/add_game_manual?from_unmatched=true', _base_fields())
    assert response.status_code == 303
    assert response.headers['location'] == '/scan_management?active_tab=unmatched'
    action, body, from_unmatched = data.calls[0]
    assert action == 'create'
    assert body.igdb_id == 101
    assert body.genre_ids == [1, 2]
    assert body.provider_urls['steam'].startswith('https://')
    assert from_unmatched is True


def test_legacy_edit_form_checks_csrf_and_uses_native_update(native_client):
    runtime, data = native_client
    refused = _request(runtime, '/game_edit/game-1', _base_fields(), csrf=False)
    assert refused.status_code == 400
    assert refused.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is invalid.</p>' in refused.content
    assert data.calls == []

    accepted = _request(runtime, '/game_edit/game-1', _base_fields())
    assert accepted.status_code == 303
    assert accepted.headers['location'] == '/library'
    assert data.calls[0][0:2] == ('update', 'game-1')


def test_legacy_manual_identify_form_enforces_body_limit(native_client):
    runtime, data = native_client
    response = _request(runtime, '/add_game_manual', {
        **_base_fields(), 'summary': 'x' * (600 * 1024),
    })
    assert response.status_code == 413
    assert data.calls == []
