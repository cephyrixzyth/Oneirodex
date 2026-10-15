"""Impression damping and daily rotation — how the feed stays fresh.

"Fresh content" reads like a modelling problem and is not one. The reason the
same eight tiles greet somebody every morning is that nothing remembers having
shown them. Two mechanics fix that, and neither involves a recommender:

* **Damping.** A title shown repeatedly and never opened is scored down, so the
  feed stops insisting. Opening it clears the damping — a tile that got clicked
  has earned its place.
* **Rotation.** The ranked tail is shuffled with a seed derived from the member
  and the date, so the feed is stable within a day and different tomorrow.
  Reshuffling on every request instead would read as broken: tiles would move
  under the pointer between one glance and the next.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import UserDiscoverImpression

#: Score multiplier floor. A damped title is pushed down, never suppressed —
#: a member who has ignored everything should still get a feed.
MIN_DAMPING = 0.35

#: Impressions before damping reaches its floor.
DAMPING_SATURATION = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_impressions(user_id, game_uuids) -> int:
    """Note that these titles were put in front of this member.

    One statement for the whole feed. Failure is swallowed by the caller rather
    than allowed to break a page — an un-recorded impression costs a little
    freshness, and nothing else.
    """
    uuids = [uuid for uuid in dict.fromkeys(game_uuids) if uuid]
    if not uuids or user_id is None:
        return 0

    stamp = _now()
    statement = pg_insert(UserDiscoverImpression.__table__).values(
        [
            {
                'user_id': user_id,
                'game_uuid': uuid,
                'shown_count': 1,
                'last_shown_at': stamp,
            }
            for uuid in uuids
        ]
    )
    statement = statement.on_conflict_do_update(
        constraint='uq_user_discover_impression',
        set_={
            'shown_count': UserDiscoverImpression.__table__.c.shown_count + 1,
            'last_shown_at': stamp,
        },
    )
    db.session.execute(statement)
    db.session.commit()
    return len(uuids)


def record_click(user_id, game_uuid) -> None:
    """A title the member actually opened stops being damped."""
    if user_id is None or not game_uuid:
        return
    stamp = _now()
    statement = pg_insert(UserDiscoverImpression.__table__).values(
        user_id=user_id,
        game_uuid=game_uuid,
        shown_count=0,
        clicked_at=stamp,
    )
    statement = statement.on_conflict_do_update(
        constraint='uq_user_discover_impression',
        set_={'clicked_at': stamp},
    )
    db.session.execute(statement)
    db.session.commit()


def damping_for(user_id) -> dict[str, float]:
    """Per-title score multipliers for one member.

    Titles with no impressions are absent, which callers read as 1.0 — the
    common case costs nothing.
    """
    if user_id is None:
        return {}
    rows = db.session.execute(
        select(
            UserDiscoverImpression.game_uuid,
            UserDiscoverImpression.shown_count,
            UserDiscoverImpression.clicked_at,
        ).where(UserDiscoverImpression.user_id == user_id)
    ).all()

    damping: dict[str, float] = {}
    for game_uuid, shown, clicked_at in rows:
        if clicked_at is not None:
            continue
        shown = max(0, int(shown or 0))
        if shown <= 1:
            continue
        # Linear ramp to the floor; simple beats clever here, and the shape is
        # easy to reason about when a recommendation looks wrong.
        fraction = min(1.0, (shown - 1) / DAMPING_SATURATION)
        damping[game_uuid] = 1.0 - (1.0 - MIN_DAMPING) * fraction
    return damping


def rotation_seed(user_id, *, today=None) -> int:
    """A seed that changes daily and differs per member.

    Derived rather than random so the same member gets the same arrangement all
    day: a feed that reshuffles on every request reads as broken rather than
    fresh.
    """
    day = (today or date.today()).isoformat()
    digest = hashlib.sha1(f'{user_id}:{day}'.encode('utf-8')).hexdigest()
    return int(digest[:8], 16)
