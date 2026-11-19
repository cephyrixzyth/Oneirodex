"""Operator scripts must run the way the runbooks document them.

The suite imports ``config`` through conftest, which puts the repo root on
``sys.path`` and registers psycopg2 for plain ``postgresql`` URLs. Inside the
image an operator runs ``python scripts/<name>.py`` with neither, so these
checks start a fresh interpreter with a minimal environment.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

OPERATOR_SCRIPTS = [
    ['scripts/migrate_reusable_secrets.py'],
    ['scripts/migrate_store_credentials.py'],
    ['scripts/migrate_emulator_save_keys.py', '--migrate', '--root', '.'],
    ['scripts/audit_emulator_saves.py', '--root', '.'],
    ['scripts/reset_admin_password.py', '--list'],
]


def _clean_env(**extra: str) -> dict[str, str]:
    keep = {'PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'HOME', 'USERPROFILE'}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.update(extra)
    return env


@pytest.mark.parametrize('argv', OPERATOR_SCRIPTS, ids=lambda argv: Path(argv[0]).stem)
def test_script_imports_the_app_without_pythonpath(argv, tmp_path):
    # External mode with no DATABASE_URL: each script must get as far as its own
    # configuration refusal, which proves the app package imported.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / argv[0]), *argv[1:]],
        cwd=tmp_path,
        env=_clean_env(ONEIRODEX_EMBEDDED_DB='false'),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert 'ModuleNotFoundError' not in output, output
    assert 'No module named' not in output, output
    assert result.returncode != 0


def test_plain_database_url_uses_installed_psycopg2_driver(tmp_path):
    code = (
        'import sys; sys.path.insert(0, sys.argv[1]);'
        'from sqlalchemy import create_engine;'
        'from scripts.migrate_store_credentials import resolve_database_url;'
        'engine = create_engine(resolve_database_url());'
        'print(engine.dialect.driver)'
    )
    result = subprocess.run(
        [sys.executable, '-c', code, str(REPO_ROOT)],
        cwd=tmp_path,
        env=_clean_env(
            ONEIRODEX_EMBEDDED_DB='false',
            DATABASE_URL='postgresql://user:password@db.invalid/example',
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'psycopg2'
