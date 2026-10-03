"""Wave 18 — ScanJob elapsed / ETA helpers + scan_jobs_status filters."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from oneirodex import db
from oneirodex.models import Library, ScanJob, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.scan_job_timing import (
    STALL_SECONDS,
    compute_scan_job_timing,
    format_duration_label,
    parse_scan_job_status_filter,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- scan-job lifecycle and timing.


def test_format_duration_label():
    assert format_duration_label(None) is None
    assert format_duration_label(14) == '14s'
    assert format_duration_label(134) == '2m 14s'
    assert format_duration_label(3661) == '1h 1m 1s'


def test_parse_scan_job_status_filter_comma_and_case():
    assert parse_scan_job_status_filter(None) == []
    assert parse_scan_job_status_filter('') == []
    assert parse_scan_job_status_filter('running,queued') == ['Running', 'Queued']
    assert parse_scan_job_status_filter('Completed,bogus,Failed') == ['Completed', 'Failed']
    assert parse_scan_job_status_filter('Running,running') == ['Running']


def test_running_job_elapsed_and_eta():
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    started = now - timedelta(seconds=100)
    job = SimpleNamespace(
        status='Running',
        last_run=started,
        last_progress_update=now - timedelta(seconds=5),
        total_folders=10,
        folders_success=4,
        folders_failed=0,
    )
    timing = compute_scan_job_timing(job, now=now)
    assert timing['started_at'] == started.isoformat()
    assert timing['created_at'] is None
    assert timing['folders_processed'] == 4
    assert timing['elapsed_seconds'] == 100
    assert timing['elapsed_label'] == '1m 40s'
    assert timing['stalled'] is False
    # 4 folders / 100s → 0.04/s; remaining 6 → 150s
    assert timing['eta_seconds'] == 150
    assert timing['eta_label'] == '2m 30s'


def test_running_zero_progress_eta_null():
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    job = SimpleNamespace(
        status='Running',
        last_run=now - timedelta(seconds=30),
        last_progress_update=None,
        total_folders=10,
        folders_success=0,
        folders_failed=0,
    )
    timing = compute_scan_job_timing(job, now=now)
    assert timing['elapsed_seconds'] == 30
    assert timing['eta_seconds'] is None
    assert timing['stalled'] is False


def test_running_stalled_eta_null():
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    job = SimpleNamespace(
        status='Running',
        last_run=now - timedelta(seconds=600),
        last_progress_update=now - timedelta(seconds=STALL_SECONDS + 10),
        total_folders=10,
        folders_success=3,
        folders_failed=0,
    )
    timing = compute_scan_job_timing(job, now=now)
    assert timing['stalled'] is True
    assert timing['elapsed_seconds'] == 600
    assert timing['eta_seconds'] is None


def test_queued_eta_null_elapsed_wait():
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    job = SimpleNamespace(
        status='Queued',
        last_run=now - timedelta(seconds=45),
        last_progress_update=None,
        total_folders=0,
        folders_success=0,
        folders_failed=0,
    )
    timing = compute_scan_job_timing(job, now=now)
    assert timing['elapsed_seconds'] == 45
    assert timing['eta_seconds'] is None
    assert timing['stalled'] is False


def test_completed_elapsed_from_progress_end():
    started = datetime(2026, 7, 30, 11, 0, 0, tzinfo=timezone.utc)
    finished = started + timedelta(seconds=200)
    job = SimpleNamespace(
        status='Completed',
        last_run=started,
        last_progress_update=finished,
        total_folders=5,
        folders_success=5,
        folders_failed=0,
    )
    now = finished + timedelta(hours=2)
    timing = compute_scan_job_timing(job, now=now)
    assert timing['elapsed_seconds'] == 200
    assert timing['eta_seconds'] is None
    assert timing['folders_processed'] == 5


@pytest.fixture
def admin_user(db_session):
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=str(uuid4()),
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def sample_library(db_session):
    unique_id = str(uuid4())[:8]
    library = Library(
        name=f'Wave18Lib_{unique_id}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def _admin_session(client, admin_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client


def _make_job(db_session, library, **kwargs):
    defaults = dict(
        library_uuid=library.uuid,
        folders={'/games': True},
        content_type='Games',
        schedule='24_hours',
        is_enabled=True,
        last_run=datetime.now(timezone.utc),
        total_folders=0,
        folders_success=0,
        folders_failed=0,
        scan_folder='/games',
    )
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.commit()
    return job


class TestScanJobsStatusTimingAndFilters:
    def test_completed_job_has_elapsed(
        self, client, db_session, sample_library, _admin_session
    ):
        started = datetime.now(timezone.utc) - timedelta(hours=1)
        job = _make_job(
            db_session,
            sample_library,
            status='Completed',
            last_run=started,
            last_progress_update=started + timedelta(minutes=12),
            total_folders=10,
            folders_success=8,
            folders_failed=2,
            scan_folder='/games/done',
        )

        response = client.get('/api/scan_jobs_status')
        assert response.status_code == 200
        row = next(r for r in response.get_json() if r['id'] == job.id)
        assert row['status'] == 'Completed'
        assert row['elapsed_seconds'] == 12 * 60
        assert row['eta_seconds'] is None
        assert row['started_at'] is not None
        assert row['created_at'] is None
        assert row['folders_processed'] == 10
        assert row['elapsed_label'] == '12m 0s'

    def test_running_job_timing_fields(
        self, client, db_session, sample_library, _admin_session
    ):
        now = datetime.now(timezone.utc)
        job = _make_job(
            db_session,
            sample_library,
            status='Running',
            last_run=now - timedelta(seconds=80),
            last_progress_update=now - timedelta(seconds=2),
            total_folders=8,
            folders_success=2,
            folders_failed=0,
            scan_folder='/games/pc',
        )

        response = client.get('/api/scan_jobs_status')
        assert response.status_code == 200
        row = next(r for r in response.get_json() if r['id'] == job.id)
        assert row['elapsed_seconds'] is not None and row['elapsed_seconds'] > 0
        assert row['folders_processed'] == 2
        assert row['eta_seconds'] is not None and row['eta_seconds'] > 0
        assert row['stalled'] is False

    def test_queued_eta_null(self, client, db_session, sample_library, _admin_session):
        # The admin status endpoint is also a safety drain and promotes queued
        # work when no scan is active. Keep the row queued while testing its
        # serialized timing fields.
        _make_job(
            db_session,
            sample_library,
            status='Running',
            scan_folder='/games/active',
            total_folders=1,
        )
        job = _make_job(
            db_session,
            sample_library,
            status='Queued',
            last_run=datetime.now(timezone.utc) - timedelta(seconds=20),
            scan_folder='/games/queued',
        )

        response = client.get('/api/scan_jobs_status?status=Queued')
        assert response.status_code == 200
        data = response.get_json()
        assert all(r['status'] == 'Queued' for r in data)
        row = next(r for r in data if r['id'] == job.id)
        assert row['eta_seconds'] is None
        assert row['elapsed_seconds'] is not None and row['elapsed_seconds'] >= 0

    def test_status_filter_comma_list(
        self, client, db_session, sample_library, _admin_session
    ):
        running = _make_job(
            db_session,
            sample_library,
            status='Running',
            scan_folder='/a',
            total_folders=1,
        )
        completed = _make_job(
            db_session,
            sample_library,
            status='Completed',
            last_run=datetime.now(timezone.utc) - timedelta(minutes=5),
            last_progress_update=datetime.now(timezone.utc) - timedelta(minutes=4),
            scan_folder='/b',
            total_folders=1,
            folders_success=1,
        )

        response = client.get('/api/scan_jobs_status?status=Running,Completed')
        assert response.status_code == 200
        data = response.get_json()
        statuses = {r['status'] for r in data}
        assert statuses <= {'Running', 'Completed'}
        ids = {r['id'] for r in data}
        assert running.id in ids
        assert completed.id in ids

    def test_library_uuid_and_q_filter(
        self, client, db_session, sample_library, _admin_session
    ):
        marker = f'unique-wave18-{uuid4().hex[:8]}'
        job = _make_job(
            db_session,
            sample_library,
            status='Failed',
            total_folders=1,
            folders_failed=1,
            scan_folder=f'/{marker}/roms',
        )

        by_lib = client.get(f'/api/scan_jobs_status?library_uuid={sample_library.uuid}')
        assert by_lib.status_code == 200
        assert any(r['id'] == job.id for r in by_lib.get_json())

        by_q = client.get(f'/api/scan_jobs_status?q={marker}')
        assert by_q.status_code == 200
        assert job.id in {r['id'] for r in by_q.get_json()}

        by_name = client.get(f'/api/scan_jobs_status?name={sample_library.name}')
        assert by_name.status_code == 200
        assert any(r['id'] == job.id for r in by_name.get_json())
