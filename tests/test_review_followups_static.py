"""Regression checks for small review fixes that are easy to undo accidentally."""

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_installer_does_not_copy_example_config_and_preserves_secret_key():
    linux = (ROOT / 'install-linux.sh').read_text(encoding='utf-8')
    macos = (ROOT / 'install-macos.sh').read_text(encoding='utf-8')
    windows = (ROOT / 'install-windows.ps1').read_text(encoding='utf-8')

    assert not (ROOT / 'config.py.example').exists()
    assert 'config.py.example' not in linux + macos + windows
    for source in (linux, macos, windows):
        assert 'SECRET_KEY' in source
        assert '.env.backup.' in source or '$envPath.backup.' in source
    assert "ALTER USER oneirodexuser WITH ENCRYPTED PASSWORD '$DB_PASSWORD'" in linux
    assert "grep -qF '# Added by Oneirodex installer'" in linux


def test_targeted_log_system_event_calls_use_keyword_metadata():
    paths = (
        'oneirodex/routes_apis/download.py',
        'oneirodex/routes_apis/filters.py',
        'oneirodex/routes_downloads_ext/admin.py',
        'oneirodex/routes_admin_ext/attract_mode.py',
    )
    snake_case = re.compile(r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$')
    offenders = []
    for relative in paths:
        tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != 'log_system_event' or len(node.args) < 2:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and snake_case.fullmatch(first.value):
                offenders.append(f'{relative}:{node.lineno}')
    assert offenders == []


def test_save_path_plugin_reports_status_independently(app):
    from oneirodex.utils.plugins import _runtime_status_map

    with app.app_context():
        assert 'compat.save_paths' in _runtime_status_map()
