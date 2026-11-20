"""Tests for optional library root-folder incremental watch."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from oneirodex.models import Game, Library, ScanJob
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_health import PATH_STATUS_MISSING, PATH_STATUS_OK
from oneirodex.utils.library_watch import (
    LibraryWatchController,
    _reset_library_watch_for_tests,
    classify_watch_path,
    get_library_watch_status,
    has_active_or_queued_scan,
    is_library_watch_enabled,
    library_should_watch,
    library_watch_debounce_seconds,
    list_watchable_libraries,
    start_library_watch,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- filesystem library watcher.


@pytest.fixture(autouse=True)
def _reset_watch_env(monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_WATCH', raising=False)
    monkeypatch.delenv('ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC', raising=False)
    monkeypatch.delenv('ONEIRODEX_LIBRARY_WATCH', raising=False)
    monkeypatch.delenv('ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC', raising=False)
    _reset_library_watch_for_tests()
    yield
    _reset_library_watch_for_tests()


@pytest.fixture(autouse=True)
def _clean_scan_jobs(db_session):
    try:
        db_session.execute(text('TRUNCATE TABLE scan_jobs RESTART IDENTITY CASCADE'))
        db_session.commit()
    except Exception:
        db_session.rollback()
    yield


@pytest.fixture
def sample_library(db_session, tmp_path):
    root = tmp_path / 'games'
    root.mkdir()
    (root / 'CoolGame').mkdir()
    library = Library(
        name=f'WatchLib_{uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
        scan_depth=1,
        last_scan_folder=str(root),
    )
    db_session.add(library)
    db_session.commit()
    return library, root


class TestEnableDisable:
    def test_disabled_by_default(self):
        assert is_library_watch_enabled() is False

    def test_enabled_truthy(self, monkeypatch):
        for value in ('1', 'true', 'YES', 'on'):
            monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH', value)
            assert is_library_watch_enabled() is True

    def test_disabled_falsy(self, monkeypatch):
        for value in ('0', 'false', 'no', 'off', ''):
            monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH', value)
            assert is_library_watch_enabled() is False

    def test_debounce_clamped(self, monkeypatch):
        assert library_watch_debounce_seconds() == 3.0
        monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC', '1')
        assert library_watch_debounce_seconds() == 2.0
        monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC', '9')
        assert library_watch_debounce_seconds() == 5.0
        monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC', '2.5')
        assert library_watch_debounce_seconds() == 2.5

    def test_start_noop_when_disabled(self, app):
        with app.app_context():
            assert start_library_watch(app) is None
        status = get_library_watch_status()
        assert status['enabled'] is False
        assert status['running'] is False


class TestClassifyWatchPath:
    def test_depth1_add_game_folder(self, tmp_path):
        root = tmp_path / 'lib'
        game = root / 'NewGame'
        root.mkdir()
        game.mkdir()
        result = classify_watch_path(
            str(root), str(game), 1, event_type='created', is_directory=True
        )
        assert result is not None
        assert result['kind'] == 'add'
        assert os.path.basename(result['game_path']).lower() == 'newgame'

    def test_depth1_delete_game_folder(self, tmp_path):
        root = tmp_path / 'lib'
        root.mkdir()
        gone = root / 'GoneGame'
        result = classify_watch_path(
            str(root), str(gone), 1, event_type='deleted', is_directory=True
        )
        assert result is not None
        assert result['kind'] == 'delete'

    def test_depth1_change_inside_game(self, tmp_path):
        root = tmp_path / 'lib'
        game = root / 'CoolGame'
        nested = game / 'readme.txt'
        root.mkdir()
        game.mkdir()
        nested.write_text('hi')
        result = classify_watch_path(
            str(root), str(nested), 1, event_type='modified', is_directory=False
        )
        assert result is not None
        assert result['kind'] == 'change'
        assert os.path.basename(result['game_path']).lower() == 'coolgame'

    def test_ignores_deep_arcade_rom_noise(self, tmp_path):
        root = tmp_path / 'lib'
        deep = root / 'MameSet' / 'roms' / 'game.zip'
        root.mkdir()
        (root / 'MameSet' / 'roms').mkdir(parents=True)
        deep.write_bytes(b'x')
        result = classify_watch_path(
            str(root), str(deep), 1, event_type='created', is_directory=False
        )
        assert result is None

    def test_depth2_letter_bucket_game(self, tmp_path):
        root = tmp_path / 'pc'
        game = root / '_b' / 'Baldurs Gate'
        root.mkdir()
        game.mkdir(parents=True)
        result = classify_watch_path(
            str(root), str(game), 2, event_type='created', is_directory=True
        )
        assert result is not None
        assert result['kind'] == 'add'
        assert result['game_path'].lower().endswith('baldurs gate')

    def test_depth2_ignores_letter_bucket_alone(self, tmp_path):
        root = tmp_path / 'pc'
        bucket = root / '_a'
        root.mkdir()
        bucket.mkdir()
        result = classify_watch_path(
            str(root), str(bucket), 2, event_type='created', is_directory=True
        )
        assert result is None


class TestEnqueueOnSyntheticEvents:
    def _seed_controller(self, app, library, root, fake_enqueue):
        ctrl = LibraryWatchController(
            app,
            debounce_seconds=30.0,  # do not auto-flush; tests call _flush_pending
            enqueue_fn=fake_enqueue,
            observer_factory=lambda: MagicMock(is_alive=MagicMock(return_value=False)),
        )
        root_n = os.path.normcase(os.path.normpath(os.path.abspath(str(root))))
        ctrl._root_meta = {
            root_n: {
                'uuid': library.uuid,
                'name': library.name,
                'folder': str(root),
                'scan_depth': 1,
            }
        }
        ctrl._running = True
        return ctrl

    def test_enqueue_after_debounce(self, app, db_session, sample_library):
        library, root = sample_library
        enqueues = []

        def fake_enqueue(**kwargs):
            enqueues.append(kwargs)
            return {
                'status': 'queued',
                'job_id': 'job-test',
                'position': 1,
                'message': 'queued',
            }

        with app.app_context():
            ctrl = self._seed_controller(app, library, root, fake_enqueue)
            new_game = root / 'BrandNew'
            new_game.mkdir()
            ctrl.handle_raw_event(
                src_path=str(new_game),
                event_type='created',
                is_directory=True,
            )
            assert library.uuid in ctrl._pending
            ctrl._flush_pending()

        assert len(enqueues) == 1
        assert enqueues[0]['library_uuid'] == library.uuid
        assert enqueues[0]['folder_path'] == str(root)
        assert enqueues[0]['queue_policy'] == 'queue'
        assert enqueues[0]['remove_missing'] is False

    def test_delete_honors_remove_missing_policy(
        self, app, db_session, sample_library
    ):
        library, root = sample_library
        prior = ScanJob(
            folders={str(root): True},
            content_type='Games',
            status='Completed',
            is_enabled=True,
            last_run=datetime.now(timezone.utc),
            library_uuid=library.uuid,
            scan_folder=str(root),
            setting_remove=True,
        )
        db_session.add(prior)
        db_session.commit()

        enqueues = []

        def fake_enqueue(**kwargs):
            enqueues.append(kwargs)
            return {'status': 'started', 'job_id': 'j2', 'position': None, 'message': 'ok'}

        with app.app_context():
            ctrl = self._seed_controller(app, library, root, fake_enqueue)
            ctrl.handle_raw_event(
                src_path=str(root / 'CoolGame'),
                event_type='deleted',
                is_directory=True,
            )
            ctrl._flush_pending()

        assert len(enqueues) == 1
        assert enqueues[0]['remove_missing'] is True

    def test_skips_when_scan_already_queued(
        self, app, db_session, sample_library
    ):
        library, root = sample_library
        job = ScanJob(
            folders={str(root): True},
            content_type='Games',
            status='Queued',
            is_enabled=True,
            last_run=datetime.now(timezone.utc),
            library_uuid=library.uuid,
            scan_folder=str(root),
        )
        db_session.add(job)
        db_session.commit()

        enqueues = []

        def fake_enqueue(**kwargs):
            enqueues.append(kwargs)
            return {'status': 'queued', 'job_id': 'x', 'position': 1, 'message': 'q'}

        with app.app_context():
            assert has_active_or_queued_scan(library.uuid, str(root)) is True
            ctrl = self._seed_controller(app, library, root, fake_enqueue)
            ctrl.handle_raw_event(
                src_path=str(root / 'CoolGame' / 'file.txt'),
                event_type='modified',
                is_directory=False,
            )
            ctrl._flush_pending()

        assert enqueues == []

    def test_add_clears_path_status_missing_to_ok(
        self, app, db_session, sample_library
    ):
        library, root = sample_library
        restored = root / 'CoolGame'
        assert restored.is_dir()
        game = Game(
            uuid=str(uuid4()),
            name='CoolGame',
            library_uuid=library.uuid,
            full_disk_path=str(restored),
            path_status=PATH_STATUS_MISSING,
        )
        db_session.add(game)
        db_session.commit()

        enqueues = []

        def fake_enqueue(**kwargs):
            enqueues.append(kwargs)
            return {
                'status': 'queued',
                'job_id': 'job-restore',
                'position': 1,
                'message': 'queued',
            }

        with app.app_context():
            ctrl = self._seed_controller(app, library, root, fake_enqueue)
            ctrl.handle_raw_event(
                src_path=str(restored),
                event_type='created',
                is_directory=True,
            )
            ctrl._flush_pending()

        assert len(enqueues) == 1
        refreshed = db_session.execute(
            select(Game).where(Game.uuid == game.uuid)
        ).scalar_one()
        assert refreshed.path_status == PATH_STATUS_OK


class TestPerLibraryWatchOptOut:
    def test_opt_out_excluded_from_watchable(self, app, db_session, sample_library, monkeypatch):
        library, root = sample_library
        monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH', '1')
        # db_session fixture already provides app_context — do not nest another.
        assert library_should_watch(library) is True
        uuids = {row['uuid'] for row in list_watchable_libraries()}
        assert library.uuid in uuids

        library.watch_enabled = False
        db_session.commit()
        db_session.refresh(library)
        assert library.watch_enabled is False
        assert library_should_watch(library) is False
        uuids = {row['uuid'] for row in list_watchable_libraries()}
        assert library.uuid not in uuids

    def test_env_off_never_watches_even_when_true(
        self, app, db_session, sample_library, monkeypatch
    ):
        library, _root = sample_library
        monkeypatch.delenv('ONEIRODEX_LIBRARY_WATCH', raising=False)
        library.watch_enabled = True
        db_session.commit()
        assert library_should_watch(library) is False


class TestOpsPulse:
    def test_services_includes_library_watch(self, app, monkeypatch):
        monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH', '0')
        with app.app_context():
            from oneirodex.utils.ops_summary import _library_watch_pulse

            pulse = _library_watch_pulse()
            assert pulse['enabled'] is False
            assert 'running' in pulse


def test_reentered_lifespan_binds_a_new_watcher_after_stopping(app, monkeypatch):
    from oneirodex.utils import library_watch

    monkeypatch.setenv('ONEIRODEX_LIBRARY_WATCH', '1')
    monkeypatch.setattr(library_watch, '_controller', None)
    monkeypatch.setattr(library_watch, '_watch_started', False)
    monkeypatch.setattr(LibraryWatchController, '_ensure_observer', lambda self: None)
    first = start_library_watch(app)
    old_thread = first._refresh_thread
    assert start_library_watch(app) is first
    first.stop()
    assert not old_thread.is_alive()
    second = start_library_watch(app)
    try:
        assert second is not first
        assert second._refresh_thread.is_alive()
    finally:
        second.stop()
