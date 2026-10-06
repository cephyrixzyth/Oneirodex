# oneirodex/utils/setup.py
from oneirodex import db
from oneirodex.models import User
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from sqlalchemy import select
from datetime import datetime, timezone

def is_setup_required():
    """Check if setup is required (no users exist)"""
    return not db.session.execute(select(User)).scalars().first()

def get_or_create_global_settings():
    """Get existing global settings or create a new instance.

    Reads via global_settings_row() so this module agrees with every other
    reader about *which* row is the singleton. The bare `.first()` it used had
    no ORDER BY, and the table is only a singleton by convention — with more
    than one row present Postgres is free to return a different one per query,
    so this could hand back a row that a caller had just configured a moment
    earlier and see none of its values.

    Creates through global_settings_row_or_create() for the same reason
    get_or_create_settings_record does: the singleton unique index turns a
    concurrent first-boot insert into an IntegrityError, and the helper's
    SAVEPOINT is what makes that recoverable instead of a 500. The commit stays
    here — callers of *this* function expect a persisted row — while the
    helper's flush is what stage_setup_step relies on.
    """
    settings = global_settings_row()
    if not settings:
        settings = global_settings_row_or_create()
        db.session.commit()
    return settings

def is_setup_in_progress():
    """Check if setup is currently in progress"""
    if is_setup_required():
        return True  # If no users exist, setup is required
    
    settings = get_or_create_global_settings()
    return settings.setup_in_progress and not settings.setup_completed

def get_current_setup_step():
    """Get the current setup step number"""
    if is_setup_required():
        return 1  # Always start with step 1 if no users exist
    
    settings = get_or_create_global_settings()
    if settings.setup_in_progress and not settings.setup_completed:
        return settings.setup_current_step
    return None  # Not in setup

def set_setup_step(step):
    """Update the current setup step and mark setup as in progress"""
    settings = get_or_create_global_settings()
    settings.setup_in_progress = True
    settings.setup_current_step = step
    settings.setup_completed = False
    settings.last_updated = datetime.now(timezone.utc)
    db.session.commit()

def mark_setup_complete():
    """Mark setup as fully completed"""
    settings = get_or_create_global_settings()
    settings.setup_in_progress = False
    settings.setup_completed = True
    # Keep the recorded step at the end of the six-stage first-run path so an
    # interrupted/replayed wizard never bounces back to credentials or setup.
    settings.setup_current_step = 6  # Final step
    settings.last_updated = datetime.now(timezone.utc)
    db.session.commit()

def reset_setup_state():
    """Reset setup state (used for --force-setup)"""
    settings = get_or_create_global_settings()
    settings.setup_in_progress = True
    settings.setup_current_step = 1
    settings.setup_completed = False
    settings.last_updated = datetime.now(timezone.utc)
    db.session.commit()

def should_redirect_to_setup():
    """Check if requests should be redirected to setup"""
    return is_setup_required() or is_setup_in_progress()

def get_setup_redirect_url():
    """Get the appropriate setup URL for the current step"""
    if is_setup_required():
        return '/setup'

    current_step = get_current_setup_step()
    if current_step == 1:
        # A user exists but the wizard still thinks it is on step 1 — the state
        # the old non-atomic setup_submit could strand an install in. Returning
        # '/setup' here is what made it a loop, because /setup redirects back to
        # this function. Step 1 *is* "create the admin account", and that is
        # provably done, so advance instead of bouncing.
        set_setup_step(2)
        return '/setup/smtp'
    elif current_step == 2:
        return '/setup/smtp'
    elif current_step == 3:
        return '/setup/features'
    elif current_step == 4:
        return '/setup/igdb'
    elif current_step == 5:
        return '/setup/integrations'
    elif current_step == 6:
        return '/setup/library'
    else:
        return '/setup'  # Default fallback

def stage_setup_step(step):
    """Set the setup step on the current session WITHOUT committing.

    set_setup_step() commits, which is wrong when the caller is mid-transaction:
    the admin account and its step advance have to succeed or fail together, or
    a failure between them strands the install on step 1 with a user present —
    a state get_setup_redirect_url() turns into an endless /setup redirect.

    Callers own the commit. Note this must not call
    get_or_create_global_settings(): on a fresh install there is no settings row
    (is_setup_required short-circuits before anything would create one), so that
    helper would commit the caller's pending admin user alongside a settings row
    still holding the column default of step 1 — reopening the very window this
    function exists to close.

    global_settings_row_or_create() is the canonical create-without-commit read:
    it flushes, so the row is usable immediately but still rolls back with the
    caller's transaction.
    """
    settings = global_settings_row_or_create()
    settings.setup_in_progress = True
    settings.setup_current_step = step
    settings.setup_completed = False
    settings.last_updated = datetime.now(timezone.utc)
