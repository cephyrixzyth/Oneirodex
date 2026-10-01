"""*Surprise me* and the taste picker (INSP-4b).

One title, drawn from the top of the member's own ranking rather than from the
whole shelf. A pick from the entire library is a coin toss that mostly lands on
things nobody in the house wanted; a pick from the single best match is the
same answer every time, which is not a surprise. The top of the ranking is the
narrow band where both hold.

The picker is the member's strongest genres, read from the stored taste
profile, offered as a way to steer the draw. Nothing here writes: pressing the
button is not a signal, and treating it as one would teach the profile that a
member likes whatever the dice happened to show them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, Genre
from oneirodex.utils.library_acl import apply_game_access_filters

from .profile import load_profile
from .scoring import already_engaged, rank_candidates

#: How many of the best-ranked titles the draw chooses between. Wide enough that
#: pressing again usually shows something new, narrow enough that every answer
#: is still one the ranking would stand behind.
DRAW_WIDTH = 12

#: How many titles are ranked to find that band. Ranking is cheap next to the
#: query, but the whole library is not a candidate set.
CANDIDATE_POOL = 200

#: How many genres the picker offers. Past a handful it stops being *your*
#: taste and becomes the genre list.
PICKER_GENRES = 6

#: The most recent picks a caller may ask us not to repeat.
MAX_EXCLUDE = 30


@dataclass(frozen=True)
class SurprisePick:
    game: Optional[Game]
    reason: str
    genre: Optional[Genre]


def taste_genres(user_id, *, limit: int = PICKER_GENRES) -> list[Genre]:
    """The member's strongest genres, strongest first. Empty with no profile."""
    weights = {
        facet_id: weight
        for (facet_type, facet_id), weight in load_profile(user_id).items()
        if facet_type == 'genre' and weight > 0
    }
    if not weights:
        return []
    top = sorted(weights, key=lambda facet_id: -weights[facet_id])[:limit]
    genres = {
        genre.id: genre
        for genre in db.session.execute(
            select(Genre).where(Genre.id.in_(top))
        ).scalars()
    }
    return [genres[facet_id] for facet_id in top if facet_id in genres]


def pick_surprise(user, *, genre: Optional[Genre] = None, exclude=(), rng=None) -> SurprisePick:
    """Draw one title the member has not touched, from the top of their ranking.

    ``exclude`` is what this member was just shown, so "another" moves on. It
    is a courtesy, not a guarantee: when the band is exhausted the draw starts
    over rather than coming back empty while unseen-this-session titles remain.
    """
    rng = rng or random.Random()
    skip = set(already_engaged(user.id))
    recent = {str(uuid) for uuid in list(exclude)[:MAX_EXCLUDE] if uuid}

    query = select(Game)
    if genre is not None:
        query = query.join(Game.genres).where(Genre.id == genre.id)
    if skip:
        query = query.where(Game.uuid.notin_(skip))
    query = query.order_by(Game.rating.desc().nullslast(), Game.id).limit(CANDIDATE_POOL)
    candidates = db.session.execute(
        apply_game_access_filters(query, user)
    ).scalars().unique().all()

    if not candidates:
        return SurprisePick(game=None, reason=_empty_reason(genre), genre=genre)

    band = rank_candidates(user.id, candidates, limit=DRAW_WIDTH)
    fresh = [game for game in band if game.uuid not in recent] or band
    choice = rng.choice(fresh)
    return SurprisePick(game=choice, reason=_reason(user.id, genre), genre=genre)


def _reason(user_id, genre: Optional[Genre]) -> str:
    if genre is not None:
        return f'From your {genre.name} picks'
    if load_profile(user_id):
        return 'Picked from what you play'
    # No profile yet: the ranking fell back to rating order, and saying it was
    # "picked from what you play" would be claiming a signal we do not have.
    return "Well regarded, and you haven't tried it"


def _empty_reason(genre: Optional[Genre]) -> str:
    if genre is not None:
        return f"Nothing in {genre.name} you haven't already tried."
    return "Nothing left you haven't already tried."
