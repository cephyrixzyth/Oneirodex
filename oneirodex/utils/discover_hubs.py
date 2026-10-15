"""Genre hubs — Discover assemblies that are not admin DiscoverySection rows.

A store genre page is a conversion funnel. A household hub is the same tile
atom in three honest shelves: unplayed here, newly added, loved here. Empty
shelves are omitted. The catalog remains the full list.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from sqlalchemy import func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Genre, UserGameProgress, user_favorites
from oneirodex.utils.discover_projections import serialize_discover_game
from oneirodex.utils.discover_hydrate import DiscoverHydration
from oneirodex.utils.discover_providers import ROW_WINDOW, _access_filtered


def resolve_genre(name: str):
    raw = (name or '').strip()
    if not raw:
        return None
    return db.session.execute(
        select(Genre).where(func.lower(Genre.name) == raw.lower())
    ).scalars().first()


def catalog_href_for_genre(genre) -> str:
    return f'/library?{urlencode({"genre": genre.name})}'


def hub_path_for_genre(genre) -> str:
    return f'/discover/hub/genre/{quote(genre.name, safe="")}'


def _in_genre(genre):
    return Game.genres.any(Genre.id == genre.id)


def _select_unplayed(user, genre, limit):
    played = select(UserGameProgress.game_uuid).where(
        UserGameProgress.user_id == getattr(user, 'id', None)
    )
    return _access_filtered(
        select(Game)
        .where(_in_genre(genre), ~Game.uuid.in_(played))
        .order_by(Game.rating.desc().nullslast(), Game.date_created.desc()),
        user,
        limit,
    )


def _select_newest(user, genre, limit):
    return _access_filtered(
        select(Game).where(_in_genre(genre)).order_by(Game.date_created.desc()),
        user,
        limit,
    )


def _select_loved(user, genre, limit):
    fav_counts = (
        select(
            user_favorites.c.game_uuid.label('game_uuid'),
            func.count(user_favorites.c.user_id).label('favorite_count'),
        )
        .group_by(user_favorites.c.game_uuid)
        .subquery()
    )
    return _access_filtered(
        select(Game)
        .join(fav_counts, Game.uuid == fav_counts.c.game_uuid)
        .where(_in_genre(genre))
        .order_by(fav_counts.c.favorite_count.desc(), Game.date_created.desc()),
        user,
        limit,
    )


_HUB_ROWS = (
    (
        'unplayed',
        'Unplayed here',
        'In this genre and not on your play record',
        _select_unplayed,
    ),
    (
        'newest',
        'Newly added',
        'Recently appeared in this genre',
        _select_newest,
    ),
    (
        'loved',
        'Loved here',
        'Favourited in this household',
        _select_loved,
    ),
)


def build_genre_hub(user, name: str) -> dict | None:
    """Assemble virtual Discover rows for one genre, or None if unknown."""
    genre = resolve_genre(name)
    if genre is None:
        return None

    catalog_href = catalog_href_for_genre(genre)
    hydration = DiscoverHydration(user)
    sections = []

    for key, title, reason, selector in _HUB_ROWS:
        selected = selector(user, genre, ROW_WINDOW + 1)
        if not selected:
            continue
        shipped = selected[:ROW_WINDOW]
        hydration.prime(shipped)
        sections.append(
            {
                'identifier': f'hub:genre:{genre.id}:{key}',
                'title': title,
                'reason': reason,
                'item_kind': 'games',
                'layout': 'shelf',
                'games': [
                    serialize_discover_game(
                        game,
                        hydration.cover_for(game),
                        **hydration.serializer_kwargs(game),
                    )
                    for game in shipped
                ],
                # Equal to the window so the shelf does not page a virtual row.
                'total_count': len(shipped),
                'has_more': len(selected) > ROW_WINDOW,
                'more_href': catalog_href,
            }
        )

    return {
        'genre': genre.name,
        'title': genre.name,
        'catalog_href': catalog_href,
        'sections': sections,
    }
