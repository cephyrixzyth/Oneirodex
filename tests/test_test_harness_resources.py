"""Per-test app teardown must release database clients despite retained tracebacks."""
from time import monotonic, sleep

import pytest
from sqlalchemy import bindparam, text

from oneirodex import db


@pytest.mark.parametrize('failure_after_yield', [False, True])
def test_app_fixture_releases_idle_clients_even_when_app_objects_remain_referenced(
    app, no_savepoint_db, failure_after_yield,
):
    import conftest

    retained, pids = [], []
    with app.app_context():
        monitor_engine = db.engine
    try:
        for _ in range(3):
            generator = conftest.app.__wrapped__()
            instance = next(generator)
            with instance.app_context():
                engine = db.engine
                with engine.connect() as connection:
                    pids.append(connection.execute(text('SELECT pg_backend_pid()')).scalar_one())
            retained.append((instance, engine))
            if failure_after_yield:
                with pytest.raises(RuntimeError, match='synthetic test failure'):
                    generator.throw(RuntimeError('synthetic test failure'))
            else:
                with pytest.raises(StopIteration):
                    next(generator)
        query = text('SELECT count(*) FROM pg_stat_activity WHERE pid IN :pids').bindparams(
            bindparam('pids', expanding=True),
        )
        remaining = len(pids)
        deadline = monotonic() + 1
        while remaining and monotonic() < deadline:
            with monitor_engine.connect() as connection:
                remaining = connection.execute(query, {'pids': pids}).scalar_one()
            if remaining:
                sleep(0.02)
        assert remaining == 0, 'Finished app fixtures must not retain idle PostgreSQL clients'
    finally:
        # The RED itself must not leak clients into the following tests.
        for _instance, engine in retained:
            engine.dispose()
