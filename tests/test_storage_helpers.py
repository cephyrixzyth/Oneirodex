"""Wave 14a — storage helpers status honesty + apply gate + RO preview."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User
from oneirodex.utils.hardlinks import (
    build_degrade_reason,
    build_storage_status,
    preview_hardlink,
    probe_games_path,
)


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'adm_{uid[:8]}',
        email=f'adm_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_probe_games_path_ro(tmp_path, monkeypatch):
    root = tmp_path / 'games'
    root.mkdir()
    real_access = __import__('os').access

    def fake_access(path, mode):
        import os as _os
        if str(path) == str(root) and mode == _os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr('oneirodex.utils.hardlinks.os.access', fake_access)
    probe = probe_games_path(str(root))
    assert probe['games_exists'] is True
    assert probe['games_readable'] is True
    assert probe['games_writable'] is False


def test_probe_games_path_missing():
    probe = probe_games_path('/no/such/games/root/xyz')
    assert probe['games_exists'] is False
    assert probe['games_readable'] is False
    assert probe['games_writable'] is False


def test_degrade_reason_apply_off_and_ro():
    reason = build_degrade_reason(
        helpers_enabled=True,
        allow_apply=False,
        games_writable=False,
        games_exists=True,
    )
    assert reason is not None
    assert 'ALLOW_HARDLINK_APPLY' in reason
    assert 'read-only' in reason.lower()


def test_degrade_reason_helpers_off_is_none():
    assert build_degrade_reason(
        helpers_enabled=False,
        allow_apply=False,
        games_writable=False,
        games_exists=True,
    ) is None


def test_preview_not_writable_reason(tmp_path, monkeypatch):
    src = tmp_path / 'a.bin'
    src.write_bytes(b'1234')
    dest_dir = tmp_path / 'out'
    dest_dir.mkdir()
    dest = dest_dir / 'b.bin'
    real_access = __import__('os').access

    def fake_access(path, mode):
        import os as _os
        if str(path) == str(dest_dir) and mode == _os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr('oneirodex.utils.hardlinks.os.access', fake_access)
    result = preview_hardlink(str(src), str(dest))
    assert result['would_succeed'] is False
    assert any('not writable' in r.lower() for r in result['reasons'])


def test_storage_status_api_ro(client, app, admin, tmp_path, monkeypatch):
    _login(client, app, admin)
    root = tmp_path / 'games'
    root.mkdir()
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', True)
    monkeypatch.setitem(app.config, 'ALLOW_HARDLINK_APPLY', False)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(root))
    real_access = __import__('os').access

    def fake_access(path, mode):
        import os as _os
        if str(path) == str(root) and mode == _os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr('oneirodex.utils.hardlinks.os.access', fake_access)
    resp = client.get('/api/storage/status')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['helpers_enabled'] is True
    assert body['allow_apply'] is False
    assert body['games_path'] == str(root)
    assert body['games_exists'] is True
    assert body['games_readable'] is True
    assert body['games_writable'] is False
    assert body['degrade_reason']
    assert 'read-only' in body['degrade_reason'].lower()
    assert 'ALLOW_HARDLINK_APPLY' in body['degrade_reason']


def test_storage_status_helpers_off(client, app, admin, tmp_path, monkeypatch):
    _login(client, app, admin)
    root = tmp_path / 'games'
    root.mkdir()
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', False)
    monkeypatch.setitem(app.config, 'ALLOW_HARDLINK_APPLY', False)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(root))
    resp = client.get('/api/storage/status')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['helpers_enabled'] is False
    assert body['allow_apply'] is False
    assert body['degrade_reason'] is None


def test_storage_status_apply_gated(client, app, admin, tmp_path, monkeypatch):
    _login(client, app, admin)
    root = tmp_path / 'games'
    root.mkdir()
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', True)
    monkeypatch.setitem(app.config, 'ALLOW_HARDLINK_APPLY', False)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(root))
    body = client.get('/api/storage/status').get_json()
    assert body['helpers_enabled'] is True
    assert body['allow_apply'] is False
    assert 'ALLOW_HARDLINK_APPLY' in (body['degrade_reason'] or '')


def test_apply_api_gated_when_apply_off(client, app, admin, tmp_path, monkeypatch):
    _login(client, app, admin)
    src = tmp_path / 'a.bin'
    src.write_bytes(b'1234')
    dest = tmp_path / 'b.bin'
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', True)
    monkeypatch.setitem(app.config, 'ALLOW_HARDLINK_APPLY', False)
    monkeypatch.setattr(
        'oneirodex.utils.security.get_allowed_base_directories',
        lambda _app: [str(tmp_path)],
    )
    resp = client.post(
        '/api/storage/hardlink/apply',
        json={'source': str(src), 'dest': str(dest)},
    )
    assert resp.status_code == 403
    assert 'ALLOW_HARDLINK_APPLY' in (resp.get_json().get('error') or '')


def test_preview_api_helpers_off(client, app, admin, monkeypatch):
    _login(client, app, admin)
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', False)
    resp = client.post(
        '/api/storage/hardlink/preview',
        json={'source': '/a', 'dest': '/b'},
    )
    assert resp.status_code == 403


def test_build_storage_status_unit(tmp_path):
    root = tmp_path / 'g'
    root.mkdir()
    payload = build_storage_status(
        helpers_enabled=True,
        allow_apply=True,
        games_path=str(root),
    )
    assert payload['helpers_enabled'] is True
    assert payload['allow_apply'] is True
    assert payload['games_exists'] is True
    assert payload['degrade_reason'] is None
