"""The taste profile — what a member reaches for, as facet weights.

Signals are weighted by how much intent each one carries. Favouriting is a
deliberate act and counts most; owning a title on a store is a weak signal,
because a bundle buys you fifty games you never asked for. Playtime is scaled
logarithmically so a single 400-hour obsession does not drown out the twenty
titles that better describe a taste.

Everything is decayed by how long ago it happened, so a profile follows a member
rather than fossilising around whatever they were into two years ago.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.utils.play_status import FINISHED_STATUSES
from oneirodex.models import (
    DownloadRequest,
    Game,
    UserGameProgress,
    UserOwnedTitle,
    UserTasteFacet,
    game_genre_association,
    game_player_perspective_association,
    game_theme_association,
    user_favorites,
    user_game_status,
)

#: How much intent each signal carries. These are the knobs worth tuning if a
#: profile ever feels wrong; nothing else in this module is a magic number.
SIGNAL_WEIGHTS = {
    'favorite': 3.0,
    'finished': 2.5,
    'download': 0.8,
    'owned': 1.0,
}

#: Playtime contributes `PLAYTIME_SCALE * ln(1 + hours)`, so the twentieth hour
#: on a title counts for far less than the first.
PLAYTIME_SCALE = 0.5

#: Signals halve in weight roughly every this many days.
DECAY_HALF_LIFE_DAYS = 60.0

FACET_TYPES = ('genre', 'theme', 'perspective', 'developer')


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decay(when, *, now=None) -> float:
    """Recency multiplier in (0, 1]. Undated signals are treated as current."""
    if when is None:
        return 1.0
    moment = now or _now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = max(0.0, (moment - when).total_seconds() / 86400.0)
    return math.exp(-days / DECAY_HALF_LIFE_DAYS)


def collect_signals(user_id, *, now=None) -> dict[str, float]:
    """Per-game interest scores for one member, before facets are involved."""
    scores: dict[str, float] = defaultdict(float)

    favourites = db.session.execute(
        select(user_favorites.c.game_uuid).where(user_favorites.c.user_id == user_id)
    ).all()
    for (game_uuid,) in favourites:
        scores[game_uuid] += SIGNAL_WEIGHTS['favorite']

    progress = db.session.execute(
        select(
            UserGameProgress.game_uuid,
            UserGameProgress.total_seconds,
            UserGameProgress.last_played_at,
        ).where(UserGameProgress.user_id == user_id)
    ).all()
    for game_uuid, seconds, last_played in progress:
        hours = max(0.0, (seconds or 0) / 3600.0)
        if hours <= 0:
            continue
        scores[game_uuid] += (
            PLAYTIME_SCALE * math.log1p(hours) * _decay(last_played, now=now)
        )

    finished = db.session.execute(
        select(user_game_status.c.game_uuid, user_game_status.c.updated_at).where(
            user_game_status.c.user_id == user_id,
            user_game_status.c.status.in_(FINISHED_STATUSES),
        )
    ).all()
    for game_uuid, updated_at in finished:
        scores[game_uuid] += SIGNAL_WEIGHTS['finished'] * _decay(updated_at, now=now)

    owned = db.session.execute(
        select(UserOwnedTitle.matched_game_uuid).where(
            UserOwnedTitle.user_id == user_id,
            UserOwnedTitle.matched_game_uuid.isnot(None),
        )
    ).all()
    for (game_uuid,) in owned:
        scores[game_uuid] += SIGNAL_WEIGHTS['owned']

    downloads = db.session.execute(
        select(DownloadRequest.game_uuid).where(DownloadRequest.user_id == user_id)
    ).all()
    for (game_uuid,) in downloads:
        if game_uuid:
            scores[game_uuid] += SIGNAL_WEIGHTS['download']

    return dict(scores)


def game_facets(game_uuids) -> dict[str, list[tuple[str, int]]]:
    """Facets for a set of games, as ``uuid -> [(facet_type, facet_id), ...]``.

    Four queries for the whole set rather than four per game — the same reason
    the card serializer batches.
    """
    uuids = list(game_uuids)
    facets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    if not uuids:
        return facets

    # The association tables key on `games.id`, while every signal in this
    # module is keyed by uuid — so each one joins back through Game rather than
    # filtering on a column it does not have.
    association_tables = (
        ('genre', game_genre_association, 'genre_id'),
        ('theme', game_theme_association, 'theme_id'),
        ('perspective', game_player_perspective_association, 'player_perspective_id'),
    )
    for facet_type, table, column in association_tables:
        rows = db.session.execute(
            select(Game.uuid, table.c[column])
            .join(table, table.c.game_id == Game.id)
            .where(Game.uuid.in_(uuids))
        ).all()
        for game_uuid, facet_id in rows:
            if facet_id is not None:
                facets[game_uuid].append((facet_type, facet_id))

    developers = db.session.execute(
        select(Game.uuid, Game.developer_id).where(
            Game.uuid.in_(uuids), Game.developer_id.isnot(None)
        )
    ).all()
    for game_uuid, developer_id in developers:
        facets[game_uuid].append(('developer', developer_id))

    return facets


def build_profile(user_id, *, now=None) -> dict[tuple[str, int], float]:
    """Facet weights for one member. Empty when they have given no signal."""
    scores = collect_signals(user_id, now=now)
    if not scores:
        return {}

    facets = game_facets(scores.keys())
    weights: dict[tuple[str, int], float] = defaultdict(float)
    for game_uuid, score in scores.items():
        for facet in facets.get(game_uuid, ()):
            weights[facet] += score
    return dict(weights)


def store_profile(user_id, weights) -> int:
    """Replace a member's stored profile. Returns how many facets were written.

    Replace rather than merge: a facet that has dropped out of a taste should
    disappear, and a profile assembled from a partial rebuild would quietly
    describe somebody who no longer exists.
    """
    db.session.execute(
        delete(UserTasteFacet).where(UserTasteFacet.user_id == user_id)
    )
    written = 0
    stamp = _now()
    for (facet_type, facet_id), weight in weights.items():
        if weight <= 0:
            continue
        db.session.add(
            UserTasteFacet(
                user_id=user_id,
                facet_type=facet_type,
                facet_id=facet_id,
                weight=float(weight),
                updated_at=stamp,
            )
        )
        written += 1
    db.session.commit()
    return written


def load_profile(user_id) -> dict[tuple[str, int], float]:
    """A member's stored facet weights, for the request path."""
    rows = db.session.execute(
        select(
            UserTasteFacet.facet_type,
            UserTasteFacet.facet_id,
            UserTasteFacet.weight,
        ).where(UserTasteFacet.user_id == user_id)
    ).all()
    return {(facet_type, facet_id): weight for facet_type, facet_id, weight in rows}


def rebuild_profile(user_id, *, now=None) -> int:
    return store_profile(user_id, build_profile(user_id, now=now))
