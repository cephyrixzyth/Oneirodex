"""
Graceful shutdown handling for Oneirodex.
Provides signal handlers and shutdown state management for clean application exit.
"""

from contextvars import ContextVar
from functools import wraps
import threading
from typing import Optional


class ShutdownManager:
    """Manages graceful shutdown state and signal handling."""
    
    def __init__(self):
        self._shutdown_requested = threading.Event()
        self._shutdown_timeout = 30  # seconds
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested.is_set()
    
    def request_shutdown(self):
        """Request graceful shutdown."""
        if not self._shutdown_requested.is_set():
            print("\n🛑 Graceful shutdown requested...")
            self._shutdown_requested.set()
    
    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for shutdown request.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if shutdown was requested, False if timeout occurred
        """
        return self._shutdown_requested.wait(timeout)
    
# Global shutdown manager instance
shutdown_manager = ShutdownManager()


_worker_owner = ContextVar('oneirodex_shutdown_owner', default=None)


def begin_lifespan() -> None:
    """A restarted server accepts work under a fresh shutdown event."""
    global shutdown_manager
    if shutdown_manager.is_shutdown_requested():
        shutdown_manager = ShutdownManager()


def bind_shutdown_owner(target):
    """Capture the caller's lifespan before a worker is dispatched to a thread."""
    manager = _worker_owner.get() or shutdown_manager

    @wraps(target)
    def run(*args, **kwargs):
        token = _worker_owner.set(manager)
        try:
            return target(*args, **kwargs)
        finally:
            _worker_owner.reset(token)
    return run


def should_continue_processing() -> bool:
    """
    Check if background processing should continue.
    Long-running tasks should call this periodically.
    
    Returns:
        True if processing should continue, False if shutdown requested
    """
    return not (_worker_owner.get() or shutdown_manager).is_shutdown_requested()


def request_shutdown():
    """Request graceful application shutdown."""
    shutdown_manager.request_shutdown()


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested."""
    return shutdown_manager.is_shutdown_requested()


def sleep_interruptible(duration: float) -> bool:
    """
    Sleep for specified duration, but return early if shutdown requested.
    
    Args:
        duration: Sleep duration in seconds
        
    Returns:
        True if sleep completed normally, False if interrupted by shutdown
    """
    return not (_worker_owner.get() or shutdown_manager).wait_for_shutdown(duration)
