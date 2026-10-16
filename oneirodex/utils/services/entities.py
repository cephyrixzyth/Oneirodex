"""Thread-safe get-or-create for taxonomy entities.

Moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3. Lives in its
own module (not scan_identify) so game_enrich and scan_identify can both import
it without a cycle.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from oneirodex.runtime_native.db_session import native_db as db

__all__ = ["get_or_create_entity"]


def get_or_create_entity(model_class, name_field="name", **kwargs):
    """
    Thread-safe helper to get an existing entity or create a new one.
    Handles race conditions that occur during multithreaded scanning.
    
    Args:
        model_class: The SQLAlchemy model class (Genre, Theme, etc.)
        name_field: The field name to query by (default: "name")
        **kwargs: The attributes to query and create with
        
    Returns:
        The existing or newly created entity instance
    """
    filter_value = kwargs.get(name_field)
    
    # First attempt: try to get existing entity
    entity = db.session.execute(
        select(model_class).filter_by(**{name_field: filter_value})
    ).scalar_one_or_none()
    
    if entity:
        return entity
    
    # Entity doesn't exist, try to create it
    try:
        entity = model_class(**kwargs)
        db.session.add(entity)
        db.session.flush()  # Flush to check for constraint violations immediately
        return entity
    except IntegrityError:
        # Handle race condition: another thread created the entity
        db.session.rollback()
        # Query again to get the entity created by the other thread
        entity = db.session.execute(
            select(model_class).filter_by(**{name_field: filter_value})
        ).scalar_one_or_none()
        if entity:
            return entity
        else:
            # This should not happen, but raise an error if it does
            raise RuntimeError(f"Failed to create or retrieve {model_class.__name__} with {name_field}='{filter_value}'")
