# oneirodex/utils/ops_issues.py
"""Derive Admin Ops/Dashboard issues (action vs warning/info).

Severity triad for banners: good / warn / bad.
Optional item severity ``info`` is softer than warn and does not paint the
banner (overall stays ``good`` when only info items exist).

``category`` (action | warning | info) is the UI-preferred bucket:
bad→action, warn→warning, info→info.

Mapping intent:
- **action** — stability/service breakers (path/DB/awake)
- **warning** — soft signals that may indicate a real problem (scan failures, recent errors)
- **info** — capacity soft signals (disk full / high %) and companions stale
"""
CATEGORY_BY_SEVERITY = {'bad': 'action', 'warn': 'warning', 'info': 'info'}
# Banner overall stays in {good, warn, bad}; info never elevates it.
OVERALL_RANK = {'good': 0, 'warn': 1, 'bad': 2}


def _worst_overall(current, candidate):
    """Worst banner color — info maps to good (non-blocking)."""
    banner = 'good' if candidate == 'info' else candidate
    return banner if OVERALL_RANK[banner] > OVERALL_RANK[current] else current


def derive_issues(
    *,
    disk_base_percent,
    disk_games_percent,
    path_problems,
    scan_failures,
    recent_error_count,
    db_reachable=None,
    awake_ok=None,
    companions_stale=None,
    livekit=None,
):
    """Build ``issues`` for ops summary.

    Action-required (``severity: bad``, ``category: action``): stability /
    service breakers — critical path missing/unreadable, DB unreachable,
    awake fail.

    Warning: soft scan failures, recent errors — may indicate a real problem.
    Info: capacity soft signals (disk % / near-full) and companions stale.
    Disk percent alone never forces ``bad`` or ``warn``.
    """
    items = []
    overall = 'good'

    def add(issue_id, severity, message, href=None):
        nonlocal overall
        overall = _worst_overall(overall, severity)
        item = {
            'id': issue_id,
            'severity': severity,
            'category': CATEGORY_BY_SEVERITY[severity],
            'message': message,
        }
        if href:
            item['href'] = href
        items.append(item)

    # Capacity — info from 85%+ (including ≥95% / ~99%); never warn/bad for % alone.
    for percent, warn_id, name in (
        (disk_base_percent, 'disk_base_high', 'Base disk'),
        (disk_games_percent, 'disk_games_high', 'Games disk'),
    ):
        if percent is None:
            continue
        if percent >= 85:
            # Keep legacy critical ids at ≥95 so existing UI filters still match,
            # but severity is info (capacity soft signal, not action-required).
            issue_id = (
                warn_id.replace('_high', '_critical')
                if percent >= 95
                else warn_id
            )
            add(issue_id, 'info', f'{name} {percent:.0f}% used')

    for problem in path_problems or []:
        key = problem.get('key', 'path')
        reason = problem.get('reason', 'unavailable')
        add(f'path_{key}', 'bad', f'{key} {reason}')

    if db_reachable is False:
        add('db_unreachable', 'bad', 'Database unreachable')

    if awake_ok is False:
        add('awake_fail', 'bad', 'Readiness check failed', href='/awake')

    # LiveKit is optional. Report known problems only when the source has
    # explicitly established that the feature is enabled; missing fields stay
    # unknown and must not be turned into an outage or configuration claim.
    if isinstance(livekit, dict) and livekit.get('enabled') is True:
        if livekit.get('configured') is False:
            add(
                'livekit_incomplete_config',
                'warn',
                'LiveKit is enabled but not fully configured',
            )
        elif livekit.get('configured') is True and livekit.get('reachable') is False:
            add(
                'livekit_unreachable',
                'warn',
                'LiveKit is configured but unreachable',
            )

    # Soft scan failures — warning only (hard path/DB/awake cover ops breakers).
    if scan_failures:
        add(
            'scan_failures',
            'warn',
            f'{scan_failures} scan job(s) failed or errored',
            href='/scan_management',
        )

    if recent_error_count:
        add(
            'recent_errors',
            'warn',
            f'{recent_error_count} error event(s) in the last 24h',
            href='/admin/ops?open=full-log',
        )

    if companions_stale:
        add(
            'companions_stale',
            'info',
            f'{companions_stale} companion device(s) stale',
            href='/admin/ops',
        )

    return {'overall': overall, 'items': items}
