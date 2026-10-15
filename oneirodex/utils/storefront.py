"""Storefront Discover shelves — curated-for-you and upcoming (W25-STORE-1).

Curation is derived **only** from the member's own on-box signals (favorites,
play status, genres already in the library). No external recommender, no
telemetry leaving the box — same stance as the rest of the product.

Both builders return `[]` rather than filler when there is nothing honest to
show; the caller hides empty shelves.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    Game,
    GameRequest,
    Genre,
    IgdbPlatformRelease,
    Library,
    user_favorites,
)
from oneirodex.utils.library_acl import allowed_library_uuids, apply_game_access_filters

DEFAULT_SHELF_LIMIT = 8
# A title needs a real release date ahead of now to count as upcoming.
UPCOMING_HORIZON_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


def favorite_genre_ids(user, *, limit: int = 5) -> list[int]:
    """Genres the member actually favourites, most-favourited first."""
    rows = db.session.execute(
        select(Genre.id, func.count(Genre.id).label('hits'))
        .select_from(user_favorites)
        .join(Game, Game.uuid == user_favorites.c.game_uuid)
        .join(Game.genres)
        .where(user_favorites.c.user_id == user.id)
        .group_by(Genre.id)
        .order_by(func.count(Genre.id).desc())
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def build_curated_for_you(user, *, limit: int = DEFAULT_SHELF_LIMIT) -> list[Game]:
    """Unplayed titles in genres the member already favourites.

    Deliberately excludes anything already favourited — a "for you" shelf that
    only shows things you have already picked is noise. Returns [] when the
    member has no signal yet, so a new account sees the shelf hidden rather
    than a random sample dressed up as a recommendation.
    """
    genre_ids = favorite_genre_ids(user)
    if not genre_ids:
        return []

    already = select(user_favorites.c.game_uuid).where(user_favorites.c.user_id == user.id)
    query = (
        select(Game)
        .join(Game.genres)
        .where(Genre.id.in_(genre_ids))
        .where(Game.uuid.notin_(already))
        .group_by(Game.id)
        # Prefer well-regarded titles, then recent additions, so the shelf is
        # stable between loads rather than shuffling on every visit.
        .order_by(Game.rating.desc().nullslast(), Game.date_created.desc())
        .limit(limit)
    )
    return db.session.execute(apply_game_access_filters(query, user)).scalars().all()


def _wishlisted_game_uuids(user) -> set[str]:
    """Library titles this member has asked for: favourites + linked requests."""
    fav = db.session.execute(
        select(user_favorites.c.game_uuid).where(user_favorites.c.user_id == user.id)
    ).scalars().all()
    linked = db.session.execute(
        select(GameRequest.linked_game_uuid)
        .where(GameRequest.user_id == user.id)
        .where(GameRequest.linked_game_uuid.isnot(None))
    ).scalars().all()
    return {u for u in [*fav, *linked] if u}


def build_upcoming(user, *, limit: int = DEFAULT_SHELF_LIMIT, now: datetime | None = None) -> list[Game]:
    """Library titles still ahead of release **that this member asked for**.

    A title already on the shelf is not "upcoming" to the household that holds
    it -- the human's words, 2026-09-06: *"if we have them it shouldn't show
    them anyways unless on the wishlist for the user."* So a library row only
    qualifies when it is a favourite or a linked request of this member. The
    non-library half of the shelf lives in :func:`build_upcoming_articles`.
    """
    moment = now or _now()
    wanted = _wishlisted_game_uuids(user)
    if not wanted:
        return []
    query = (
        select(Game)
        .where(Game.uuid.in_(wanted))
        .where(Game.first_release_date.isnot(None))
        .where(Game.first_release_date > moment)
        .order_by(Game.first_release_date.asc())
        .limit(limit)
    )
    return db.session.execute(apply_game_access_filters(query, user)).scalars().all()


def _held_platforms(user) -> set[str]:
    """Platform names of the libraries this member can see."""
    query = select(Library.uuid, Library.platform)
    allowed = allowed_library_uuids(user)
    rows = db.session.execute(query).all()
    out: set[str] = set()
    for lib_uuid, platform in rows:
        if allowed is not None and lib_uuid not in allowed:
            continue
        name = getattr(platform, 'name', None) or str(platform or '')
        if name:
            out.add(name)
    return out


def build_upcoming_articles(
    user, *, limit: int = DEFAULT_SHELF_LIMIT, now: datetime | None = None,
) -> list[dict]:
    """The Upcoming shelf as article tiles: what is coming that you do not hold.

    Two sources, soonest first:

    1. :func:`build_upcoming` -- library titles this member favourited or
       requested, still ahead of release (cover, link to the title).
    2. The IGDB release cache the licensed-title report already keeps
       (``igdb_platform_releases``): titles releasing within
       ``UPCOMING_HORIZON_DAYS`` on a platform the member's libraries hold and
       whose ``igdb_game_id`` matches **no** library row. No cover -- the cache
       stores names and dates, and fetching art per tile would be an outbound
       call per Discover load. The tile links to the platform's licensed
       catalogue, which is where the household would go to request it.

    ``published_at`` carries the release date so the card shows it as the
    badge date; ``kind`` is ``upcoming`` for the badge text. Empty cache is
    "no data", not "nothing is coming" -- the row hides itself either way.
    """
    from oneirodex.utils.cover_url import resolve_game_cover_url

    moment = now or _now()
    horizon = moment + timedelta(days=UPCOMING_HORIZON_DAYS)
    articles: list[dict] = []

    for game in build_upcoming(user, limit=limit, now=moment):
        released = game.first_release_date
        articles.append({
            'kind': 'upcoming',
            'id': f'upcoming-lib-{game.uuid}',
            'title': game.name,
            'summary': 'On your wishlist',
            'image_url': resolve_game_cover_url(game),
            'href': f'/game/{game.uuid}',
            'published_at': released.isoformat() if released else None,
            'release_at': released.isoformat() if released else None,
            'platform': getattr(getattr(game, 'library', None), 'platform', None)
            and game.library.platform.name,
        })

    platforms = _held_platforms(user)
    if platforms:
        held_igdb_ids = {
            i for i in db.session.execute(
                select(Game.igdb_id).where(Game.igdb_id.isnot(None))
            ).scalars().all()
        }
        rows = db.session.execute(
            select(IgdbPlatformRelease)
            .where(IgdbPlatformRelease.library_platform.in_(sorted(platforms)))
            .where(IgdbPlatformRelease.released_at.isnot(None))
            .where(IgdbPlatformRelease.released_at > moment)
            .where(IgdbPlatformRelease.released_at <= horizon)
            .order_by(IgdbPlatformRelease.released_at.asc())
            .limit(limit * 6)
        ).scalars().all()
        seen: set[int] = set()
        for row in rows:
            if row.igdb_game_id in held_igdb_ids or row.igdb_game_id in seen:
                continue
            seen.add(row.igdb_game_id)
            when = row.released_at
            articles.append({
                'kind': 'upcoming',
                'id': f'upcoming-igdb-{row.igdb_game_id}',
                'title': row.name or f'IGDB #{row.igdb_game_id}',
                'summary': f'{row.library_platform} · not in the library yet',
                'image_url': None,
                'href': f'/systems/catalog?platform={row.library_platform}',
                'published_at': when.isoformat() if when else None,
                'release_at': when.isoformat() if when else None,
                'platform': row.library_platform,
            })

    articles.sort(key=lambda a: a.get('release_at') or '')
    return articles[:limit]


def build_storefront_shelf(identifier: str, user, *, limit: int = DEFAULT_SHELF_LIMIT) -> list[Game] | None:
    """Dispatch for the storefront seed shelves. ``None`` = not a storefront shelf."""
    if identifier == 'curated_for_you':
        return build_curated_for_you(user, limit=limit)
    if identifier == 'upcoming':
        return build_upcoming(user, limit=limit)
    return None
