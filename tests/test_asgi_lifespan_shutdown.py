"""ASGI lifespan owns shutdown without replacing Uvicorn's signal handlers."""

import asyncio
import logging
import signal
from unittest.mock import AsyncMock, Mock, patch

from asgi import LazyASGIApp
from uvicorn.config import Config
from uvicorn.lifespan.on import LifespanOn


def test_lazy_asgi_app_installs_uvicorn_access_secret_filter_idempotently():
    from oneirodex.utils.logging_setup import UvicornAccessSecretFilter

    access_logger = logging.getLogger('uvicorn.access')
    saved_filters = access_logger.filters[:]
    access_logger.filters[:] = [
        item for item in access_logger.filters
        if not isinstance(item, UvicornAccessSecretFilter)
    ]
    try:
        LazyASGIApp()
        LazyASGIApp()
        assert sum(
            isinstance(item, UvicornAccessSecretFilter)
            for item in access_logger.filters
        ) == 1
    finally:
        access_logger.filters[:] = saved_filters


def test_uvicorn_lifespan_stops_workers_on_shutdown_and_keeps_sigterm_handler():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    engine = Mock()
    app._native_sqlalchemy_engine = engine
    original_sigterm = signal.getsignal(signal.SIGTERM)

    with (
        patch('oneirodex.background.start_background_workers') as start_workers,
        patch('oneirodex.background.stop_background_workers') as stop_workers,
        patch('oneirodex.utils.shutdown.request_shutdown') as request_shutdown,
    ):
        async def run_lifespan():
            lifespan = LifespanOn(Config(app=app, lifespan='on'))
            await lifespan.startup()
            start_workers.assert_called_once_with(app._flask_app)
            await lifespan.shutdown()

        asyncio.run(run_lifespan())

    stop_workers.assert_called_once_with()
    request_shutdown.assert_called_once_with()
    engine.dispose.assert_called_once_with()
    assert app._native_sqlalchemy_engine is None
    assert signal.getsignal(signal.SIGTERM) == original_sigterm
