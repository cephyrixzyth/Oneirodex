"""One place to read the GlobalSettings singleton.

`global_settings` is a one-row table, but nothing at the database level enforces
that and roughly fifteen code paths will create a row when they find none — so a
race at startup, or a restore that merged two dumps, can leave two.

Most readers used to do:

    db.session.execute(select(GlobalSettings)).scalar_one_or_none()

which raises ``MultipleResultsFound`` the moment a second row exists. Six of
those were in the login blueprint, so a duplicate row would have locked every
user out of the site. Others sat in the scanner and in game_core, where the
failure would surface as an unrelated-looking scan error.

Reading the lowest id is what the settings writers already assume elsewhere
(``quality_profiles._settings_row``), and a second row should degrade to "use
the first", never to a 500.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from oneirodex.models import GlobalSettings
from oneirodex.runtime_native.db_session import native_db as db


def global_settings_row() -> GlobalSettings | None:
    """The settings singleton, or None when setup has not created it yet."""
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()


def global_settings_row_or_create() -> GlobalSettings:
    """The settings singleton, creating it when absent.

    Flushes rather than commits so the caller keeps control of the transaction.

    The insert runs inside a SAVEPOINT because the table now carries a
    single-row unique index (see cleanup_duplicate_global_settings in
    updateschema.py). That turns the old failure mode inside out: two workers
    racing on first boot used to *both* succeed and leave a duplicate, where a
    later write could land on the row nobody reads and silently not take
    effect. Now the loser gets an IntegrityError, which is recoverable — the
    winner's row is the answer we wanted anyway. The savepoint is what keeps
    that collision from poisoning the caller's surrounding transaction.
    """
    row = global_settings_row()
    if row is not None:
        return row

    try:
        with db.session.begin_nested():
            row = GlobalSettings()
            db.session.add(row)
    except IntegrityError:
        row = global_settings_row()
        if row is None:
            # Not the race — the insert was rejected for some other reason, and
            # swallowing that would hand back None to callers annotated as
            # returning a row.
            raise
    return row


# Duplicates are collapsed at startup by
# `DatabaseManager.cleanup_duplicate_global_settings` in updateschema.py,
# alongside the other data cleanups.
