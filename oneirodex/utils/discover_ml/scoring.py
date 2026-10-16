"""Turning a stored profile into an ordering — the request-path half.

Everything expensive already ran in the job. This module only reads what was
materialised, so a Discover load stays a handful of SELECTs no matter how much
signal the install has accumulated.
"""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, UserGameProgress, user_favorites, user_game_status
from oneirodex.utils.play_status import WONT_PLAY

from .impressions import damping_for
from .profile import game_facets, load_profile

#: Weight of the rating prior relative to facet affinity. Deliberately small:
#: a well-regarded title the member has no affinity for should not outrank a
#: middling one squarely in their taste.
QUALITY_WEIGHT = 0.25


def already_engaged(user_id) -> set[str]:
    """Titles a recommendation row should not be recommending back.

    A "for you" row that shows what you already favourited or played is not a
    recommendation, it is a mirror.

    It also covers titles marked **Won't play** (INSP-4). That status has been
    recordable for a long time and nothing read it, so a member could say no to
    a game and keep being offered it -- the single most irritating thing a
    recommender can do, because it looks like not listening.

    Suppressing the title is as far as this goes on purpose. One "won't play"
    is not evidence against its whole genre, and letting a single no reweigh
    every facet it touches would quietly narrow the shelves on the strength of
    one click.
    """
    engaged = {
        row[0]
        for row in db.session.execute(
            select(user_favorites.c.game_uuid).where(
                user_favorites.c.user_id == user_id
            )
        ).all()
    }
    engaged.update(
        row[0]
        for row in db.session.execute(
            select(UserGameProgress.game_uuid).where(
                UserGameProgress.user_id == user_id
            )
        ).all()
    )
    engaged.update(
        row[0]
        for row in db.session.execute(
            select(user_game_status.c.game_uuid).where(
                user_game_status.c.user_id == user_id,
                user_game_status.c.status == WONT_PLAY,
            )
        ).all()
    )
    return engaged


def affinity_scores(user_id, game_uuids) -> dict[str, float]:
    """How well each title matches the member's stored taste.

    Cosine rather than a raw dot product, so a title carrying twenty facets does
    not outscore a precise match simply by overlapping more.
    """
    profile = load_profile(user_id)
    if not profile:
        return {}

    facets = game_facets(game_uuids)
    profile_norm = math.sqrt(sum(weight * weight for weight in profile.values())) or 1.0

    scores: dict[str, float] = defaultdict(float)
    for game_uuid, owned in facets.items():
        if not owned:
            continue
        dot = sum(profile.get(facet, 0.0) for facet in owned)
        if dot <= 0:
            continue
        scores[game_uuid] = dot / (profile_norm * math.sqrt(len(owned)))
    return dict(scores)


def rank_candidates(user_id, games, *, limit=None):
    """Order games by taste, quality prior and impression damping.

    Returns the games themselves, best first, so a caller can hand the result
    straight to the feed without a second lookup.
    """
    uuids = [getattr(game, 'uuid', None) for game in games]
    uuids = [uuid for uuid in uuids if uuid]
    if not uuids:
        return []

    affinity = affinity_scores(user_id, uuids)
    if not affinity:
        # No stored profile yet. Returning the input untouched is honest: the
        # caller's own ordering is better than a ranking built on nothing.
        return list(games)[:limit] if limit else list(games)

    damping = damping_for(user_id)

    def total(game):
        uuid = getattr(game, 'uuid', None)
        base = affinity.get(uuid, 0.0)
        rating = getattr(game, 'rating', None)
        if rating:
            # Ratings are 0-100 in this schema.
            base += QUALITY_WEIGHT * (float(rating) / 100.0)
        return base * damping.get(uuid, 1.0)

    ranked = sorted(games, key=lambda game: (-total(game), getattr(game, 'name', '')))
    return ranked[:limit] if limit else ranked


def top_anchors(user_id, *, limit=3) -> list[Game]:
    """Titles worth building a "because you played" row around.

    Most-played first, because a member recognises what they have actually put
    hours into — a row anchored on something they bounced off reads as a
    misunderstanding rather than a recommendation.
    """
    rows = db.session.execute(
        select(UserGameProgress.game_uuid)
        .where(
            UserGameProgress.user_id == user_id,
            UserGameProgress.total_seconds > 0,
        )
        .order_by(
            UserGameProgress.total_seconds.desc(),
            UserGameProgress.last_played_at.desc().nullslast(),
        )
        .limit(limit)
    ).all()
    uuids = [row[0] for row in rows]
    if not uuids:
        return []

    games = db.session.execute(
        select(Game).where(Game.uuid.in_(uuids))
    ).scalars().all()
    by_uuid = {game.uuid: game for game in games}
    return [by_uuid[uuid] for uuid in uuids if uuid in by_uuid]
