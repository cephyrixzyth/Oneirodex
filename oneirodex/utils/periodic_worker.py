"""Own a single periodic thread across server lifespan restarts."""
from __future__ import annotations

from threading import Event, Lock, Thread

from oneirodex.utils.shutdown import bind_shutdown_owner


class PeriodicWorker:
    def __init__(self, name):
        self.name = name
        self.thread = None
        self._lock = Lock()
        self._stop = Event()

    def start(self, run_once, *, interval, delay=0):
        with self._lock:
            if self.thread is not None and self.thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError(f'{self.name} is still stopping')
                return self
            self._stop.clear()

            def run():
                if self._stop.wait(delay):
                    return
                while not self._stop.is_set():
                    run_once()
                    if self._stop.wait(interval):
                        break

            self.thread = Thread(target=bind_shutdown_owner(run), name=self.name, daemon=True)
            self.thread.start()
        return self

    def request_stop(self):
        self._stop.set()

    def stop(self, timeout=5):
        with self._lock:
            self._stop.set()
            if self.thread is not None:
                self.thread.join(timeout=timeout)
                if self.thread.is_alive():
                    raise TimeoutError(f'{self.name} did not finish its active cycle')
                self.thread = None
