"""Catalog/library counters, first-run state, association teardown.

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""
from sqlalchemy import select, func
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Library, Game, ScanJob, UnmatchedFolder

__all__ = [
    "get_library_count",
    "get_games_count",
    "get_first_run_state",
    "delete_associations_for_game",
]


def get_library_count():
    return int(db.session.execute(select(func.count()).select_from(Library)).scalar() or 0)


def get_games_count():
    return int(db.session.execute(select(func.count()).select_from(Game)).scalar() or 0)


def get_first_run_state():
    """What the empty catalog actually means, for the empty state to say it.

    Three situations render the same blank grid and want three different
    sentences, and counts alone cannot tell them apart (UID-043):

    - no library has been added yet;
    - a library exists but no scan has ever finished, so nothing has looked;
    - a scan finished and matched nothing, which is a *problem to act on* and
      was previously indistinguishable from "you haven't started".

    ``scan_has_run`` is true once any job reaches a terminal state. Terminal,
    not ``last_run``, because a job that is Queued or Running has a timestamp
    the moment it is picked up — telling the operator a scan had run while it
    was still running is the same wrong answer in the opposite direction.

    ``unmatched_count`` is what a finished scan could not place. It is the
    actionable half: "a scan ran and found 40 folders it could not match" points
    at Unmatched, where the operator can do something, instead of leaving them
    to guess whether the scan even happened.
    """
    terminal = ('Completed', 'Failed', 'Cancelled')
    scan_has_run = bool(
        db.session.execute(
            select(func.count())
            .select_from(ScanJob)
            .where(ScanJob.status.in_(terminal))
        ).scalar() or 0
    )
    unmatched_count = int(
        db.session.execute(
            select(func.count())
            .select_from(UnmatchedFolder)
            .where(UnmatchedFolder.status.in_(('Pending', 'Unmatched')))
        ).scalar() or 0
    )
    return {'scan_has_run': scan_has_run, 'unmatched_count': unmatched_count}

def delete_associations_for_game(game_to_delete):
    associations = [game_to_delete.genres, game_to_delete.platforms, game_to_delete.game_modes,
                    game_to_delete.themes, game_to_delete.player_perspectives, game_to_delete.multiplayer_modes]
    
    for association in associations:
        association.clear()
