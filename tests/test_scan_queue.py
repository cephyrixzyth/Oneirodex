"""Tests for scan queue / force-parallel start policy."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from oneirodex.models import Library, ScanJob, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.scan_queue import (
    count_queued_jobs,
    create_scan_job_row,
    drain_scan_queue,
    find_queued_for_library,
    maybe_drain_scan_queue,
    parse_force_parallel,
    parse_queue_policy,
    promote_next_queued_scan,
    queue_position,
    reclaim_stale_busy_jobs,
    start_or_queue_scan,
    PROCESS_TOKEN,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- library scan queue / worker coordination.


@pytest.fixture(autouse=True)
def _clean_scan_jobs(db_session):
    try:
        db_session.execute(text('TRUNCATE TABLE scan_jobs RESTART IDENTITY CASCADE'))
        db_session.commit()
    except Exception:
        db_session.rollback()
    yield
    try:
        db_session.execute(text('TRUNCATE TABLE scan_jobs RESTART IDENTITY CASCADE'))
        db_session.commit()
    except Exception:
        db_session.rollback()


@pytest.fixture
def sample_library(db_session):
    library = Library(
        name=f'QueueLib_{uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def running_job(db_session, sample_library):
    job = ScanJob(
        folders={'/games': True},
        content_type='Games',
        status='Running',
        is_enabled=True,
        last_run=datetime.now(timezone.utc),
        library_uuid=sample_library.uuid,
        scan_folder='/games',
        total_folders=10,
        folders_success=1,
        folders_failed=0,
    )
    db_session.add(job)
    db_session.commit()
    return job


class TestParsePolicy:
    def test_force_parallel_truthy(self):
        assert parse_force_parallel(True) is True
        assert parse_force_parallel('true') is True
        assert parse_force_parallel('1') is True
        assert parse_force_parallel('force') is False
        assert parse_force_parallel(None) is False

    def test_queue_policy_force(self):
        assert parse_queue_policy('force') == 'force'
        assert parse_queue_policy(None, force_parallel=True) == 'force'
        assert parse_queue_policy('queue') == 'queue'
        assert parse_queue_policy(None) == 'queue'


class TestStartOrQueueScan:
    def test_race_recheck_yields_only_to_older_busy_job(self, app, db_session, sample_library, monkeypatch):
        from oneirodex.utils import scan_queue

        old = ScanJob(
            folders={'/old': True}, content_type='Games', status='Running',
            is_enabled=True, last_run=datetime.now(timezone.utc) - timedelta(minutes=2),
            library_uuid=sample_library.uuid, scan_folder='/old', owner_token=PROCESS_TOKEN,
        )
        db_session.add(old)
        db_session.commit()
        monkeypatch.setattr(scan_queue, 'is_scan_busy', lambda: False)
        with app.app_context(), patch('oneirodex.utils.scan_queue.Thread') as thread:
            thread.return_value.start = lambda: None
            result = start_or_queue_scan(folder_path='/new', library_uuid=sample_library.uuid, app=app)
        assert result['status'] == 'queued'
        thread.assert_not_called()

        db_session.execute(text('TRUNCATE TABLE scan_jobs CASCADE'))
        db_session.commit()
        newer = ScanJob(
            folders={'/newer': True}, content_type='Games', status='Running',
            is_enabled=True, last_run=datetime.now(timezone.utc) + timedelta(minutes=2),
            library_uuid=sample_library.uuid, scan_folder='/newer', owner_token=PROCESS_TOKEN,
        )
        db_session.add(newer)
        db_session.commit()
        with app.app_context(), patch('oneirodex.utils.scan_queue.Thread') as thread:
            thread.return_value.start = lambda: None
            result = start_or_queue_scan(folder_path='/candidate', library_uuid=sample_library.uuid, app=app)
        assert result['status'] == 'started'
        thread.assert_called_once()

    def test_queues_when_busy_by_default(self, app, db_session, sample_library, running_job):
        with app.app_context():
            result = start_or_queue_scan(
                folder_path='/games/pc',
                library_uuid=sample_library.uuid,
                queue_policy='queue',
                allow_force=True,
                app=app,
            )
            assert result['status'] == 'queued'
            assert result['job_id']
            assert result['position'] == 1
            assert 'queued' in result['message'].lower()
            job = db_session.get(ScanJob, result['job_id'])
            assert job is not None
            assert job.status == 'Queued'
            assert count_queued_jobs() == 1
            still = db_session.get(ScanJob, running_job.id)
            assert still.status == 'Running'

    def test_coalesces_duplicate_queued_same_library(
        self, app, db_session, sample_library, running_job
    ):
        with app.app_context():
            first = start_or_queue_scan(
                folder_path='/games/pc',
                library_uuid=sample_library.uuid,
                queue_policy='queue',
                allow_force=False,
                app=app,
            )
            second = start_or_queue_scan(
                folder_path='/games/pc',
                library_uuid=sample_library.uuid,
                queue_policy='queue',
                allow_force=False,
                app=app,
            )
            assert first['status'] == 'queued'
            assert second['status'] == 'queued'
            assert second['job_id'] == first['job_id']
            assert second.get('coalesced') is True
            assert count_queued_jobs() == 1
            assert find_queued_for_library(sample_library.uuid, '/games/pc') is not None

    def test_force_parallel_starts_second_running(
        self, app, db_session, sample_library, running_job
    ):
        with app.app_context():
            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                result = start_or_queue_scan(
                    folder_path='/games/pc2',
                    library_uuid=sample_library.uuid,
                    queue_policy='force',
                    allow_force=True,
                    app=app,
                )
            assert result['status'] == 'started'
            assert result['job_id']
            assert result['position'] is None
            assert 'parallel' in result['message'].lower() or 'Force' in result['message']
            job = db_session.get(ScanJob, result['job_id'])
            assert job.status == 'Running'
            running = db_session.execute(
                select(ScanJob).where(ScanJob.status == 'Running')
            ).scalars().all()
            assert len(running) >= 2

    def test_non_admin_cannot_force(self, app, db_session, sample_library, running_job):
        with app.app_context():
            result = start_or_queue_scan(
                folder_path='/games/pc3',
                library_uuid=sample_library.uuid,
                queue_policy='force',
                allow_force=False,
                app=app,
            )
            assert result['status'] == 'rejected'
            assert result['job_id'] is None
            assert 'admin' in result['message'].lower()
            assert count_queued_jobs() == 0

    def test_promote_queued_after_running_clears(
        self, app, db_session, sample_library, running_job
    ):
        with app.app_context():
            queued = create_scan_job_row(
                folder_path='/games/next',
                library_uuid=sample_library.uuid,
                status='Queued',
            )
            assert queue_position(queued.id) == 1

            job = db_session.get(ScanJob, running_job.id)
            job.status = 'Completed'
            db_session.commit()
            db_session.expire_all()

            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                promoted = promote_next_queued_scan(app)

            assert promoted is not None
            assert promoted.id == queued.id
            refreshed = db_session.get(ScanJob, queued.id)
            assert refreshed.status == 'Running'
            assert count_queued_jobs() == 0

    def test_idle_with_queued_promotes_via_drain(
        self, app, db_session, sample_library
    ):
        with app.app_context():
            queued = create_scan_job_row(
                folder_path='/games/stuck',
                library_uuid=sample_library.uuid,
                status='Queued',
            )
            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                promoted = drain_scan_queue(app)
            assert promoted is not None
            assert promoted.id == queued.id
            assert db_session.get(ScanJob, queued.id).status == 'Running'

    def test_maybe_drain_skips_while_a_job_is_running(
        self, app, db_session, sample_library, running_job
    ):
        with app.app_context():
            queued = create_scan_job_row(
                folder_path='/games/waiting',
                library_uuid=sample_library.uuid,
                status='Queued',
            )
            with patch('oneirodex.utils.scan_queue.drain_scan_queue') as drain:
                result = maybe_drain_scan_queue(app)
            drain.assert_not_called()
            assert result is None
            assert db_session.get(ScanJob, queued.id).status == 'Queued'
            assert db_session.get(ScanJob, running_job.id).status == 'Running'

    def test_maybe_drain_promotes_when_idle(
        self, app, db_session, sample_library
    ):
        with app.app_context():
            queued = create_scan_job_row(
                folder_path='/games/idle-drain',
                library_uuid=sample_library.uuid,
                status='Queued',
            )
            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                promoted = maybe_drain_scan_queue(app)
            assert promoted is not None
            assert promoted.id == queued.id
            assert db_session.get(ScanJob, queued.id).status == 'Running'

    def test_dead_owner_running_job_reclaimed_immediately(
        self, app, db_session, sample_library
    ):
        """A scan orphaned by a restart must not hold the queue for six hours.

        The row looks perfectly healthy to the time-based sweep — it reported
        progress a second ago — so only process ownership can tell that nothing
        is working on it. Before owner_token this wedged every later scan until
        STALE_RUNNING_SECONDS elapsed, which is what "scanning is broken"
        looked like from the admin UI.
        """
        with app.app_context():
            now = datetime.now(timezone.utc)
            orphan = ScanJob(
                folders={'/games': True},
                content_type='Games',
                status='Running',
                is_enabled=True,
                last_run=now,
                last_progress_update=now,
                library_uuid=sample_library.uuid,
                scan_folder='/games',
                # A pid that cannot be running: max_pid is well below this.
                owner_token=f'{uuid4().hex}:4294967000',
            )
            db_session.add(orphan)
            db_session.commit()

            assert reclaim_stale_busy_jobs() == 1
            assert db_session.get(ScanJob, orphan.id).status == 'Failed'

    def test_live_owner_running_job_is_left_alone(
        self, app, db_session, sample_library
    ):
        """The sweep must never reclaim a scan this process is still running."""
        from oneirodex.utils.scan_queue import PROCESS_TOKEN

        with app.app_context():
            now = datetime.now(timezone.utc)
            live = ScanJob(
                folders={'/games': True},
                content_type='Games',
                status='Running',
                is_enabled=True,
                last_run=now,
                last_progress_update=now,
                library_uuid=sample_library.uuid,
                scan_folder='/games',
                owner_token=PROCESS_TOKEN,
            )
            db_session.add(live)
            db_session.commit()

            assert reclaim_stale_busy_jobs() == 0
            assert db_session.get(ScanJob, live.id).status == 'Running'

    def test_untokened_running_job_still_waits_for_timeout(
        self, app, db_session, sample_library
    ):
        """Rows written before owner_token existed keep the old behaviour.

        A NULL token is not evidence of death, so upgrading must not sweep a
        genuinely running scan out from under itself on first boot.
        """
        with app.app_context():
            now = datetime.now(timezone.utc)
            legacy = ScanJob(
                folders={'/games': True},
                content_type='Games',
                status='Running',
                is_enabled=True,
                last_run=now,
                last_progress_update=now,
                library_uuid=sample_library.uuid,
                scan_folder='/games',
                owner_token=None,
            )
            db_session.add(legacy)
            db_session.commit()

            assert reclaim_stale_busy_jobs() == 0
            assert db_session.get(ScanJob, legacy.id).status == 'Running'

    def test_scan_after_dead_owner_starts_instead_of_queueing(
        self, app, db_session, sample_library
    ):
        """End to end: the first request after a restart starts, not queues."""
        with app.app_context():
            now = datetime.now(timezone.utc)
            orphan = ScanJob(
                folders={'/games': True},
                content_type='Games',
                status='Running',
                is_enabled=True,
                last_run=now,
                last_progress_update=now,
                library_uuid=sample_library.uuid,
                scan_folder='/games',
                owner_token=f'{uuid4().hex}:4294967000',
            )
            db_session.add(orphan)
            db_session.commit()

            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                result = start_or_queue_scan(
                    folder_path='/games/next',
                    library_uuid=sample_library.uuid,
                    app=app,
                )
            assert result['status'] == 'started'
            assert db_session.get(ScanJob, orphan.id).status == 'Failed'

    def test_reclaim_stale_stopping_unblocks_queue(
        self, app, db_session, sample_library
    ):
        with app.app_context():
            stale = ScanJob(
                folders={'/games': True},
                content_type='Games',
                status='Stopping',
                is_enabled=False,
                last_run=datetime.now(timezone.utc) - timedelta(hours=1),
                last_progress_update=datetime.now(timezone.utc) - timedelta(hours=1),
                library_uuid=sample_library.uuid,
                scan_folder='/games',
                error_message='Scan is stopping',
            )
            db_session.add(stale)
            db_session.commit()
            queued = create_scan_job_row(
                folder_path='/games/after',
                library_uuid=sample_library.uuid,
                status='Queued',
            )
            n = reclaim_stale_busy_jobs(stopping_after_seconds=60)
            assert n == 1
            assert db_session.get(ScanJob, stale.id).status == 'Failed'
            with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
                mock_thread.return_value.start = lambda: None
                promoted = promote_next_queued_scan(app)
            assert promoted is not None
            assert promoted.id == queued.id


class TestLibraryScanApi:
    @pytest.fixture
    def admin_user(self, db_session):
        unique = uuid4().hex[:8]
        admin = User(
            user_id=str(uuid4()),
            name=f'Admin_{unique}',
            email=f'admin_{unique}@test.com',
            role='admin',
            is_email_verified=True,
        )
        admin.set_password('testpass123')
        db_session.add(admin)
        db_session.commit()
        return admin

    @pytest.fixture
    def regular_user(self, db_session):
        unique = uuid4().hex[:8]
        user = User(
            user_id=str(uuid4()),
            name=f'User_{unique}',
            email=f'user_{unique}@test.com',
            role='user',
            is_email_verified=True,
        )
        user.set_password('testpass123')
        db_session.add(user)
        db_session.commit()
        return user

    def test_api_queues_when_busy(
        self, client, admin_user, sample_library, running_job, db_session
    ):
        sample_library.last_scan_folder = '/games/pc'
        db_session.commit()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        resp = client.post(
            '/api/admin/libraries/scan',
            json={
                'library_uuid': sample_library.uuid,
                'folder': '/games/pc',
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['status'] == 'queued'
        assert body['job_id']
        assert body['position'] >= 1

    def test_api_force_parallel_admin(
        self, client, admin_user, sample_library, running_job, db_session
    ):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        with patch('oneirodex.utils.scan_queue.Thread') as mock_thread:
            mock_thread.return_value.start = lambda: None
            resp = client.post(
                '/api/admin/libraries/scan',
                json={
                    'library_uuid': sample_library.uuid,
                    'folder': '/games/pc',
                    'force_parallel': True,
                },
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['status'] == 'started'
        assert 'risk' in body or 'parallel' in body['message'].lower()

    def test_non_admin_forbidden_on_scan_api(self, client, regular_user, sample_library):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        resp = client.post(
            '/api/admin/libraries/scan',
            json={
                'library_uuid': sample_library.uuid,
                'folder': '/games/pc',
                'force_parallel': True,
            },
        )
        assert resp.status_code in (401, 403, 302)


class TestManualScanQueuesWhenBusy:
    """Manual Scan form path: busy → start_or_queue_scan (queued), not hard reject."""

    def test_manual_while_busy_queues(self, app, db_session, sample_library, running_job):
        from unittest.mock import Mock, patch

        from oneirodex.utilities import handle_manual_scan

        mock_form = Mock()
        mock_form.validate_on_submit.return_value = True
        mock_form.library_uuid.data = sample_library.uuid
        # No scan location picked -> resolve against the OS base folder
        mock_form.library_root.data = ''
        mock_form.folder_path.data = 'pc'
        mock_form.scan_mode.data = 'folders'
        mock_form.force_updates_extras_scan.data = False
        mock_form.fetch_hltb.data = False
        mock_form.force_hltb_refetch.data = False

        with app.app_context():
            with app.test_request_context():
                mock_session = {}
                with patch('oneirodex.utils.services.scan_orchestration.session', mock_session):
                    with patch('oneirodex.utils.services.scan_orchestration.flash') as mock_flash:
                        with patch(
                            'oneirodex.utils.services.scan_orchestration.redirect',
                            return_value='ok',
                        ):
                            with patch(
                                'oneirodex.utils.services.scan_orchestration.url_for',
                                return_value='/scan',
                            ):
                                with patch(
                                    'oneirodex.utils.services.scan_orchestration.get_allowed_base_directories',
                                    return_value=['/base'],
                                ):
                                    with patch(
                                        'oneirodex.utils.services.scan_orchestration.is_safe_path',
                                        return_value=(True, None),
                                    ):
                                        with patch(
                                            'oneirodex.utils.services.scan_orchestration.os.path.exists',
                                            return_value=True,
                                        ):
                                            with patch(
                                                'oneirodex.utils.services.scan_orchestration.os.access',
                                                return_value=True,
                                            ):
                                                with patch.dict(
                                                    'oneirodex.utils.services.scan_orchestration.current_app.config',
                                                    {
                                                        'BASE_FOLDER_POSIX': '/base',
                                                        'BASE_FOLDER_WINDOWS': '/base',
                                                    },
                                                    clear=False,
                                                ):
                                                    handle_manual_scan(mock_form)

                msg, cat = mock_flash.call_args[0]
                assert 'queued' in msg.lower()
                assert cat == 'info'
                queued = db_session.execute(
                    select(ScanJob).where(
                        ScanJob.library_uuid == sample_library.uuid,
                        ScanJob.status == 'Queued',
                    )
                ).scalars().all()
                assert len(queued) == 1
                assert queued[0].scan_folder.endswith('pc') or 'pc' in queued[0].scan_folder
