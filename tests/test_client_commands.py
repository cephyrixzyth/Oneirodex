"""Unit tests for companion command queue (no DB)."""

from datetime import datetime, timedelta, timezone

from oneirodex.utils import client_commands as cc


def test_enqueue_and_claim_pending_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))

    first = cc.enqueue_client_command(9, 'game-a', 'install')
    second = cc.enqueue_client_command(9, 'game-b', 'uninstall')
    assert first['status'] == 'pending'
    assert first['action'] == 'install'

    claimed = cc.claim_pending_commands(9)
    assert {row['game_uuid'] for row in claimed} == {'game-a', 'game-b'}
    assert cc.claim_pending_commands(9) == []


def test_enqueue_dedupes_same_game_action(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))

    cc.enqueue_client_command(1, 'game-a', 'install')
    cc.enqueue_client_command(1, 'game-a', 'install')
    claimed = cc.claim_pending_commands(1)
    assert len(claimed) == 1
    assert claimed[0]['action'] == 'install'


def test_enqueue_update_pack_includes_kind_and_version(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))

    command = cc.enqueue_client_command(
        2,
        'game-a',
        'update',
        kind='update',
        version_uuid='upd-9',
    )
    assert command['kind'] == 'update'
    assert command['version_uuid'] == 'upd-9'
    claimed = cc.claim_pending_commands(2)
    assert claimed[0]['kind'] == 'update'
    assert claimed[0]['version_uuid'] == 'upd-9'


def test_enqueue_rejects_invalid_action(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    try:
        cc.enqueue_client_command(1, 'game-a', 'launch')
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'action' in str(exc)


def test_ack_removes_in_flight_and_nack_requeues(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))

    command = cc.enqueue_client_command(3, 'game-a', 'install')
    claimed = cc.claim_pending_commands(3)
    assert len(claimed) == 1
    assert claimed[0]['id'] == command['id']
    assert cc.claim_pending_commands(3) == []

    assert cc.nack_client_commands(3, [command['id']]) == 1
    reclaimed = cc.claim_pending_commands(3)
    assert len(reclaimed) == 1
    assert reclaimed[0]['id'] == command['id']

    assert cc.ack_client_commands(3, [command['id']]) == 1
    assert cc.claim_pending_commands(3) == []


def test_stale_in_flight_is_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    monkeypatch.setattr(cc, '_IN_FLIGHT_TTL_SECONDS', 1)

    command = cc.enqueue_client_command(4, 'game-a', 'update')
    claimed = cc.claim_pending_commands(4)
    assert claimed[0]['id'] == command['id']

    path = cc._store_path(4)
    queue = cc._read_queue(path)
    queue[0]['claimed_at'] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    cc._write_queue(path, queue)

    again = cc.claim_pending_commands(4)
    assert len(again) == 1
    assert again[0]['id'] == command['id']


def test_apply_patch_requires_flag_and_extra_version(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    monkeypatch.setattr(cc, 'rom_patch_apply_enabled', lambda: False)
    try:
        cc.enqueue_client_command(
            5, 'game-a', 'apply_patch', kind='extra', version_uuid='patch-1'
        )
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'ENABLE_ROM_PATCH_APPLY' in str(exc)

    monkeypatch.setattr(cc, 'rom_patch_apply_enabled', lambda: True)
    try:
        cc.enqueue_client_command(5, 'game-a', 'apply_patch')
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'kind=extra' in str(exc)

    command = cc.enqueue_client_command(
        5, 'game-a', 'apply_patch', kind='extra', version_uuid='patch-1'
    )
    assert command['action'] == 'apply_patch'
    assert command['version_uuid'] == 'patch-1'


def _prep_open_path_roots(tmp_path, monkeypatch):
    games = tmp_path / 'games'
    games.mkdir()
    target = games / 'Some Title'
    target.mkdir()
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    monkeypatch.setattr(cc, '_open_path_allowed_bases', lambda: [str(games)])
    return games, target


def test_open_path_enqueue_and_claim_without_game_uuid(tmp_path, monkeypatch):
    _games, target = _prep_open_path_roots(tmp_path, monkeypatch)

    command = cc.enqueue_client_command(
        7, '', 'open_path', path=str(target), select=True
    )
    assert command['action'] == 'open_path'
    assert command['game_uuid'] == ''
    assert command['path'] == str(target)
    assert command['select'] is True

    claimed = cc.claim_pending_commands(7)
    assert len(claimed) == 1
    assert claimed[0]['action'] == 'open_path'
    assert claimed[0]['path'] == str(target)
    assert claimed[0]['select'] is True
    assert claimed[0]['game_uuid'] == ''


def test_open_path_rejects_outside_allowlist(tmp_path, monkeypatch):
    games, _target = _prep_open_path_roots(tmp_path, monkeypatch)
    outside = tmp_path / 'elsewhere' / 'secret'
    outside.mkdir(parents=True)

    try:
        cc.enqueue_client_command(8, '', 'open_path', path=str(outside))
        assert False, 'expected ValueError'
    except ValueError as exc:
        msg = str(exc).lower()
        assert 'outside' in msg or 'denied' in msg or 'allowed' in msg

    # Relative paths rejected even under an allowlisted name.
    try:
        cc.enqueue_client_command(8, '', 'open_path', path='games/Some Title')
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'absolute' in str(exc).lower()

    # Missing path rejected.
    try:
        cc.enqueue_client_command(8, 'game-a', 'open_path')
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'path' in str(exc).lower()

    # Sanity: still can enqueue under the allowlisted root.
    nested = games / 'ok'
    nested.mkdir()
    ok = cc.enqueue_client_command(8, 'game-a', 'open_path', path=str(nested), select=False)
    assert ok['path'] == str(nested)
    assert ok['select'] is False
    assert ok['game_uuid'] == 'game-a'


def test_open_path_dedupes_same_path(tmp_path, monkeypatch):
    _games, target = _prep_open_path_roots(tmp_path, monkeypatch)
    other = _games / 'Other'
    other.mkdir()

    cc.enqueue_client_command(9, '', 'open_path', path=str(target))
    cc.enqueue_client_command(9, '', 'open_path', path=str(target))
    cc.enqueue_client_command(9, '', 'open_path', path=str(other))
    claimed = cc.claim_pending_commands(9)
    assert len(claimed) == 2
    assert {row['path'] for row in claimed} == {str(target), str(other)}


def test_open_path_uses_native_runtime_config_without_flask_context(tmp_path, monkeypatch):
    from oneirodex.runtime_native.runtime_context import runtime_config_scope

    games = tmp_path / 'native-games'
    games.mkdir()
    target = games / 'Title'
    target.mkdir()
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path / 'queue'))
    config = {
        'DATA_FOLDER_GAMES': str(games),
        'BASE_FOLDER_WINDOWS': None,
        'BASE_FOLDER_POSIX': None,
        'ONEIRODEX_LIBRARY_ROOTS': '',
    }

    with runtime_config_scope(config):
        assert str(games) in cc._open_path_allowed_bases()
        command = cc.enqueue_client_command(18, '', 'open_path', path=str(target))

    assert command['path'] == str(target)


def test_targeted_lease_redelivery_rejects_stale_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    command = cc.enqueue_client_command(3, 'game', 'install', target_device_id='den')
    assert not cc.claim_pending_commands(3, device_id='kitchen')
    assert not cc.claim_pending_commands(3)
    first, = cc.claim_pending_commands(3, device_id='den')
    lease = first['lease_id']
    assert cc.ack_client_commands(3, [command['id']]) == 0
    assert not cc.finish_leased_command(3, command['id'], 'kitchen', lease, 'ok')
    cc.claim_pending_commands(3, device_id='den', renew_lease=lease)
    path = cc._store_path(3)
    stored = cc._read_queue(path)
    stored[0]['claimed_at'] = '2000-01-01T01:00:00+00:00'
    cc._write_queue(path, stored)
    second, = cc.claim_pending_commands(3, device_id='den')
    assert second['lease_id'] != lease
    assert not cc.finish_leased_command(3, command['id'], 'den', lease, 'ok')
    assert cc.finish_leased_command(3, command['id'], 'den', second['lease_id'], 'busy')
    assert not cc.claim_pending_commands(3, device_id='den')
    stored = cc._read_queue(path)
    stored[0]['retry_at'] = '2000-01-01T01:00:00+00:00'
    cc._write_queue(path, stored)
    third, = cc.claim_pending_commands(3, device_id='den')
    assert cc.finish_leased_command(3, command['id'], 'den', third['lease_id'], 'error')
    assert cc._read_queue(path)[0]['status'] == 'failed'
    assert not cc.nack_client_commands(3, [command['id']])
    assert not cc.ack_client_commands(3, [command['id']])
    assert cc.command_status_for_game(3, 'game')[0]['status'] == 'failed'
    assert cc.command_status_for_game(4, 'game') == []
    assert not cc.claim_pending_commands(3, device_id='den')


def test_queue_pressure_keeps_active_commands(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    for idx in range(50):
        cc.enqueue_client_command(7, str(idx), 'install')
    first, = cc.claim_pending_commands(7, device_id='one', limit=1)
    with pytest.raises(ValueError, match='queue is full'):
        cc.enqueue_client_command(7, 'over-limit', 'download')
    assert len(cc._read_queue(cc._store_path(7))) == 50
    assert cc.finish_leased_command(7, first['id'], 'one', first['lease_id'], 'ok')
