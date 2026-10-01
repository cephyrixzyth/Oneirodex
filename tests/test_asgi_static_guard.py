"""The ASGI static handler never serves members' private library files.

Saves, chat attachments, extracted ROMs and the companion's command queues
live under ``static/library`` but are served (when at all) by routes with
their own checks. BIOS is served to signed-in members only.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from asgi import LazyASGIApp
from oneirodex.utils.static_files import library_access


@pytest.mark.parametrize('url, access', [
    ('/static/library/themes/default/css/od-tokens.css', 'public'),
    ('/static/library/images/cover.jpg', 'public'),
    ('/static/library/system-marks/aurora/nes.webp', 'public'),
    ('/static/library/saves/1/uuid/cloud-state_cloud.state', 'private'),
    ('/static/library/client_commands/user_1.json', 'private'),
    ('/static/library/client_lifecycle/user_1.json', 'private'),
    ('/static/library/rom_cache/uuid/play.zip', 'private'),
    ('/static/library/chat-attachments/abc.png', 'private'),
    ('/static//library/./SAVES/1/x', 'private'),
    ('/static/LIBRARY/Rom_Cache/x', 'private'),
    ('/static/library/bios/scph5501.bin', 'member'),
    ('/static/dist/member-app/member-app.js', 'public'),
])
def test_library_folders_are_classified(url, access):
    assert library_access(url) == access


def _serve(tmp_path, path, user_id):
    static = tmp_path / 'static'
    for rel in ('library/saves/1/g/s.srm', 'library/bios/x.bin', 'library/images/a.jpg'):
        (static / rel).parent.mkdir(parents=True, exist_ok=True)
        (static / rel).write_bytes(b'x')
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._static_root = static.resolve()
    app._get_user_from_session = AsyncMock(return_value=user_id)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {'type': 'http.request'}

    asyncio.run(app._handle_static({'type': 'http', 'method': 'GET', 'path': path, 'headers': []},
                                   receive, send, path))
    return next(m['status'] for m in sent if m['type'] == 'http.response.start')


def test_private_files_are_never_served(tmp_path, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    assert _serve(tmp_path, '/static/library/saves/1/g/s.srm', user_id=1) == 404
    assert _serve(tmp_path, '/static/library/images/a.jpg', user_id=None) == 200


def test_bios_needs_a_signed_in_member(tmp_path, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    assert _serve(tmp_path, '/static/library/bios/x.bin', user_id=None) == 404
    assert _serve(tmp_path, '/static/library/bios/x.bin', user_id=7) == 200
