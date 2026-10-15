from types import SimpleNamespace

from oneirodex.utils import scanning


def test_scan_identify_receives_native_app_and_database_scope(monkeypatch):
    library = SimpleNamespace(uuid='library-1')
    results = iter([
        SimpleNamespace(scalar_one_or_none=lambda: library),
        SimpleNamespace(scalar_one_or_none=lambda: None),
        SimpleNamespace(scalar_one_or_none=lambda: None),
    ])
    monkeypatch.setattr(scanning.db.session, 'execute', lambda _statement: next(results))
    calls = []
    monkeypatch.setattr(
        scanning, 'try_add_game',
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )
    app = object()
    database_scope = lambda _app: None

    assert scanning.process_game_with_fallback(
        'Example Game', '/library/Example Game', 'job-1', 'library-1',
        app=app, database_scope=database_scope,
    ) is True
    assert len(calls) == 1
    assert calls[0][1]['app'] is app
    assert calls[0][1]['database_scope'] is database_scope


def test_game_admission_forwards_native_scope_to_identify_service(monkeypatch):
    from oneirodex.utils import game_core

    library = SimpleNamespace(uuid='library-1')
    monkeypatch.setattr(
        scanning.db.session, 'execute',
        lambda _statement: SimpleNamespace(scalar_one_or_none=lambda: library),
    )
    calls = []
    monkeypatch.setattr(
        game_core, 'retrieve_and_save_game',
        lambda *args, **kwargs: calls.append((args, kwargs)) or object(),
    )
    app = object()
    database_scope = lambda _app: None

    assert scanning.try_add_game(
        'Example Game', '/library/Example Game', 'job-1', 'library-1',
        check_exists=False, app=app, database_scope=database_scope,
    ) is True
    assert len(calls) == 1
    assert calls[0][1]['app'] is app
    assert calls[0][1]['database_scope'] is database_scope


def test_native_post_identify_worker_uses_db_scope_without_flask_context(monkeypatch):
    from contextlib import nullcontext
    from oneirodex.utils.services import game_enrich

    game = SimpleNamespace(uuid='game-1', name='Example Game', full_disk_path='/library/Example Game')
    session = SimpleNamespace(
        execute=lambda _statement: SimpleNamespace(scalar_one_or_none=lambda: game),
        commit=lambda: None,
        rollback=lambda: None,
    )
    monkeypatch.setattr(game_enrich, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(game_enrich, 'enrich_game_all_sources', lambda *_a, **_kw: None)
    folder_size_calls = []
    monkeypatch.setattr(
        game_enrich, 'get_folder_size_in_bytes_updates',
        lambda *args, **kwargs: folder_size_calls.append((args, kwargs)) or 4096,
    )
    image_calls = []
    monkeypatch.setattr(
        game_enrich, 'smart_process_images_for_game',
        lambda *args, **kwargs: image_calls.append((args, kwargs)),
    )

    class App:
        @staticmethod
        def app_context():
            raise AssertionError('native enrichment must not push Flask app context')

    scopes = []

    def database_scope(_app):
        scopes.append(True)
        return nullcontext()

    game_enrich.queue_post_identify_enrichment(
        'game-1', app=App(), database_scope=database_scope,
        allowed_bases=['/library'], run_inline=True, compute_folder_size=True,
    )

    assert scopes == [True]
    assert folder_size_calls == [((game.full_disk_path,), {'allowed_bases': ['/library']})]
    assert len(image_calls) == 1


def test_native_image_pipeline_uses_config_and_scope_without_flask_context(monkeypatch):
    from contextlib import nullcontext
    from oneirodex.utils.services import image_pipeline
    from oneirodex.utils import cover_selection

    session = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(image_pipeline, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(
        image_pipeline, 'global_settings_row',
        lambda: SimpleNamespace(use_turbo_image_downloads=False),
    )
    monkeypatch.setattr(
        cover_selection, 'image_save_path_status',
        lambda config=None: {'writable': config.get('IMAGE_SAVE_PATH') == '/images'},
    )
    calls = []
    monkeypatch.setattr(
        image_pipeline, 'download_images_for_game',
        lambda *args, **kwargs: calls.append((args, kwargs)) or 2,
    )

    class App:
        config = {'IMAGE_SAVE_PATH': '/images'}

        @staticmethod
        def app_context():
            raise AssertionError('native image processing must not push Flask app context')

    scopes = []

    def database_scope(_app):
        scopes.append(True)
        return nullcontext()

    app = App()
    assert image_pipeline.smart_process_images_for_game(
        'game-1', app=app, database_scope=database_scope,
    ) == 2
    assert scopes == [True]
    assert calls == [(('game-1', app), {'database_scope': database_scope})]
