"""The ASGI static handler never serves members' private library files.

Saves, chat attachments, extracted ROMs and the companion's command queues
live under ``static/library`` but are served (when at all) by routes with
their own checks. BIOS is served to signed-in members only.
"""
from __future__ import annotations

import asyncio
import json
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


def _serve_response(
    tmp_path, path, *, method='GET', accept='*/*', extra_headers=(), files=None,
    static_root=None,
):
    static = static_root or tmp_path / 'static-response'
    static.mkdir(exist_ok=True)
    for name, payload in (files or {}).items():
        target = static / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        import os

        os.utime(target, (1700000000, 1700000000))
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._static_root = static.resolve()
    app._runtime_config = {'CSP_ENABLED': False}
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {'type': 'http.request'}

    scope = {
        'type': 'http', 'method': method, 'path': path,
        'headers': [(b'accept', accept.encode('ascii'))]
        + [(key.lower().encode('ascii'), value.encode('latin-1')) for key, value in extra_headers],
    }
    asyncio.run(app._handle_static(scope, receive, send, path))
    start = next(message for message in sent if message['type'] == 'http.response.start')
    body = b''.join(
        message.get('body', b'') for message in sent
        if message['type'] == 'http.response.body'
    )
    return start['status'], dict(start['headers']), body


@pytest.mark.parametrize(('path', 'method', 'accept'), [
    ('/static/', 'GET', '*/*'),
    ('/static/', 'HEAD', '*/*'),
    ('/static/missing-parity-asset.css', 'GET', '*/*'),
    ('/static/missing-parity-asset.css', 'POST', '*/*'),
    ('/static/missing-parity-asset.css', 'GET', 'application/json'),
])
def test_static_route_errors_match_legacy_flask(tmp_path, path, method, accept):
    status, headers, body = _serve_response(
        tmp_path, path, method=method, accept=accept,
    )
    expected_status = 405 if method == 'POST' else 404
    expected_message = 'Method Not Allowed' if method == 'POST' else 'Not Found'
    expected_body = json.dumps({'error': expected_message}).encode()
    assert status == expected_status
    assert headers[b'content-type'].startswith(b'application/json')
    assert body == expected_body


@pytest.mark.parametrize(('method', 'expected_body'), [
    ('GET', b'0123456789abcdef'),
    ('HEAD', b''),
])
def test_static_file_get_and_head_keep_legacy_body_and_cache_behavior(
    tmp_path, method, expected_body,
):
    files = {'parity.txt': b'0123456789abcdef'}
    static_root = tmp_path / 'shared-static'
    actual_status, actual_headers, actual_body = _serve_response(
        tmp_path, '/static/parity.txt', method=method, files=files,
        static_root=static_root,
    )
    assert actual_status == 200
    assert actual_body == expected_body
    assert actual_headers[b'content-type'] == b'text/plain; charset=utf-8'
    assert actual_headers[b'content-length'] == b'16'
    assert actual_headers[b'cache-control'] == b'public, max-age=3600'


def test_static_file_conditional_and_range_support_is_retained(tmp_path):
    files = {'parity.txt': b'0123456789abcdef'}
    static_root = tmp_path / 'enhanced-static'
    _, headers, _ = _serve_response(
        tmp_path, '/static/parity.txt', files=files, static_root=static_root,
    )
    etag = headers[b'etag'].decode()
    status, not_modified, body = _serve_response(
        tmp_path, '/static/parity.txt', method='GET',
        extra_headers=(('If-None-Match', etag),), static_root=static_root,
    )
    assert status == 304
    assert body == b''
    status, ranged, body = _serve_response(
        tmp_path, '/static/parity.txt', method='GET',
        extra_headers=(('Range', 'bytes=3-6'),), static_root=static_root,
    )
    assert status == 206
    assert body == b'3456'
    assert ranged[b'content-range'] == b'bytes 3-6/16'
    status, unsatisfiable, _ = _serve_response(
        tmp_path, '/static/parity.txt', method='GET',
        extra_headers=(('Range', 'bytes=99-104'),), static_root=static_root,
    )
    assert status == 416


def test_private_files_are_never_served(tmp_path, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    assert _serve(tmp_path, '/static/library/saves/1/g/s.srm', user_id=1) == 404
    assert _serve(tmp_path, '/static/library/images/a.jpg', user_id=None) == 200


def test_bios_needs_a_signed_in_member(tmp_path, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    assert _serve(tmp_path, '/static/library/bios/x.bin', user_id=None) == 404
    assert _serve(tmp_path, '/static/library/bios/x.bin', user_id=7) == 200


@pytest.mark.parametrize('spelling', [
    '/static/library/saves./1/g/s.srm',            # Win32 drops a trailing dot
    '/static/library/saves /1/g/s.srm',            # ...and a trailing space (%20)
    '/static/library/saves::$INDEX_ALLOCATION/1/g/s.srm',
    '/static/library/SAVES~1/1/g/s.srm',           # 8.3 short name
    '/static/library./saves/1/g/s.srm',
    '/static/library/client_commands./user_1.json',
])
def test_windows_aliases_of_a_private_folder_are_refused(tmp_path, monkeypatch, spelling):
    from oneirodex.utils.static_files import static_access

    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    static = tmp_path / 'static'
    (static / 'library' / 'saves' / '1' / 'g').mkdir(parents=True)
    (static / 'library' / 'saves' / '1' / 'g' / 's.srm').write_bytes(b'x')
    assert static_access(static, spelling) == 'private'
    assert _serve(tmp_path, spelling, user_id=1) == 404


def test_the_resolved_folder_decides_when_the_url_looks_public(tmp_path, monkeypatch):
    """A public-looking URL whose file really sits in a private folder (a link,
    a junction, a case-folded alias) is classified by where it resolves."""
    from oneirodex.utils.static_files import static_access

    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    static = tmp_path / 'static'
    (static / 'library' / 'saves').mkdir(parents=True)
    (static / 'library' / 'saves' / 'f.txt').write_bytes(b'x')
    (static / 'library' / 'images').mkdir(parents=True)
    try:
        (static / 'library' / 'images' / 'link').symlink_to(static / 'library' / 'saves', target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks need privileges here')
    assert static_access(static, '/static/library/images/link/f.txt') == 'private'
