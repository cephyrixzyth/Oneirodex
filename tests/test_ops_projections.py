from datetime import datetime, timezone
from types import SimpleNamespace

from oneirodex.utils import ops_projections


def test_log_summary_projects_latest_event_to_plain_json():
    timestamp = datetime(2026, 10, 14, tzinfo=timezone.utc)
    latest = SimpleNamespace(
        id=9, timestamp=timestamp, event_level='WARNING',
        event_type='scan', event_text='snapshot',
    )
    assert ops_projections.log_summary({'count': 3, 'latest': latest}) == {
        'count': 3,
        'latest': {
            'id': 9,
            'timestamp': timestamp.isoformat(),
            'level': 'WARNING',
            'type': 'scan',
            'text': 'snapshot',
        },
    }


def test_theme_asset_panel_projects_reasons_and_stale_samples(monkeypatch):
    monkeypatch.setattr(
        'oneirodex.utils.theme_freshness.theme_freshness',
        lambda root: {
            'root': root, 'reason': None, 'stale': True, 'checked': 12,
            'outdated_count': 2, 'missing_count': 1,
            'missing': ['missing.css'], 'outdated': ['theme.css', 'tokens.css'],
        },
    )
    assert ops_projections.theme_asset_panel('/srv/oneirodex') == {
        'Status': 'Behind source — run Reset Themes',
        'Tracked files': 12,
        'Outdated': 2,
        'Missing': 1,
        'Never deployed': 'missing.css',
        'Behind (sample)': 'theme.css, tokens.css',
    }
