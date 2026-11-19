"""Lightweight 5-field cron next-fire helper (no croniter dependency).

Supports ``*``, ``N``, ``N-M``, ``*/N``, and comma lists for minute/hour/
day-of-month/month/day-of-week. Day-of-week uses 0=Sunday … 6=Saturday (also
accepts 7 as Sunday). Enough for admin scan schedules; not a full crontab.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(','):
        part = part.strip()
        if not part:
            raise ValueError(f'empty element in {field!r}')
        if part == '*':
            values.update(range(minimum, maximum + 1))
            continue
        if part.startswith('*/'):
            step = int(part[2:])
            if step < 1:
                raise ValueError(f'invalid step in {field!r}')
            values.update(range(minimum, maximum + 1, step))
            continue
        if '-' in part:
            start_s, end_s = part.split('-', 1)
            start, end = int(start_s), int(end_s)
            if not minimum <= start <= end <= maximum:
                raise ValueError(f'invalid range in {field!r}')
            values.update(range(start, end + 1))
            continue
        value = int(part)
        if not minimum <= value <= maximum:
            raise ValueError(f'value outside range in {field!r}')
        values.add(value)
    return values


def parse_cron_expression(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = (expr or '').strip().split()
    if len(parts) != 5:
        raise ValueError('cron must have 5 fields: minute hour dom month dow')
    minute, hour, dom, month, dow = parts
    minutes = _parse_field(minute, 0, 59)
    hours = _parse_field(hour, 0, 23)
    doms = _parse_field(dom, 1, 31)
    months = _parse_field(month, 1, 12)
    dows = _parse_field(dow, 0, 7)
    if 7 in dows:
        dows.add(0)
        dows.discard(7)
    return minutes, hours, doms, months, dows


def _day_fields_restricted(expr: str) -> tuple[bool, bool]:
    """Whether day-of-month / day-of-week are restricted (i.e. not ``*``).

    POSIX crontab unions the two day fields when **both** are restricted, so
    the caller has to know which of them the author actually constrained. A
    parsed set cannot answer that: ``*`` and ``1-31`` both expand to the same
    31 values.
    """
    parts = (expr or '').strip().split()
    dom_raw = parts[2] if len(parts) > 2 else '*'
    dow_raw = parts[4] if len(parts) > 4 else '*'
    return (dom_raw.strip() != '*', dow_raw.strip() != '*')


def next_cron_fire(expr: str, from_time: datetime | None = None) -> datetime:
    """Return the next UTC datetime strictly after ``from_time`` matching ``expr``.

    Day matching follows POSIX crontab: when day-of-month **and** day-of-week
    are both restricted the entry fires on days matching *either* of them, not
    both. ``0 3 1 * 1`` is "the 1st, and every Monday" — ANDing the two fields
    turns roughly five fires a month into roughly one a year.

    The search steps a whole day at a time while the date does not match, so
    an unsatisfiable-but-parseable expression (``0 0 30 2 *``) advances
    by days instead of testing every minute.
    """
    minutes, hours, doms, months, dows = parse_cron_expression(expr)
    dom_restricted, dow_restricted = _day_fields_restricted(expr)
    base = from_time or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    else:
        base = base.astimezone(timezone.utc)

    def _day_matches(moment: datetime) -> bool:
        if moment.month not in months:
            return False
        # Python weekday is Mon=0 … Sun=6; cron is Sun=0 … Sat=6.
        dom_hit = moment.day in doms
        dow_hit = ((moment.weekday() + 1) % 7) in dows
        if dom_restricted and dow_restricted:
            return dom_hit or dow_hit
        return dom_hit and dow_hit

    # Start at the next whole minute — the result is strictly after `base`.
    cursor = base.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Nine years includes the longest leap-day gap, even across a
    # non-leap century (2096 to 2104). Nonmatching dates advance by day.
    limit = cursor + timedelta(days=9 * 366)
    while cursor <= limit:
        if not _day_matches(cursor):
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cursor.hour in hours and cursor.minute in minutes:
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f'no next fire for cron {expr!r} within search window')


def validate_cron_expression(expr: str) -> str | None:
    """Return None when valid, otherwise a short error string.

    Parse-ok is not enough: expressions with no fire in the search window
    (e.g. ``0 0 31 2 *``) must also fail closed so schedules are not armed
    once and then silently abandoned.
    """
    try:
        parse_cron_expression(expr)
        next_cron_fire(expr)
    except Exception as exc:  # noqa: BLE001 — surface as validation message
        return str(exc)
    return None
