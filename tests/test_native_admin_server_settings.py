from __future__ import annotations

from types import SimpleNamespace

from oneirodex.runtime_native.admin_server_settings import AdminServerSettingsData
from oneirodex.utils import global_settings
from oneirodex.utils.server_settings import FIELD_MAPPINGS


def test_native_server_settings_projects_safe_values_without_route_import(monkeypatch):
    record = SimpleNamespace(
        settings={'showHelpButton': False, 'siteUrl': 'https://user:secret@example.test'},
        last_updated=None,
        **{field: None for field in FIELD_MAPPINGS.values()},
    )
    record.site_url = 'https://user:secret@example.test'
    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: record)

    state = AdminServerSettingsData().state()

    assert state['settings']['showHelpButton'] is False
    assert state['settings']['siteUrl'] == 'https://example.test'
    assert len(state['settings']) == 28
    assert state['bounds']['turboDownloadThreads']['max'] == 20
