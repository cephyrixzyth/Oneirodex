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


def test_setup_library_keeps_distinct_path_validation_messages(monkeypatch):
    import oneirodex.runtime_native.setup_transition as setup_transition
    import oneirodex.utils.setup as setup_state
    import oneirodex.utils.security as security

    app = SimpleNamespace(config={}, logger=SimpleNamespace(warning=lambda *a: None, error=lambda *a: None))
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 6)
    monkeypatch.setattr(security, 'get_allowed_base_directories', lambda _app: ['/allowed'])
    monkeypatch.setattr(setup_transition.os.path, 'isdir', lambda _folder: False)

    monkeypatch.setattr(security, 'is_safe_path', lambda *_a, **_k: (False, 'outside'))
    _, outside_failure, _ = setup_transition.SetupTransitionData().transition(
        {
            'step': 6, 'skip': False, 'library_name': 'First library', 'platform': 'NES',
            'folder_path': '/outside/game-data', 'scan_depth': 1, 'scan_mode': 'folders',
        },
        app,
    )
    assert outside_failure == (
        'unprocessable', 'Check the first library details.', 422,
        {'folder_path': ['That folder is outside the configured library locations.']},
    )

    monkeypatch.setattr(security, 'is_safe_path', lambda *_a, **_k: (True, None))
    _, missing_failure, _ = setup_transition.SetupTransitionData().transition(
        {
            'step': 6, 'skip': False, 'library_name': 'First library', 'platform': 'NES',
            'folder_path': '/allowed/missing', 'scan_depth': 1, 'scan_mode': 'folders',
        },
        app,
    )
    assert missing_failure == (
        'unprocessable', 'Check the first library details.', 422,
        {'folder_path': ['That folder is not available as a directory on the server.']},
    )
