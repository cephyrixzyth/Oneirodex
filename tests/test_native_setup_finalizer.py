"""Native setup finalization supplies boot config without Flask context."""
from types import SimpleNamespace

from flask import Flask

from oneirodex.runtime_native.setup_transition import SetupTransitionData


def test_setup_finalizer_runs_seeders_without_pushing_flask_context(monkeypatch):
    import oneirodex
    import oneirodex.init_data as init_data
    import oneirodex.utils.event_logging as event_logging

    app = Flask(__name__)
    app.config['FONT_PATH'] = ''
    app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native setup finalization pushed Flask app context')
    )
    calls = []
    fake_db = SimpleNamespace(session=SimpleNamespace(rollback=lambda: None))
    monkeypatch.setattr(oneirodex, 'db', fake_db)
    monkeypatch.setattr(event_logging, 'log_system_event', lambda *a, **k: calls.append(('event', a, k)))

    def initialize_library_folders(*, config, app):
        calls.append(('library', config, app))

    monkeypatch.setattr(init_data, 'initialize_library_folders', initialize_library_folders)
    for name in (
        'initialize_discovery_sections', 'insert_default_scanning_filters',
        'initialize_default_settings', 'initialize_allowed_file_types',
    ):
        monkeypatch.setattr(init_data, name, lambda _name=name: calls.append((_name,)))

    result = SetupTransitionData._finish_setup(
        fake_db, lambda: calls.append(('complete',)), app,
    )

    assert result == {
        'complete': True,
        'message': 'Setup is ready. You can add a library at any time from Libraries & scans.',
        'next_url': '/libraries',
    }
    assert calls[0] == ('library', app.config, app)
    assert ('complete',) in calls
    assert calls[-1][0] == 'event'
