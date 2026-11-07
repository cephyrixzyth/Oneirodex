"""Save-state layer (Phase 4): resume on tiles, slot vocabulary, the shell's prompt.

Storage existed (`EmulatorSave`, `/api/games/<uuid>/saves`); what was missing
was the member-facing half — a tile that says *Resume*, a shell that asks
before loading, an auto-state on quit, named quick saves. The backend bits are
behavioural tests; the shell bits are source assertions, because a missing
resume bar still renders a playable room and nothing else would notice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.emulator_saves import (
    AUTO_STATE_SLOT,
    CLOUD_SRAM_SLOT,
    CLOUD_STATE_SLOT,
    QUICK_SAVE_PREFIX,
    is_state_slot,
    latest_state_by_game,
    audit_save_storage,
)

ROOT = Path(__file__).resolve().parents[1]
WEBRETRO = ROOT / 'oneirodex' / 'static' / 'vendor' / 'webretro'


def _library(db_session):
    library = Library(name=f'NES {uuid4().hex[:8]}', platform=LibraryPlatform.NES, display_order=1)
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, library):
    game = Game(
        uuid=str(uuid4()),
        name=f'Save probe {uuid4().hex[:6]}',
        library_uuid=library.uuid,
        full_disk_path=f'/test/saves/{uuid4().hex}.nes',
    )
    db_session.add(game)
    db_session.commit()
    return game


def _user(db_session):
    tag = uuid4().hex[:8]
    user = User(
        name=f'saves-{tag}', email=f'saves-{tag}@example.com', password_hash='unused',
        role='user', user_id=str(uuid4()), state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _row(db_session, user, game, slot, *, filename='cloud.state', age_minutes=0):
    when = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    row = EmulatorSave(
        user_id=user.id, game_uuid=game.uuid, slot_name=slot, filename=filename,
        size_bytes=3, storage_path=f'/nonexistent/{uuid4().hex}', encrypted=False,
        created_at=when, updated_at=when,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# --- slot vocabulary ---------------------------------------------------------


def test_state_slots_are_states_and_sram_is_not():
    def row(slot, filename='cloud.state'):
        return EmulatorSave(slot_name=slot, filename=filename)

    assert is_state_slot(row(AUTO_STATE_SLOT))
    assert is_state_slot(row(CLOUD_STATE_SLOT))
    assert is_state_slot(row('cloud1'))  # legacy Wave 7 placeholder
    assert is_state_slot(row(QUICK_SAVE_PREFIX + 'before-boss'))
    assert not is_state_slot(row(CLOUD_SRAM_SLOT, 'cloud.srm'))
    # An older ad-hoc slot is judged by what it holds.
    assert is_state_slot(row('slot1', 'game.state'))
    assert not is_state_slot(row('slot1', 'game.srm'))


# --- latest state per game, one query ----------------------------------------


def test_latest_state_by_game_picks_the_newest_state_and_skips_sram(db_session):
    user = _user(db_session)
    library = _library(db_session)
    played = _game(db_session, library)
    sram_only = _game(db_session, library)
    untouched = _game(db_session, library)

    _row(db_session, user, played, CLOUD_STATE_SLOT, age_minutes=60)
    newest = _row(db_session, user, played, AUTO_STATE_SLOT, age_minutes=5)
    _row(db_session, user, played, CLOUD_SRAM_SLOT, filename='cloud.srm', age_minutes=1)
    _row(db_session, user, sram_only, CLOUD_SRAM_SLOT, filename='cloud.srm')

    latest = latest_state_by_game(user.id, [played.uuid, sram_only.uuid, untouched.uuid])
    assert set(latest) == {played.uuid}
    assert latest[played.uuid]['slot_name'] == AUTO_STATE_SLOT
    assert latest[played.uuid]['updated_at'] == newest.updated_at.isoformat()

    # Someone else's states are not mine.
    other = _user(db_session)
    assert latest_state_by_game(other.id, [played.uuid]) == {}
    assert latest_state_by_game(None, [played.uuid]) == {}
    assert latest_state_by_game(user.id, []) == {}


def test_saves_api_lists_newest_first_and_flags_states(client, db_session, configured_install):
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _row(db_session, user, game, CLOUD_STATE_SLOT, age_minutes=30)
    _row(db_session, user, game, CLOUD_SRAM_SLOT, filename='cloud.srm', age_minutes=20)
    _row(db_session, user, game, QUICK_SAVE_PREFIX + 'lab', age_minutes=2)

    _login(client, user)
    body = client.get(f'/api/games/{game.uuid}/saves').get_json()
    slots = [(row['slot_name'], row['is_state']) for row in body['saves']]
    assert slots == [
        (QUICK_SAVE_PREFIX + 'lab', True),
        (CLOUD_SRAM_SLOT, False),
        (CLOUD_STATE_SLOT, True),
    ]


def test_browse_tile_carries_resume_state(client, db_session, configured_install):
    """The tile reads `resume_state` to say Resume instead of Play."""
    user = _user(db_session)
    library = _library(db_session)
    played = _game(db_session, library)
    fresh = _game(db_session, library)
    _row(db_session, user, played, AUTO_STATE_SLOT, age_minutes=3)

    _login(client, user)
    response = client.get(f'/browse_games?library_uuid={library.uuid}&per_page=50')
    assert response.status_code == 200, response.get_json()
    games = {row['uuid']: row for row in response.get_json()['games']}
    assert games[played.uuid]['resume_state']['slot_name'] == AUTO_STATE_SLOT
    assert games[played.uuid]['resume_state']['updated_at']
    assert games[fresh.uuid]['resume_state'] is None


def test_uploading_a_state_updates_the_resume_summary(client, db_session, configured_install, tmp_path, app):
    """Store a state through the API and the tile summary follows it."""
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _login(client, user)

    response = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': AUTO_STATE_SLOT, 'file': (BytesIO(b'state-bytes'), 'cloud.state')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 201, response.get_json()
    latest = latest_state_by_game(user.id, [game.uuid])
    assert latest[game.uuid]['slot_name'] == AUTO_STATE_SLOT


def test_invalid_expected_revision_returns_bad_request_without_writing(
    client, db_session, configured_install, tmp_path, app,
):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _login(client, user)

    response = client.post(
        f'/api/games/{game.uuid}/saves',
        data={
            'slot': AUTO_STATE_SLOT,
            'expected_revision': 'not-a-number',
            'file': (BytesIO(b'state-bytes'), 'cloud.state'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    assert db_session.query(EmulatorSave).filter_by(user_id=user.id, game_uuid=game.uuid).count() == 0
    assert not (tmp_path / str(user.id) / game.uuid).exists()


def test_save_quota_counts_all_games_for_the_member(client, db_session, configured_install, tmp_path, app):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1
    user = _user(db_session)
    library = _library(db_session)
    existing_game = _game(db_session, library)
    target_game = _game(db_session, library)
    db_session.add(EmulatorSave(
        user_id=user.id,
        game_uuid=existing_game.uuid,
        slot_name='existing',
        filename='existing.state',
        size_bytes=1024 * 1024,
        storage_path=str(tmp_path / 'existing.state'),
        encrypted=False,
    ))
    db_session.commit()
    _login(client, user)

    response = client.post(
        f'/api/games/{target_game.uuid}/saves',
        data={'slot': 'new-slot', 'file': (BytesIO(b'new-state'), 'new.state')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 413
    assert response.get_json()['error_code'] == 'payload_too_large'
    assert not (tmp_path / str(user.id) / target_game.uuid).exists()


def test_save_quota_charges_only_replacement_growth(client, db_session, configured_install, tmp_path, app):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    old_path = tmp_path / 'old.state'
    old_path.write_bytes(b'old')
    db_session.add(EmulatorSave(
        user_id=user.id,
        game_uuid=game.uuid,
        slot_name='replace-me',
        filename='old.state',
        size_bytes=1024 * 1024,
        storage_path=str(old_path),
        encrypted=False,
    ))
    db_session.commit()
    _login(client, user)

    response = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'replace-me', 'file': (BytesIO(b'new-state'), 'new.state')},
        content_type='multipart/form-data',
    )

    # The old generation remains charged against quota, so a replacement that
    # would exceed the aggregate retained-byte budget is rejected.
    assert response.status_code == 413, response.get_json()
    saved = db_session.query(EmulatorSave).filter_by(
        user_id=user.id, game_uuid=game.uuid, slot_name='replace-me',
    ).one()
    assert saved.size_bytes == 1024 * 1024
    assert old_path.read_bytes() == b'old'


def test_save_replacement_keeps_prior_generation_and_uses_unique_paths(
    client, db_session, configured_install, tmp_path, app, monkeypatch,
):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    from oneirodex.utils import emulator_saves

    synced_directories = []
    monkeypatch.setattr(
        emulator_saves, '_fsync_directory',
        lambda directory: synced_directories.append(Path(directory).resolve()) or True,
    )
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _login(client, user)
    first = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'a/b', 'file': (BytesIO(b'first'), 'same.state')},
        content_type='multipart/form-data',
    )
    assert first.status_code == 201
    first_row = db_session.query(EmulatorSave).filter_by(user_id=user.id, game_uuid=game.uuid).one()
    old_path = Path(first_row.storage_path)
    second = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'a?b', 'file': (BytesIO(b'second'), 'same.state')},
        content_type='multipart/form-data',
    )
    assert second.status_code == 201
    rows = db_session.query(EmulatorSave).filter_by(user_id=user.id, game_uuid=game.uuid).all()
    assert len(rows) == 2
    assert rows[0].storage_path != rows[1].storage_path
    assert old_path.read_bytes() == b'first'
    assert db_session.query(EmulatorSaveGeneration).count() == 0

    replacement = client.post(
        f'/api/games/{game.uuid}/saves',
        data={
            'slot': 'a/b', 'expected_revision': '1',
            'file': (BytesIO(b'updated'), 'same.state'),
        },
        content_type='multipart/form-data',
    )
    assert replacement.status_code == 201
    assert len(synced_directories) == 3
    assert all(path.is_relative_to(tmp_path.resolve()) for path in synced_directories)
    active = db_session.query(EmulatorSave).filter_by(
        user_id=user.id, game_uuid=game.uuid, slot_name='a/b',
    ).one()
    history = db_session.query(EmulatorSaveGeneration).filter_by(save_id=active.id).one()
    assert Path(history.storage_path).read_bytes() == b'first'
    assert Path(active.storage_path).read_bytes() == b'updated'
    stale = client.post(
        f'/api/games/{game.uuid}/saves',
        data={
            'slot': 'a/b', 'expected_revision': '1',
            'file': (BytesIO(b'stale'), 'stale.state'),
        },
        content_type='multipart/form-data',
    )
    assert stale.status_code == 409
    assert stale.get_json()['detail']['current_revision'] == 2


def test_directory_sync_failure_keeps_old_pointer_and_is_reported_as_orphan(
    client, db_session, configured_install, tmp_path, app, monkeypatch,
):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _login(client, user)
    initial = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'slot', 'file': (BytesIO(b'committed'), 'old.state')},
        content_type='multipart/form-data',
    )
    assert initial.status_code == 201
    row = db_session.query(EmulatorSave).filter_by(
        user_id=user.id, game_uuid=game.uuid, slot_name='slot',
    ).one()
    old_path = Path(row.storage_path)

    from oneirodex.utils import emulator_saves

    def fail_directory_sync(_directory):
        raise OSError('synthetic directory sync failure')

    monkeypatch.setattr(emulator_saves, '_fsync_directory', fail_directory_sync)
    failed = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'slot', 'file': (BytesIO(b'not committed'), 'new.state')},
        content_type='multipart/form-data',
    )
    assert failed.status_code == 500
    db_session.expire_all()
    unchanged = db_session.query(EmulatorSave).filter_by(id=row.id).one()
    assert unchanged.storage_path == str(old_path)
    assert old_path.read_bytes() == b'committed'
    audit = audit_save_storage(db_session, tmp_path)
    assert audit['complete'] is True
    assert audit['mutated_files'] is False
    assert audit['referenced_files'] == 1
    assert audit['unreferenced_files'] == 1


def test_save_storage_audit_reports_missing_and_shared_root_references(db_session, tmp_path):
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    existing_path = tmp_path / 'existing.save'
    existing_path.write_bytes(b'save')
    missing_path = tmp_path / 'missing.save'
    db_session.add_all([
        EmulatorSave(
            user_id=user.id, game_uuid=game.uuid, slot_name='one', filename='one.state',
            size_bytes=4, storage_path=str(existing_path),
        ),
        EmulatorSave(
            user_id=user.id, game_uuid=game.uuid, slot_name='two', filename='two.state',
            size_bytes=4, storage_path=str(missing_path),
        ),
    ])
    db_session.commit()
    (tmp_path / 'orphan.save').write_bytes(b'orphan')
    outside = tmp_path.parent / 'outside.save'
    outside.write_bytes(b'outside')
    try:
        db_session.add(EmulatorSave(
            user_id=user.id, game_uuid=game.uuid, slot_name='three', filename='three.state',
            size_bytes=7, storage_path=str(outside),
        ))
        db_session.commit()

        audit = audit_save_storage(db_session, tmp_path)

        assert audit == {
            'root_available': True,
            'complete': True,
            'entry_limit': 100_000,
            'entries_scanned': 2,
            'regular_files': 2,
            'referenced_files': 2,
            'missing_references': 1,
            'outside_root_references': 1,
            'unreferenced_files': 1,
            'symlinks_skipped': 0,
            'scan_limit_reached': False,
            'mutated_files': False,
        }
        assert existing_path.exists() and (tmp_path / 'orphan.save').exists()
    finally:
        outside.unlink(missing_ok=True)


def test_failed_save_commit_keeps_previous_generation_readable(
    client, db_session, configured_install, tmp_path, app, monkeypatch,
):
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)
    _login(client, user)
    initial = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'slot', 'file': (BytesIO(b'committed'), 'old.state')},
        content_type='multipart/form-data',
    )
    assert initial.status_code == 201
    row = db_session.query(EmulatorSave).filter_by(user_id=user.id, game_uuid=game.uuid).one()
    prior_path = Path(row.storage_path)
    from oneirodex.runtime_native.db_session import native_db
    session = native_db.session()
    real_commit = session.commit

    def fail_commit():
        raise RuntimeError('simulated database failure')

    monkeypatch.setattr(session, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='simulated database failure'):
        from oneirodex.utils.emulator_saves import store_save
        store_save(
            user_id=user.id, game_uuid=game.uuid, slot_name='slot',
            file_storage=BytesIO(b'uncommitted'),
        )
    monkeypatch.setattr(session, 'commit', real_commit)
    db_session.expire_all()
    unchanged = db_session.query(EmulatorSave).filter_by(id=row.id).one()
    assert unchanged.storage_path == str(prior_path)
    assert prior_path.read_bytes() == b'committed'


# --- the shell ---------------------------------------------------------------


def test_shell_asks_before_loading_and_saves_on_leave():
    shell = (WEBRETRO / 'webretro.html').read_text(encoding='utf-8')
    bridge = (WEBRETRO / 'od-bridge.js').read_text(encoding='utf-8')

    # Boot pull imports with autoLoad:false and the resume bar is the only
    # path to od-load-state from a pulled state.
    assert 'autoLoad: false' in shell
    assert 'id="od-resume-bar"' in shell
    assert "getElementById('od-resume-yes')" in shell
    assert 'data.autoLoad !== false' in bridge
    assert 'autoLoaded = autoLoad ? tryLoadState() : false' in bridge

    # Auto-state on quit: Back / Power go through the autosave, capped, with
    # keepalive so the upload survives the navigation.
    assert 'function goBackToLibrary()' in shell
    assert "autoSaveState({ keepalive: true })" in shell
    assert 'keepalive: !!(opts && opts.keepalive)' in shell
    assert "document.addEventListener('visibilitychange'" in shell

    # Named quick saves + the slot vocabulary the backend understands.
    assert 'id="od-saves-panel"' in shell
    assert 'id="od-saves-form"' in shell
    assert f"var AUTO_SLOT = '{AUTO_STATE_SLOT}'" in shell
    assert f"var SYNC_SLOT = '{CLOUD_STATE_SLOT}'" in shell
    assert f"var SRAM_SLOT = '{CLOUD_SRAM_SLOT}'" in shell
    assert f"var QS_PREFIX = '{QUICK_SAVE_PREFIX}'" in shell

    # A `?resume=<slot>` deep link from a tile or the details page is honoured.
    assert "String(args.resume || '')" in shell


def test_shell_never_auto_loads_a_pulled_state():
    """The pre-layer behaviour — `autoLoaded` straight after the boot pull —
    must not come back: the member decides."""
    shell = (WEBRETRO / 'webretro.html').read_text(encoding='utf-8')
    assert 'Cloud saves restored (state loaded)' not in shell


# --- Why no save ever reached the server, found live 2026-09-22 -------------
#
# He reported: "the badge doesnt update and loading manually does not load the
# save state". Two separate faults, both proven in the browser against the live
# box before these tests were written.


def test_the_saves_listing_hands_the_play_room_a_csrf_token(client, db_session, configured_install):
    """The room is a static file, so this listing is its only source of one.

    `webretro.html` is served from /static and never rendered, so its
    `<meta name="csrf-token">` is permanently empty, and the CSRF cookie is
    HttpOnly. Every upload and delete the room attempted was therefore rejected
    with "The CSRF token is missing" -- which is why the save list stayed empty
    and the resume badge never moved.
    """
    user = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library)

    _login(client, user)
    body = client.get(f'/api/games/{game.uuid}/saves').get_json()
    assert body['csrf_token'], 'the room has no other way to obtain a token'


def test_the_room_sends_the_token_the_listing_gave_it():
    shell = (WEBRETRO / 'webretro.html').read_text(encoding='utf-8')

    # Remembered from the listing, and fetched on demand if a write comes first.
    assert 'function rememberCsrf(' in shell
    assert 'function withCsrf(' in shell
    assert 'rememberCsrf(body.csrf_token)' in shell

    # Both writing paths go through it rather than reading an empty meta tag.
    for fn in ('function uploadSlot(', 'function deleteSlot('):
        at = shell.index(fn)
        body = shell[at:at + 900]
        assert 'withCsrf()' in body, fn
        assert "'X-CSRFToken': csrfToken()" not in body, fn


def test_an_export_waits_for_the_state_to_stop_growing():
    """The second fault: a save state that uploaded 8 bytes and would not load.

    RetroArch writes the state's RZIP header immediately and compresses the
    payload over the next second or three; webretro copies the file into
    IndexedDB from its write callback, so a read taken straight after the save
    command returns the header alone. The bridge used to accept the first
    non-empty read.
    """
    bridge = (WEBRETRO / 'od-bridge.js').read_text(encoding='utf-8')

    # Retries carry the previous length and stop only when it stops growing …
    assert 'function exportWithRetries(done, attempt, lastLen)' in bridge
    assert 'len <= seen' in bridge
    # … and never settle on something too small to be a state.
    assert 'MIN_STATE_BYTES' in bridge
    assert 'bytes >= MIN_STATE_BYTES' in bridge
    # The tail has to outlast the compression, not just the first frame.
    assert 'EXPORT_DELAYS_MS = [200, 400, 800, 1200, 1600, 2000]' in bridge
    # The file being written wins over the IndexedDB copy of it.
    assert 'onDisk.length > state.length' in bridge
    # A zero-length array must read as nothing, not as an empty base64 string.
    assert 'if (!bytes.length) return null;' in bridge


def test_the_shell_cache_key_moved_with_the_bridge():
    """base.js / od-bridge.js are cached for an hour with no validator, so a
    fix to either only reaches a returning member when this key changes -- and
    the two files must agree or the room loads a mismatched pair."""
    shell = (WEBRETRO / 'webretro.html').read_text(encoding='utf-8')
    standalone = (WEBRETRO / 'standalone.html').read_text(encoding='utf-8')

    key = shell.split("'&_gt=")[1].split("'")[0]
    assert f'od-bridge.js?v={key}' in standalone
    assert f'base.js?v={key}' in standalone
    assert key != 'save-states-1', 'the key must move when the bridge does'

