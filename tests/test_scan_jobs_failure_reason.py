"""Scan Jobs API preserves operator failure reasons and processed counts.

React ScansPage and scanJobsDom component tests cover the visible caption,
reason and progress calculation; the server now returns the shared SPA shell.
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from oneirodex.models import Library, ScanJob, User
from oneirodex.platform import LibraryPlatform

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- scan-job failure/reclaim paths.

RECLAIM_MESSAGE = (
    'Scan owner process is no longer running; reclaimed so queued scans can start.'
)


def test_unmatched_compatibility_alias_preserves_classic_destination(admin_client):
    response = admin_client.get('/admin/unmatched')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/scan_management?active_tab=unmatched')


@pytest.fixture
def admin_user(db_session):
    unique = uuid4().hex[:8]
    admin = User(
        user_id=str(uuid4()),
        name=f'ScanAdmin_{unique}',
        email=f'scan_admin_{unique}@test.com',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def admin_client(client, admin_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def failed_job(db_session):
    library = Library(name=f'ReasonLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()

    job = ScanJob(
        folders={'/games': True},
        content_type='Games',
        status='Failed',
        is_enabled=False,
        last_run=datetime.now(timezone.utc),
        library_uuid=library.uuid,
        scan_folder='/games',
        total_folders=9,
        folders_success=2,
        folders_failed=1,
        error_message=RECLAIM_MESSAGE,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_reclaimed_job_states_its_reason(admin_client, failed_job):
    """The reason the ownership sweep records must reach the operator."""
    response = admin_client.get('/api/scan_jobs_status?status=all')
    assert response.status_code == 200
    mine = next(row for row in response.get_json() if row['id'] == failed_job.id)
    assert mine['error_message'] == RECLAIM_MESSAGE


def test_progress_counts_failures_not_just_successes(admin_client, failed_job):
    """First paint must agree with every poll after it.

    `progressCounts()` in admin_manage_scanjobs.js computes processed as
    success + failed. The template counted successes alone, so a job with any
    failed folder showed one number on load and a different one a poll later.
    """
    response = admin_client.get('/api/scan_jobs_status?status=all')
    assert response.status_code == 200
    row = next(row for row in response.get_json() if row['id'] == failed_job.id)

    # 2 success + 1 failed of 9.
    assert row['folders_success'] + row['folders_failed'] == 3
    assert row['folders_processed'] == 3
    assert row['total_folders'] == 9


def test_sort_key_uses_the_same_processed_count(admin_client, failed_job):
    """The Progress column sorts on data-sort-progress, not on its text.

    If that attribute counted only successes it would order the table by a
    number the operator cannot see and that disagrees with the caption.
    """
    response = admin_client.get('/api/scan_jobs_status?status=all')
    assert response.status_code == 200
    row = next(row for row in response.get_json() if row['id'] == failed_job.id)

    # 3 of 9 processed == 33.3%, not 22.2%.
    assert round(row['progress_percentage'], 1) == 33.3


def test_ops_summary_carries_the_failure_reason(app, db_session, failed_job):
    """Third surface, same gap (GT-B38).

    `_scan_job_payload` carried counts, current folder, elapsed, ETA and
    stalled — everything needed to read a scan except the one field that
    explains a job that stopped. The Ops console could therefore report a
    failure and never its reason, including the ownership sweep's.
    """
    from oneirodex.utils.ops_summary import _scan_snapshot

    with app.app_context():
        snapshot = _scan_snapshot()

    jobs = snapshot['jobs']
    mine = [j for j in jobs if j.get('id') == failed_job.id]
    assert mine, 'the failed job did not appear in the scan snapshot at all'
    assert mine[0]['error_message'] == RECLAIM_MESSAGE


def test_ops_summary_reports_no_reason_as_none_not_empty_string(
    app, db_session
):
    """A healthy job must not carry a falsy-but-present reason.

    `''` and `None` render differently once a UI starts branching on the field,
    and ScanJob defaults error_message to an empty string on create.
    """
    from oneirodex.utils.ops_summary import _scan_snapshot

    library = Library(name=f'OkLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()

    job = ScanJob(
        folders={'/games': True},
        content_type='Games',
        status='Running',
        is_enabled=True,
        last_run=datetime.now(timezone.utc),
        library_uuid=library.uuid,
        scan_folder='/games',
        total_folders=5,
        folders_success=1,
        folders_failed=0,
        error_message='',
    )
    db_session.add(job)
    db_session.commit()

    with app.app_context():
        snapshot = _scan_snapshot()

    mine = [j for j in snapshot['jobs'] if j.get('id') == job.id]
    assert mine
    assert mine[0]['error_message'] is None

    # A Running job is global state: is_scan_job_running() stays true for
    # the rest of the session, and every later test whose route refuses to
    # act during a scan fails for a reason that has nothing to do with it.
    # The suite only survived this because 'r' sorts before 's'.
    db_session.delete(job)
    db_session.commit()


def test_library_tools_live_on_scan_management(admin_client):
    """Legacy direct entries share the SPA shell; React routes select the content."""
    auto = admin_client.get('/scan_management').get_data(as_text=True)
    tools = admin_client.get('/scan_management?active_tab=tools').get_data(as_text=True)
    assert 'id="admin-app-root"' in auto
    assert 'id="admin-app-root"' in tools
    routes = (Path(__file__).resolve().parents[1] / 'frontend' / 'admin-app' / 'src' / 'components' / 'AdminRoutes.tsx').read_text(encoding='utf-8')
    assert "tab === 'tools' || tab === 'libraries'" in routes


def test_libraries_tab_uses_the_react_libraries_panel(admin_client):
    response = admin_client.get('/scan_management?active_tab=libraries')
    assert response.status_code == 200
    assert 'id="admin-app-root"' in response.get_data(as_text=True)
    routes = (Path(__file__).resolve().parents[1] / 'frontend/admin-app/src/components/AdminRoutes.tsx').read_text(encoding='utf-8')
    assert "tab === 'tools' || tab === 'libraries'" in routes


def test_library_tools_page_redirects_to_the_scan_tab(admin_client):
    response = admin_client.get('/admin/library_tools')
    assert response.status_code == 302
    assert 'active_tab=tools' in response.headers['Location']


def test_unmatched_compare_offers_a_pop_out():
    src = (
        Path(__file__).resolve().parents[1]
        / 'oneirodex' / 'setup' / 'default_theme' / 'js' / 'admin_manage_scanjobs.js'
    ).read_text(encoding='utf-8')
    assert 'showDupeComparePopout' in src
    assert 'unmatched-dupe-compare__pop' in src
