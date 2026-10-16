"""Unit tests for interval/cron schedules and auto scan-mode detection."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from oneirodex.utils.cron_schedule import next_cron_fire, validate_cron_expression
from oneirodex.utils.scan_queue import (
    apply_schedule_to_job,
    job_next_run_from_row,
    normalize_schedule_fields,
)
from oneirodex.utils.services.scan_orchestration import (
    SCHEDULE_HOURS,
    compute_next_run,
    resolve_scan_mode_for_path,
)


def test_validate_cron_expression_accepts_five_fields():
    assert validate_cron_expression('0 */6 * * *') is None
    assert validate_cron_expression('bad') is not None
    assert validate_cron_expression('* * *') is not None


def test_next_cron_fire_advances_to_next_slot():
    base = datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc)
    nxt = next_cron_fire('0 */6 * * *', from_time=base)
    assert nxt == datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)


def test_compute_next_run_preset_interval_cron():
    base = datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc)
    assert compute_next_run('8_hours', from_time=base) == base + timedelta(hours=8)
    assert compute_next_run(
        schedule_kind='interval', interval_minutes=45, from_time=base,
    ) == base + timedelta(minutes=45)
    cron_next = compute_next_run(
        schedule_kind='cron', cron_expr='0 3 * * *', from_time=base,
    )
    assert cron_next.hour == 3
    assert '8_hours' in SCHEDULE_HOURS


def test_normalize_schedule_fields_presets_interval_cron():
    preset = normalize_schedule_fields('24_hours')
    assert preset['schedule'] == '24_hours'
    assert preset['schedule_kind'] == 'preset'
    assert preset['next_run'] is not None

    interval = normalize_schedule_fields(
        'interval', interval_value=2, interval_unit='hours',
    )
    assert interval['schedule_kind'] == 'interval'
    assert interval['schedule_interval_minutes'] == 120
    assert interval['schedule'] is None

    cron = normalize_schedule_fields('cron', cron_expr='15 * * * *')
    assert cron['schedule_kind'] == 'cron'
    assert cron['schedule_cron'] == '15 * * * *'

    once = normalize_schedule_fields('')
    assert once['schedule_kind'] == 'once'


def test_apply_schedule_and_job_next_run_from_row():
    fields = normalize_schedule_fields(
        'interval', interval_value=30, interval_unit='minutes',
    )
    job = SimpleNamespace(
        schedule=None,
        schedule_kind=None,
        schedule_interval_minutes=None,
        schedule_cron=None,
        next_run=None,
        status='Completed',
        is_enabled=False,
    )
    apply_schedule_to_job(job, fields)
    assert job.schedule_kind == 'interval'
    assert job.schedule_interval_minutes == 30
    nxt = job_next_run_from_row(job)
    assert nxt is not None


def test_resolve_scan_mode_for_path_auto_heuristic():
    with tempfile.TemporaryDirectory() as folder:
        for name in ('a.zip', 'b.zip', 'c.zip', 'd.chd'):
            open(os.path.join(folder, name), 'w', encoding='utf-8').close()
        assert resolve_scan_mode_for_path(folder, 'auto') == 'files'
        assert resolve_scan_mode_for_path(folder, 'folders') == 'folders'

    with tempfile.TemporaryDirectory() as folder:
        os.mkdir(os.path.join(folder, 'Game A'))
        os.mkdir(os.path.join(folder, 'Game B'))
        assert resolve_scan_mode_for_path(folder, 'auto') == 'folders'


def test_normalize_schedule_fields_rejects_bad_cron_and_interval():
    bad_cron = normalize_schedule_fields('cron', cron_expr='not-a-cron')
    assert bad_cron.get('error')
    assert bad_cron['schedule_kind'] == 'once'

    empty_cron = normalize_schedule_fields('cron', cron_expr='')
    assert empty_cron.get('error')

    # Parse-ok but no fire in the window (31 Feb) must fail closed.
    impossible = normalize_schedule_fields('cron', cron_expr='0 0 31 2 *')
    assert impossible.get('error')

    bad_interval = normalize_schedule_fields(
        'interval', interval_value=0, interval_unit='minutes',
    )
    assert bad_interval.get('error')
    assert bad_interval['schedule_kind'] == 'once'

    over_limit = normalize_schedule_fields(
        'interval', interval_value=10081, interval_unit='minutes',
    )
    assert over_limit['error'] == 'Number must be between 1 and 10080.'
    assert over_limit['schedule_kind'] == 'once'

    boundary = normalize_schedule_fields(
        'interval', interval_value=10080, interval_unit='minutes',
    )
    assert boundary['error'] is None
    assert boundary['schedule_interval_minutes'] == 10080


def test_validate_cron_expression_rejects_impossible_dom():
    assert validate_cron_expression('0 0 31 2 *') is not None


def test_resolve_scan_mode_ignores_non_rom_extensions():
    with tempfile.TemporaryDirectory() as folder:
        os.mkdir(os.path.join(folder, 'Game A'))
        for name in ('readme.txt', 'cover.jpg', 'notes.nfo'):
            open(os.path.join(folder, name), 'w', encoding='utf-8').close()
        assert resolve_scan_mode_for_path(folder, 'auto') == 'folders'


def test_apply_schedule_to_job_updates_coalesced_fields():
    """Busy coalesce must be able to overwrite schedule on an existing Queued row."""
    job = SimpleNamespace(
        schedule=None,
        schedule_kind='once',
        schedule_interval_minutes=None,
        schedule_cron=None,
        next_run=None,
        status='Queued',
        is_enabled=True,
    )
    fields = normalize_schedule_fields('cron', cron_expr='0 */6 * * *')
    assert not fields.get('error')
    apply_schedule_to_job(job, fields)
    assert job.schedule_kind == 'cron'
    assert job.schedule_cron == '0 */6 * * *'


def test_unknown_schedule_choice_fails_closed():
    """A select value this function does not know must not arm a silent once job.

    Falling through to `once` with `error: None` made `handle_auto_scan` flash
    success for a schedule that would never repeat.
    """
    fields = normalize_schedule_fields('weekly')
    assert fields['error']
    assert 'weekly' in fields['error']
    assert fields['next_run'] is None


def test_cron_day_fields_follow_posix_union():
    """Crontab ORs day-of-month and day-of-week when both are restricted.

    `0 3 1 * 1` is "the 1st, and every Monday". ANDing the two turned roughly
    five fires a month into roughly one a year.
    """
    from datetime import datetime, timezone

    from oneirodex.utils.cron_schedule import next_cron_fire

    # 2026-09-16 is a Wednesday; the next Monday is the 21st, well before the
    # next 1st of a month (October).
    base = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    assert next_cron_fire('0 3 1 * 1', base) == datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)

    # Only one field restricted -> that field alone decides (no union).
    assert next_cron_fire('0 3 1 * *', base) == datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)


def test_impossible_cron_fails_without_walking_two_years():
    """Feb 30 parses but never fires; rejecting it must not cost a minute-by-minute walk."""
    import time

    from oneirodex.utils.cron_schedule import validate_cron_expression

    started = time.monotonic()
    error = validate_cron_expression('0 0 30 2 *')
    elapsed = time.monotonic() - started
    assert error
    # The old minute-stepping search took ~1.15M iterations (seconds) to reach
    # the same answer; day-stepping is ~800.
    assert elapsed < 1.0, f'impossible cron took {elapsed:.2f}s to reject'

