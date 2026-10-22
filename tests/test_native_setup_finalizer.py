"""Native setup finalization supplies boot config without Flask context."""
from types import SimpleNamespace

import pytest
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


def test_setup_integrations_save_only_selected_nonblank_provider_credentials(monkeypatch):
    import oneirodex.runtime_native.db_session as native_db_session
    import oneirodex.runtime_native.setup_transition as setup_transition
    import oneirodex.utils.global_settings as global_settings
    import oneirodex.utils.setup as setup_state

    settings = SimpleNamespace(
        steam_web_api_key='existing-steam-key',
        steamgriddb_api_key='existing-grid-key',
        giantbomb_api_key='existing-giantbomb-key',
        mobygames_api_key='existing-moby-key',
        thegamesdb_api_key='existing-gamesdb-key',
        enable_hltb_integration=False,
        oidc_enabled=False,
    )
    calls = []
    fake_db = SimpleNamespace(session=SimpleNamespace())
    app = SimpleNamespace(logger=SimpleNamespace(error=lambda *_a: None))
    monkeypatch.setattr(native_db_session, 'native_db', fake_db)
    monkeypatch.setattr(global_settings, 'global_settings_row_or_create', lambda: settings)
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 5)
    monkeypatch.setattr(setup_state, 'set_setup_step', lambda step: calls.append(('step', step)))
    monkeypatch.setattr(
        setup_transition, '_commit_step',
        lambda _db, _set, step, _app, _label: calls.append(('commit', step)) or True,
    )

    body = {
        'step': 5,
        'skip': False,
        'steam_web_api_key': 'unchecked-replacement',
        'configure_steam_web_api_key': False,
        'steamgriddb_api_key': 'selected-replacement',
        'configure_steamgriddb_api_key': True,
        'giantbomb_api_key': '',
        'configure_giantbomb_api_key': True,
        'mobygames_api_key': 'unchecked-moby',
        'configure_mobygames_api_key': False,
        'thegamesdb_api_key': 'selected-gamesdb',
        'configure_thegamesdb_api_key': True,
        'configure_oidc': False,
        'enable_hltb_integration': True,
    }

    result, failure, new_admin = setup_transition.SetupTransitionData().transition(body, app)

    assert failure is None and new_admin is None
    assert result == {'step': 6, 'next_url': '/setup/library'}
    assert settings.steam_web_api_key == 'existing-steam-key'
    assert settings.steamgriddb_api_key == 'selected-replacement'
    assert settings.giantbomb_api_key == 'existing-giantbomb-key'
    assert settings.mobygames_api_key == 'existing-moby-key'
    assert settings.thegamesdb_api_key == 'selected-gamesdb'
    assert settings.enable_hltb_integration is True
    assert settings.oidc_enabled is False
    assert calls == [('commit', 6)]


@pytest.mark.parametrize('duplicate', [False, True])
@pytest.mark.parametrize('scan_status', [None, 'started'])
def test_setup_library_completes_and_preserves_library_across_scan_outcomes(
    monkeypatch, duplicate, scan_status,
):
    import oneirodex.init_data as init_data
    import oneirodex.runtime_native.db_session as native_db_session
    import oneirodex.utils.event_logging as event_logging
    import oneirodex.utils.scan_queue as scan_queue
    import oneirodex.utils.security as security
    import oneirodex.utils.setup as setup_state
    from oneirodex.models import Library
    from oneirodex.platform import LibraryPlatform

    existing = Library(
        uuid='existing-library', name='First library', platform=LibraryPlatform.NES,
        last_scan_folder='/allowed/roms',
    ) if duplicate else None
    calls = []

    class FakeSession:
        def execute(self, _statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: existing))

        def add(self, library):
            calls.append(('add', library))
            library.uuid = 'created-library'

        def commit(self):
            calls.append(('commit',))

        def rollback(self):
            calls.append(('rollback',))

    fake_session = FakeSession()
    session_token = native_db_session._native_session.set(fake_session)
    monkeypatch.setattr(setup_state, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup_state, 'get_current_setup_step', lambda: 6)
    monkeypatch.setattr(setup_state, 'mark_setup_complete', lambda: calls.append(('complete',)))
    monkeypatch.setattr(security, 'get_allowed_base_directories', lambda _app: ['/allowed'])
    monkeypatch.setattr(security, 'is_safe_path', lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr('oneirodex.runtime_native.setup_transition.os.path.isdir', lambda _path: True)
    def queue_scan(**kwargs):
        calls.append(('scan', kwargs))
        if scan_status is None:
            raise OSError('synthetic queue failure')
        return {'status': scan_status}

    monkeypatch.setattr(scan_queue, 'start_or_queue_scan', queue_scan)
    monkeypatch.setattr(event_logging, 'log_system_event', lambda *a, **k: calls.append(('event',)))
    for name in (
        'initialize_library_folders', 'initialize_discovery_sections',
        'insert_default_scanning_filters', 'initialize_default_settings',
        'initialize_allowed_file_types',
    ):
        monkeypatch.setattr(init_data, name, lambda *a, **k: None)
    app = SimpleNamespace(
        config={},
        logger=SimpleNamespace(warning=lambda *a: None, error=lambda *a: None),
    )

    try:
        result, failure, new_admin = SetupTransitionData().transition(
            {
                'step': 6, 'skip': False, 'library_name': 'First library',
                'platform': 'NES', 'folder_path': '/allowed/roms',
                'scan_depth': 1, 'scan_mode': 'folders',
            },
            app,
        )
    finally:
        native_db_session._native_session.reset(session_token)

    assert failure is None and new_admin is None
    assert result == {
        'complete': True,
        'message': (
            'Your first library is ready and its initial scan has started or queued.'
            if scan_status else
            'Your first library is ready. Start its first scan from Libraries & scans.'
        ),
        'next_url': '/libraries',
    }
    scan_call = next(call[1] for call in calls if call[0] == 'scan')
    assert scan_call['library_uuid'] == ('existing-library' if duplicate else 'created-library')
    assert [call[0] for call in calls].count('add') == (0 if duplicate else 1)
    assert [call[0] for call in calls].count('commit') == (0 if duplicate else 1)
    assert ('complete',) in calls
