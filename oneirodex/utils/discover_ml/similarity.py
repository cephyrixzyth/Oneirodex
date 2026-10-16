"""Neighbourhoods — what a title is like, and what gets played alongside it.

Two methods write into the same table.

``content`` compares facet sets. It works on an install with one member and a
library nobody has touched, which is why it is the default and why *Because you
played X* can appear on day one.

``collab`` counts how often two titles are played by the same people. It is a
genuinely better signal — when there are enough people. Below the floor it is
noise wearing a lab coat: with four members, two titles co-occurring once is
indistinguishable from coincidence, and the recommender would state it with the
same confidence as a real result. So the job skips it, the blend falls back to
pure content, and nothing pretends otherwise.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameSimilarity, UserGameProgress

from .profile import game_facets

#: Members with real play history before collaborative filtering is trusted.
#: Below this the co-occurrence counts are dominated by chance.
COLLAB_MIN_MEMBERS = 25

#: Played titles a member needs before they count toward the floor.
COLLAB_MIN_TITLES_PER_MEMBER = 3

#: Neighbours kept per title. The feed shows a handful; storing hundreds would
#: grow the table quadratically for rows nobody scrolls to.
MAX_NEIGHBOURS = 20

#: How the two methods combine when both have an opinion.
CONTENT_BLEND = 0.7
COLLAB_BLEND = 0.3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collab_is_meaningful() -> bool:
    """Whether this install has the population for co-occurrence to mean anything."""
    counts = db.session.execute(
        select(UserGameProgress.user_id)
        .group_by(UserGameProgress.user_id)
        .having(func.count(UserGameProgress.game_uuid) >= COLLAB_MIN_TITLES_PER_MEMBER)
    ).all()
    return len(counts) >= COLLAB_MIN_MEMBERS


def content_neighbours(game_uuids, *, limit=MAX_NEIGHBOURS):
    """Jaccard overlap of facet sets, as ``uuid -> [(neighbour, score), ...]``.

    Jaccard rather than raw overlap count so a title tagged with twenty genres
    does not become everybody's nearest neighbour.
    """
    uuids = list(game_uuids)
    facets = game_facets(uuids)
    facet_sets = {uuid: set(facets.get(uuid, ())) for uuid in uuids}

    # Invert the map so each title is only compared against titles it shares at
    # least one facet with, rather than against the whole library.
    by_facet: dict[tuple[str, int], list[str]] = defaultdict(list)
    for uuid, owned in facet_sets.items():
        for facet in owned:
            by_facet[facet].append(uuid)

    neighbours: dict[str, list[tuple[str, float]]] = {}
    for uuid, owned in facet_sets.items():
        if not owned:
            continue
        shared: dict[str, int] = defaultdict(int)
        for facet in owned:
            for other in by_facet.get(facet, ()):
                if other != uuid:
                    shared[other] += 1

        scored = []
        for other, overlap in shared.items():
            union = len(owned | facet_sets[other])
            if union:
                scored.append((other, overlap / union))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        if scored:
            neighbours[uuid] = scored[:limit]
    return neighbours


def collab_neighbours(*, limit=MAX_NEIGHBOURS):
    """Normalised co-occurrence across members who actually played things.

    Returns an empty map when the install is below the population floor, so a
    caller does not have to remember to check.
    """
    if not collab_is_meaningful():
        return {}

    rows = db.session.execute(
        select(UserGameProgress.user_id, UserGameProgress.game_uuid)
    ).all()
    by_user: dict[int, set[str]] = defaultdict(set)
    for user_id, game_uuid in rows:
        by_user[user_id].add(game_uuid)

    plays: dict[str, int] = defaultdict(int)
    together: dict[tuple[str, str], int] = defaultdict(int)
    for played in by_user.values():
        ordered = sorted(played)
        for uuid in ordered:
            plays[uuid] += 1
        for i, first in enumerate(ordered):
            for second in ordered[i + 1:]:
                together[(first, second)] += 1

    neighbours: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (first, second), count in together.items():
        # Cosine over play counts: a title everybody touches does not become
        # every other title's neighbour just by being popular.
        denominator = (plays[first] * plays[second]) ** 0.5
        if not denominator:
            continue
        score = count / denominator
        neighbours[first].append((second, score))
        neighbours[second].append((first, score))

    for uuid, scored in neighbours.items():
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        neighbours[uuid] = scored[:limit]
    return dict(neighbours)


def store_neighbours(method: str, neighbours) -> int:
    """Replace every stored neighbourhood for one method."""
    db.session.execute(delete(GameSimilarity).where(GameSimilarity.method == method))
    stamp = _now()
    written = 0
    for game_uuid, scored in neighbours.items():
        for neighbour_uuid, score in scored:
            if score <= 0:
                continue
            db.session.add(
                GameSimilarity(
                    game_uuid=game_uuid,
                    neighbour_uuid=neighbour_uuid,
                    score=float(score),
                    method=method,
                    computed_at=stamp,
                )
            )
            written += 1
    db.session.commit()
    return written


def neighbours_of(game_uuid, *, limit=MAX_NEIGHBOURS) -> list[tuple[str, float]]:
    """Blended neighbours of one title, best first — the request path.

    Content and collaborative scores are blended when both exist. On an install
    below the population floor there are no collaborative rows at all, so this
    silently returns pure content scores rather than nothing.
    """
    rows = db.session.execute(
        select(
            GameSimilarity.neighbour_uuid,
            GameSimilarity.method,
            GameSimilarity.score,
        ).where(GameSimilarity.game_uuid == game_uuid)
    ).all()

    blended: dict[str, float] = defaultdict(float)
    for neighbour_uuid, method, score in rows:
        weight = COLLAB_BLEND if method == 'collab' else CONTENT_BLEND
        blended[neighbour_uuid] += weight * (score or 0.0)

    scored = sorted(blended.items(), key=lambda pair: (-pair[1], pair[0]))
    return scored[:limit]


def rebuild(*, limit=MAX_NEIGHBOURS) -> dict:
    """Recompute every neighbourhood. Called by the scheduled job."""
    uuids = [row[0] for row in db.session.execute(select(Game.uuid)).all()]
    content = store_neighbours('content', content_neighbours(uuids, limit=limit))

    collab_ran = collab_is_meaningful()
    collab = store_neighbours('collab', collab_neighbours(limit=limit)) if collab_ran else 0
    if not collab_ran:
        # Clear anything a previously larger install left behind, so a shrunken
        # one is not still serving co-occurrence it no longer has the
        # population to justify.
        db.session.execute(delete(GameSimilarity).where(GameSimilarity.method == 'collab'))
        db.session.commit()

    return {
        'games': len(uuids),
        'content_pairs': content,
        'collab_pairs': collab,
        'collab_ran': collab_ran,
    }
