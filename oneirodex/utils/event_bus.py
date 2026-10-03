"""In-process event bus for scan/download realtime updates (SSE)."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {'type': self.type, 'payload': self.payload, 'ts': self.ts}


class EventBus:
    """Thread-safe fan-out of JSON events to sync SSE subscribers."""

    def __init__(self, history_size: int = 50):
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []
        self._async_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._history: list[AppEvent] = []
        self._history_size = history_size

    def publish(self, event_type: str, **payload: Any) -> AppEvent:
        event = AppEvent(type=event_type, payload=payload)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size:]
            subscribers = list(self._subscribers)
            async_subscribers = list(self._async_subscribers)

        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        for loop, async_queue in async_subscribers:
            try:
                loop.call_soon_threadsafe(self._offer_async, async_queue, event)
            except RuntimeError:
                # The subscriber's event loop has already closed.
                self.unsubscribe(async_queue)
        return event

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
            history = list(self._history)
        for event in history[-10:]:
            try:
                q.put_nowait(event)
            except queue.Full:
                break
        return q

    @staticmethod
    def _offer_async(subscriber: asyncio.Queue, event: AppEvent) -> None:
        try:
            subscriber.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def subscribe_async(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Subscribe an async handler without polling in a worker thread."""
        subscriber: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._async_subscribers.append((loop, subscriber))
            history = list(self._history)
        for event in history[-10:]:
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                break
        return subscriber

    def unsubscribe(self, q: queue.Queue | asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
            self._async_subscribers = [
                (loop, subscriber) for loop, subscriber in self._async_subscribers
                if subscriber is not q
            ]


event_bus = EventBus()


def publish_scan_event(job_id: int | str, status: str, **extra: Any) -> None:
    event_bus.publish('scan', job_id=job_id, status=status, **extra)


def publish_download_event(request_id: int | str, status: str, **extra: Any) -> None:
    event_bus.publish('download', request_id=request_id, status=status, **extra)


def encode_sse(event: AppEvent) -> bytes:
    data = json.dumps(event.to_dict(), default=str)
    return f'event: {event.type}\ndata: {data}\n\n'.encode('utf-8')
