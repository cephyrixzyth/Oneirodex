"""DB-free harness regressions: pytest --noconftest tests/test_test_database_guard.py."""
import builtins
import os
from pathlib import Path
import runpy
import sys
import types

import pytest


HARNESS = Path(__file__).resolve().parents[1] / 'conftest.py'
SAFE = 'postgresql://runner:secret-canary@localhost:5432/oneirodextest'


def load_harness(monkeypatch, url, *, forbid_app=False, actual_uri=SAFE):
    monkeypatch.setenv('DATABASE_URL', 'original-canary')
    if url is None:
        monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    else:
        monkeypatch.setenv('TEST_DATABASE_URL', url)
    monkeypatch.setitem(sys.modules, 'dotenv', types.SimpleNamespace(load_dotenv=lambda: None))
    calls = []
    def create_app():
        calls.append(True)
        return types.SimpleNamespace(config={'SQLALCHEMY_DATABASE_URI': actual_uri})
    monkeypatch.setitem(sys.modules, 'oneirodex', types.SimpleNamespace(create_app=create_app, db=None))
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if forbid_app and name == 'oneirodex':
            raise AssertionError('Unsafe URL reached app import')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    return runpy.run_path(str(HARNESS)), calls


@pytest.mark.parametrize('url', [
    None, '', 'secret-canary',
    'postgresql://test:secret-canary@localhost/production',
    'postgresql://runner:test-secret-canary@localhost/production',
    'postgresql://runner:secret-canary@test-host/production',
    'postgresql://runner:secret-canary@localhost/unrelated',
    'postgresql://runner:secret-canary@localhost/',
    'postgresql:///oneirodextest',
    'postgresql://runner:secret-canary@localhost:bad/oneirodextest',
    SAFE + '?dbname=production', SAFE + '?host=production',
    'sqlite:///oneirodextest',
    'postgresql://runner:secret-canary@localhost/production%00test',
    'postgresql://runner:secret-canary@localhost/prod%0atest',
    'postgresql://runner:secret-canary@localhost/prod%2500test',
    'postgresql://runner:secret-canary@local%00host/oneirodextest',
    'postgresql://runner:secret-canary@localhost/prod\ntest',
])
def test_invalid_url_rejected_before_app_import(monkeypatch, capsys, url):
    with pytest.raises(RuntimeError) as error:
        load_harness(monkeypatch, url, forbid_app=True)
    assert os.environ['DATABASE_URL'] == 'original-canary'
    output = str(error.value) + str(capsys.readouterr())
    assert 'secret-canary' not in output
    assert 'original-canary' not in output
    assert error.value.__cause__ is None


@pytest.mark.parametrize('url', [SAFE, SAFE.replace('postgresql:', 'postgresql+psycopg:'),
                                      SAFE.replace('oneirodextest', 'TEST_suite')])
def test_safe_url_selected_without_connecting(monkeypatch, capsys, url):
    harness, calls = load_harness(monkeypatch, url, actual_uri=url)
    assert os.environ['DATABASE_URL'] == url
    fixture = harness['app'].__wrapped__()
    assert next(fixture).config['SQLALCHEMY_DATABASE_URI'] == url
    fixture.close()
    assert calls == [True]
    assert 'secret-canary' not in str(capsys.readouterr())


def test_literal_nul_rejected_without_environment_roundtrip():
    # OS environments cannot contain NUL, but callers may supply strings directly.
    from database_test_guard import validate_test_database_url
    with pytest.raises(RuntimeError):
        validate_test_database_url(SAFE.replace('oneirodextest', 'prod\x00test'))


def test_fixture_revalidates_changed_url_before_creation(monkeypatch):
    harness, calls = load_harness(monkeypatch, SAFE)
    monkeypatch.setenv('TEST_DATABASE_URL', SAFE.replace('oneirodextest', 'production'))
    with pytest.raises(RuntimeError):
        next(harness['app'].__wrapped__())
    assert calls == []


@pytest.mark.parametrize('mismatch', ['environment', 'app'])
def test_mismatch_diagnostics_withhold_urls(monkeypatch, capsys, mismatch):
    harness, calls = load_harness(monkeypatch, SAFE, actual_uri='actual-secret-canary')
    if mismatch == 'environment':
        monkeypatch.setenv('DATABASE_URL', 'environment-secret-canary')
    with pytest.raises(pytest.fail.Exception) as error:
        next(harness['app'].__wrapped__())
    assert 'secret-canary' not in str(error.value) + str(capsys.readouterr())
    assert len(calls) == (mismatch == 'app')


@pytest.mark.parametrize('uri', [SAFE, SAFE.replace('oneirodextest', 'production')])
def test_real_app_checks_config_before_initializing_extensions(monkeypatch, caplog, uri):
    import oneirodex
    import oneirodex.utils.logging_setup as logging_setup
    monkeypatch.setenv('TEST_DATABASE_URL', SAFE)
    monkeypatch.setattr(logging_setup, 'configure_logging', lambda app: None)
    class ReachedExtensions(Exception):
        pass
    def stop(app):
        raise ReachedExtensions()
    monkeypatch.setattr(oneirodex.csrf, 'init_app', stop)
    config = type('GuardConfig', (), {'SQLALCHEMY_DATABASE_URI': uri})
    with caplog.at_level('INFO'):
        with pytest.raises(ReachedExtensions if uri == SAFE else RuntimeError):
            oneirodex.create_app(config)
    assert 'secret-canary' not in caplog.text
