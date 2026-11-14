"""What is running, and is it what shipped?

Before this there was no answer from inside the product: the version was a
literal, the Alembic revision was never read back, and no build stamp reached
the process. These cover the two properties that make the answer trustworthy --
one source for the version, and every field degrading to ``None`` rather than
taking the Ops poll down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oneirodex.utils import build_identity as module
from oneirodex.utils.build_identity import build_identity, reset_build_identity_cache

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_cache():
    # The memo is per-process and deliberate; tests must not inherit each
    # other's answer.
    reset_build_identity_cache()
    yield
    reset_build_identity_cache()


def test_the_version_has_exactly_one_source():
    """`VERSION` and `app_version` used to be two literals that agreed only as
    long as somebody remembered to change both."""
    from oneirodex import app_version

    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == app_version


def test_the_identity_names_the_running_build(app):
    with app.app_context():
        identity = build_identity()

    assert identity['version']
    assert identity['generator_version']
    # The schema pair is the point: what the DB is stamped at, and what this
    # code expects.
    assert 'schema_revision' in identity
    assert 'schema_head' in identity


def test_a_pending_migration_is_reported_as_pending(app, monkeypatch):
    monkeypatch.setattr(module, '_schema_revision', lambda: 'b2c3d4e5f6a7')
    monkeypatch.setattr(module, '_schema_head', lambda: 'c3d4e5f6a7b8')
    with app.app_context():
        assert build_identity()['migration_pending'] is True

    reset_build_identity_cache()
    monkeypatch.setattr(module, '_schema_revision', lambda: 'c3d4e5f6a7b8')
    with app.app_context():
        assert build_identity()['migration_pending'] is False


def test_an_unknown_revision_is_not_reported_as_up_to_date(app, monkeypatch):
    """`None` and `False` are different answers.

    "We could not read the revision" must not render as "nothing is pending" --
    that is the one wrong answer this tile could give, because it would be
    reassuring and wrong at exactly the moment an operator is checking.
    """
    monkeypatch.setattr(module, '_schema_revision', lambda: None)
    with app.app_context():
        assert build_identity()['migration_pending'] is None


def test_the_build_stamp_is_absent_rather_than_invented(app, monkeypatch):
    """A hand-built image has no commit, and says so."""
    monkeypatch.delenv('ONEIRODEX_BUILD_SHA', raising=False)
    monkeypatch.delenv('ONEIRODEX_BUILT_AT', raising=False)
    with app.app_context():
        identity = build_identity()
    assert identity['commit'] is None
    assert identity['built_at'] is None

    reset_build_identity_cache()
    monkeypatch.setenv('ONEIRODEX_BUILD_SHA', '0befa9b4')
    monkeypatch.setenv('ONEIRODEX_BUILT_AT', '2026-09-22T18:05:00Z')
    with app.app_context():
        identity = build_identity()
    assert identity['commit'] == '0befa9b4'
    assert identity['built_at'] == '2026-09-22T18:05:00Z'


def test_a_broken_collector_never_takes_the_ops_poll_down(app, monkeypatch):
    """The contract `get_gpu_usage` set (INSP-44): degrade, never raise.

    An Ops tile that reads *n/a* is honest. One that propagates an exception
    takes the whole 15-second poll down with it, so the operator loses the
    dashboard at the moment they most wanted to look at it.
    """
    def boom():
        raise RuntimeError('database is on fire')

    monkeypatch.setattr(module, '_schema_revision', boom)
    monkeypatch.setattr(module, '_schema_head', boom)

    with app.app_context():
        identity = build_identity()  # must not raise

    assert identity['version']  # the half that cannot fail is still there
    assert identity['schema_revision'] is None
    assert identity['migration_pending'] is None


def test_the_schema_revision_helper_returns_none_when_the_db_is_unreachable(app, monkeypatch):
    class Boom:
        def connect(self):
            raise RuntimeError('no database')

    with app.app_context():
        from oneirodex import db

        monkeypatch.setattr(type(db), 'engine', property(lambda self: Boom()))
        assert module._schema_revision() is None


def test_schema_revision_uses_native_engine_without_flask(monkeypatch):
    import builtins

    from sqlalchemy import create_engine, text
    from oneirodex.runtime_native import db_session

    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'
        ))
        connection.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('native-head')"
        ))
    monkeypatch.setattr(db_session, 'current_native_engine', lambda: engine)
    real_import = builtins.__import__

    def without_flask(name, *args, **kwargs):
        if name == 'flask':
            raise ImportError('Flask is not installed in the native runtime')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', without_flask)
    try:
        assert module._schema_revision() == 'native-head'
    finally:
        engine.dispose()


def test_ops_summary_carries_the_build_block(app):
    from oneirodex import app_start_time
    from oneirodex.utils.ops_summary import build_ops_summary

    with app.app_context():
        summary = build_ops_summary(app_start_time)

    assert 'build' in summary
    assert summary['build']['version']
