"""Framework-neutral Ops response projections shared by Flask and FastAPI."""
from __future__ import annotations


def log_summary(info: dict) -> dict:
    latest = info.get('latest')
    return {
        'count': info.get('count'),
        'latest': None if latest is None else {
            'id': latest.id,
            'timestamp': latest.timestamp.isoformat() if latest.timestamp else None,
            'level': latest.event_level,
            'type': latest.event_type,
            'text': latest.event_text,
        },
    }


def theme_asset_panel(root_path) -> dict:
    """Return the plain JSON theme-freshness panel without Flask globals."""
    from oneirodex.utils.theme_freshness import theme_freshness

    data = theme_freshness(root_path)
    if data.get('reason'):
        return {'Status': data['reason'], 'Tracked files': data['checked']}
    panel = {
        'Status': 'Up to date' if not data['stale'] else 'Behind source — run Reset Themes',
        'Tracked files': data['checked'],
        'Outdated': data['outdated_count'],
        'Missing': data['missing_count'],
    }
    if data['missing']:
        panel['Never deployed'] = ', '.join(data['missing'][:5])
    if data['outdated']:
        panel['Behind (sample)'] = ', '.join(data['outdated'][:5])
    return panel
