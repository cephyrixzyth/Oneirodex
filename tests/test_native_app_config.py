from oneirodex.runtime_native.app_config import build_runtime_config


def test_runtime_config_uses_uppercase_settings_and_persistent_paths(tmp_path, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_LIBRARY_DIR', raising=False)
    root = tmp_path / 'oneirodex'
    values = build_runtime_config(
        {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'ignored': 'x'},
        package_root=root,
    )

    assert values['TESTING'] is True
    assert values['SQLALCHEMY_DATABASE_URI'] == 'sqlite://'
    assert 'ignored' not in values
    assert values['UPLOAD_FOLDER'] == str(root / 'static' / 'library')
    assert values['IMAGE_SAVE_PATH'] == str(root / 'static' / 'library' / 'images')


def test_runtime_config_honors_relocated_library_directory(tmp_path, monkeypatch):
    library = tmp_path / 'persistent-library'
    monkeypatch.setenv('ONEIRODEX_LIBRARY_DIR', str(library))

    values = build_runtime_config({'TESTING': True})

    assert values['UPLOAD_FOLDER'] == str(library)
    assert values['IMAGE_SAVE_PATH'] == str(library / 'images')
