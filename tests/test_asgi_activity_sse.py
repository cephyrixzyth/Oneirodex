"""ASGI SSE — activity + events streams stay off WsgiToAsgi."""

from __future__ import annotations

import asyncio
import inspect
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from unittest.mock import AsyncMock

from asgi import LazyASGIApp
from oneirodex.utils.event_bus import AppEvent, EventBus, encode_sse, event_bus


def test_encode_sse_bytes():
    raw = encode_sse(AppEvent(type='hello', payload={'ok': True}))
    assert isinstance(raw, bytes)
    assert raw.startswith(b'event: hello\n')
    assert b'"ok": true' in raw


def test_asgi_intercepts_both_sse_paths():
    src = inspect.getsource(LazyASGIApp.__call__)
    assert '/api/activity/stream' in src or '_SSE_ROUTES' in inspect.getsource(LazyASGIApp)
    routes = LazyASGIApp._SSE_ROUTES
    assert '/api/activity/stream' in routes
    assert '/api/events/stream' in routes
    assert src.index('_SSE_ROUTES') < src.index('await self._app(')


def test_sse_routes_config():
    activity = LazyASGIApp._SSE_ROUTES['/api/activity/stream']
    events = LazyASGIApp._SSE_ROUTES['/api/events/stream']
    assert activity['restrict_child'] is True
    assert events['restrict_child'] is False
    assert 'activity' in activity['event_types']
    assert events['event_types'] is None


def _run(coro):
    return asyncio.run(coro)


def test_sse_unauthorized_without_session():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._get_user_from_session = AsyncMock(return_value=None)
    app._authorize_sse_user = AsyncMock(return_value=401)

    messages = []

    async def send(msg):
        messages.append(msg)

    async def receive():
        return {'type': 'http.disconnect'}

    async def run():
        await app._handle_sse(
            {'type': 'http', 'method': 'GET', 'path': '/api/activity/stream'},
            receive,
            send,
            channel='activity',
            event_types=frozenset({'activity'}),
            restrict_child=True,
        )

    _run(run())
    start = next(m for m in messages if m.get('type') == 'http.response.start')
    assert start['status'] == 401


def test_sse_forbidden_for_child():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._get_user_from_session = AsyncMock(return_value=7)
    app._authorize_sse_user = AsyncMock(return_value=403)

    messages = []

    async def send(msg):
        messages.append(msg)

    async def receive():
        return {'type': 'http.disconnect'}

    async def run():
        await app._handle_sse(
            {'type': 'http', 'method': 'GET', 'path': '/api/activity/stream'},
            receive,
            send,
            channel='activity',
            event_types=frozenset({'activity'}),
            restrict_child=True,
        )

    _run(run())
    start = next(m for m in messages if m.get('type') == 'http.response.start')
    assert start['status'] == 403


def test_sse_hello_and_unsubscribe_on_disconnect():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._get_user_from_session = AsyncMock(return_value=1)
    app._authorize_sse_user = AsyncMock(return_value=None)

    before = len(event_bus._subscribers) + len(event_bus._async_subscribers)
    messages = []

    async def send(msg):
        messages.append(msg)

    async def receive():
        # Let hello flush, then disconnect so the loop exits.
        await asyncio.sleep(0.05)
        return {'type': 'http.disconnect'}

    async def run():
        await app._handle_sse(
            {'type': 'http', 'method': 'GET', 'path': '/api/activity/stream'},
            receive,
            send,
            channel='activity',
            event_types=frozenset({'activity', 'presence', 'hello', 'test'}),
            restrict_child=True,
        )

    _run(run())
    bodies = [
        m.get('body', b'')
        for m in messages
        if m.get('type') == 'http.response.body' and m.get('body')
    ]
    assert any(b.startswith(b'event: hello') and b'activity' in b for b in bodies)
    assert len(event_bus._subscribers) + len(event_bus._async_subscribers) == before


def test_sse_emits_published_event():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._get_user_from_session = AsyncMock(return_value=1)
    app._authorize_sse_user = AsyncMock(return_value=None)

    messages = []
    got_scan = asyncio.Event()

    async def send(msg):
        messages.append(msg)
        body = msg.get('body') or b''
        if b'event: scan' in body:
            got_scan.set()

    async def receive():
        await got_scan.wait()
        await asyncio.sleep(0.02)
        return {'type': 'http.disconnect'}

    async def run():
        task = asyncio.create_task(
            app._handle_sse(
                {'type': 'http', 'method': 'GET', 'path': '/api/events/stream'},
                receive,
                send,
                channel='events',
                event_types=None,
                restrict_child=False,
            )
        )
        await asyncio.sleep(0.08)
        event_bus.publish('scan', job_id=99, status='running')
        await asyncio.wait_for(task, timeout=3.0)

    _run(run())
    bodies = b''.join(
        m.get('body', b'')
        for m in messages
        if m.get('type') == 'http.response.body'
    )
    assert b'event: hello' in bodies
    assert b'event: scan' in bodies


def test_async_subscriber_receives_publish_from_another_thread():
    bus = EventBus()

    async def run():
        subscriber = bus.subscribe_async(asyncio.get_running_loop())
        try:
            thread = Thread(target=lambda: bus.publish('scan', job_id=12, status='running'))
            thread.start()
            thread.join(timeout=1)
            assert not thread.is_alive()
            event = await asyncio.wait_for(subscriber.get(), timeout=1)
            assert event.type == 'scan'
            assert event.payload['job_id'] == 12
        finally:
            bus.unsubscribe(subscriber)

    _run(run())


def test_twenty_open_sse_handlers_do_not_starve_the_default_executor():
    app = LazyASGIApp()
    app._ensure_flask = AsyncMock()
    app._get_user_from_session = AsyncMock(return_value=1)
    app._authorize_sse_user = AsyncMock(return_value=None)

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=8))
        disconnects = [asyncio.Event() for _ in range(20)]
        messages = []

        async def send(message):
            messages.append(message)

        async def serve(event):
            async def receive():
                await event.wait()
                return {'type': 'http.disconnect'}

            await app._handle_sse(
                {'type': 'http', 'method': 'GET', 'path': '/api/activity/stream'},
                receive,
                send,
                channel='activity',
                event_types=frozenset(),
                restrict_child=True,
            )

        tasks = [asyncio.create_task(serve(event)) for event in disconnects]
        try:
            await asyncio.sleep(0.05)
            started = time.perf_counter()
            await asyncio.wait_for(loop.run_in_executor(None, lambda: 'available'), timeout=0.2)
            assert time.perf_counter() - started < 0.2
        finally:
            for event in disconnects:
                event.set()
            await asyncio.gather(*tasks)

    _run(run())
