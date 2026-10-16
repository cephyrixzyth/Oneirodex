from __future__ import annotations

from flask import Flask

from oneirodex.utils.theme_reset import reset_default_theme_assets


def test_default_theme_reset_uses_explicit_paths_and_preserves_other_themes(tmp_path, monkeypatch):
    app_root = tmp_path / 'package'
    source = app_root / 'setup' / 'default_theme'
    source.mkdir(parents=True)
    (source / 'theme.css').write_text('shipped', encoding='utf-8')

    library_root = tmp_path / 'runtime-library'
    themes_root = library_root / 'themes'
    default_theme = themes_root / 'default'
    default_theme.mkdir(parents=True)
    (default_theme / 'old.css').write_text('stale', encoding='utf-8')
    custom_theme = themes_root / 'custom'
    custom_theme.mkdir()
    (custom_theme / 'custom.css').write_text('keep', encoding='utf-8')

    monkeypatch.setenv('ONEIRODEX_LIBRARY_DIR', str(library_root))
    events = []
    versions = []
    monkeypatch.setattr('oneirodex.utils.event_logging.log_system_event',
                        lambda *args, **kwargs: events.append((args, kwargs)) or True)
    monkeypatch.setattr('oneirodex.utils.preset_themes.install_preset_themes',
                        lambda *args, **kwargs: 2)
    monkeypatch.setattr('oneirodex.utils.asset_version.clear_asset_versions',
                        lambda: versions.append('cleared'))
    app = Flask('theme-reset-no-context')
    app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))

    ok, message = reset_default_theme_assets(
        app_root, audit_user_id=31, logger=app.logger,
    )

    assert ok is True
    assert '2 preset themes' in message
    assert (default_theme / 'theme.css').read_text(encoding='utf-8') == 'shipped'
    assert not (default_theme / 'old.css').exists()
    assert (custom_theme / 'custom.css').read_text(encoding='utf-8') == 'keep'
    assert versions == ['cleared']
    assert events[-1][1]['audit_user'] == 31


def test_default_theme_reset_reports_missing_source_without_writing(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr('oneirodex.utils.event_logging.log_system_event',
                        lambda *args, **kwargs: events.append(kwargs) or True)

    ok, message = reset_default_theme_assets(tmp_path / 'missing', audit_user_id=7)

    assert ok is False
    assert 'source not found' in message
    assert events[-1]['audit_user'] == 7
    assert not (tmp_path / 'missing' / 'static' / 'library').exists()
