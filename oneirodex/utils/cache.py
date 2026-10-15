"""Small process-local TTL cache shared by the native and legacy adapters.

The application only uses the SimpleCache contract (get, set, delete, clear).
Keeping this primitive independent from Flask lets the FastAPI runtime use the
same cache without importing Flask-Caching or tying cache invalidation to an
application context.
"""
from __future__ import annotations

import logging
import pickle
import threading
import time
from datetime import timedelta
from typing import Any


logger = logging.getLogger(__name__)


class ProcessCache:
    """Thread-safe in-memory cache with Flask-Caching SimpleCache defaults."""

    def __init__(self, *, default_timeout: int = 300, threshold: int = 500):
        self.default_timeout = default_timeout
        self.threshold = threshold
        self._entries: dict[Any, tuple[float, bytes | None]] = {}
        self._lock = threading.RLock()

    def init_app(self, _app) -> None:
        """Keep the legacy app-factory call harmless during runtime migration."""
        self.clear()

    def get(self, key: Any):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, serialized = entry
            if expires and expires <= time.time():
                self._entries.pop(key, None)
                return None
            if serialized is None:
                return None
            try:
                return pickle.loads(serialized)
            except (pickle.PickleError, EOFError, AttributeError, ImportError, IndexError):
                logger.warning('Discarding an unreadable in-process cache value for key %r', key)
                self._entries.pop(key, None)
                return None

    def set(self, key: Any, value: Any, timeout: int | timedelta | None = None) -> bool:
        if timeout is None:
            seconds = self.default_timeout
        elif isinstance(timeout, timedelta):
            seconds = int(timeout.total_seconds())
        else:
            seconds = int(timeout)
        expires = 0 if seconds == 0 else int(time.time()) + seconds
        try:
            serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except (pickle.PickleError, TypeError, AttributeError):
            logger.warning('Cache value for key %r could not be serialized', key)
            serialized = None
        with self._lock:
            self._entries[key] = (expires, serialized)
            self._prune()
        return True

    def delete(self, key: Any) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> bool:
        with self._lock:
            self._entries.clear()
            return True

    def _prune(self) -> None:
        if len(self._entries) <= self.threshold:
            return
        now = time.time()
        expired = [key for key, (expires, _value) in self._entries.items() if expires and expires < now]
        for key in expired:
            self._entries.pop(key, None)
        if len(self._entries) > self.threshold:
            ordered = sorted(self._entries.items(), key=lambda item: item[1][0])
            for key, _entry in ordered[:len(self._entries) - self.threshold]:
                self._entries.pop(key, None)


cache = ProcessCache()

__all__ = ['ProcessCache', 'cache']
