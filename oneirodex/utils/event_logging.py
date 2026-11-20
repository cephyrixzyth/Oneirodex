from contextvars import ContextVar
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import SystemEvents
from datetime import datetime, timezone
from typing import Optional, Union

# The signed-in user of the current request in the served (ASGI) runtime.
# Flask's ``current_user`` does not exist there, so request authentication
# records the user here and audit events fall back to it.
_ACTING_USER: ContextVar[Optional[int]] = ContextVar('oneirodex_acting_user', default=None)


def set_acting_user(user_id: Optional[int]) -> None:
    """Record who is acting for the rest of this request's context."""
    _ACTING_USER.set(user_id)


def log_system_event(
    event_text: str,
    event_type: str = 'log',
    event_level: str = 'information',
    audit_user: Optional[Union[int, str]] = None
) -> bool:
    """
    Log a system event to the database.
    
    Args:
        event_text (str): The message to log (required, max 256 chars)
        event_type (str, optional): Type of event (default: 'log', max 32 chars)
        event_level (str, optional): Level of event (default: 'information', max 32 chars)
        audit_user (Union[int, str], optional): User ID or 'system' for system events
            If None, attempts to get current_user.id, falls back to 'system'
    
    Returns:
        bool: True if logging was successful, False otherwise
    """
    try:
        # Truncate strings if they exceed maximum lengths
        event_text = event_text[:256]
        event_type = event_type[:32]
        event_level = event_level[:32]
        
        # Handle audit_user logic
        if audit_user is None:
            # The served runtime records the request's user; the Flask
            # current_user is only available in a Flask request context.
            audit_user = _ACTING_USER.get()
            if audit_user is None:
                try:
                    from flask_login import current_user

                    audit_user = getattr(current_user, 'id', None)
                except (ImportError, RuntimeError):
                    audit_user = None
        
        # Create new system event
        new_event = SystemEvents(
            event_text=event_text,
            event_type=event_type,
            event_level=event_level,
            audit_user=audit_user if audit_user != 'system' else None,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add and commit to database
        db.session.add(new_event)
        db.session.commit()
        
        return True
        
    except Exception as e:
        # SQL driver exception messages can contain the rejected row or connection details.
        print(f"Error logging system event: {type(e).__name__}")
        try:
            db.session.rollback()
        except Exception:
            # The session can already be gone when a stream disconnects.
            pass
        return False
