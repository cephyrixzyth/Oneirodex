"""Native production helpers retain their fallback when Flask is absent."""

from __future__ import annotations

import builtins


def _without_flask(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == 'flask' or name.startswith('flask.'):
            raise ModuleNotFoundError("No module named 'flask'", name='flask')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)


def test_native_auth_password_check_does_not_import_legacy_flask_auth(monkeypatch):
    _without_flask(monkeypatch)

    from oneirodex.utils.password_checks import burn_password_check

    burn_password_check('unknown-user-password')


def test_native_member_helpers_fall_back_without_flask(monkeypatch, tmp_path):
    _without_flask(monkeypatch)
    monkeypatch.setenv('FONT_PATH', str(tmp_path / 'fonts'))
    monkeypatch.setenv('ONEIRODEX_LIBRARY_DIR', str(tmp_path / 'library'))

    from oneirodex.utils.client_lifecycle import _library_root
    from oneirodex.utils.theme_fonts import fonts_dir

    assert fonts_dir() == str(tmp_path / 'fonts')
    assert _library_root() == str(tmp_path / 'library')
