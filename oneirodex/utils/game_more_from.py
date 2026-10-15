"""Vault shelves of other titles from the same developer or publisher.

Household presence only: ACL-filtered, finite, hidden when fewer than two
other titles exist. Not a store "more from this publisher" conversion rail.
"""

from __future__ import annotations

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game
from oneirodex.utils.discover_projections import serialize_discover_game
from oneirodex.utils.discover_hydrate import DiscoverHydration
from oneirodex.utils.library_acl import apply_game_access_filters

MORE_FROM_CAP = 12
MIN_OTHERS = 2


def _others(user, *, exclude_uuid: str, developer_id=None, publisher_id=None):
    stmt = select(Game).where(Game.uuid != exclude_uuid)
    if developer_id is not None:
        stmt = stmt.where(Game.developer_id == developer_id)
    if publisher_id is not None:
        stmt = stmt.where(Game.publisher_id == publisher_id)
    stmt = stmt.order_by(Game.rating.desc().nullslast(), Game.name.asc())
    stmt = apply_game_access_filters(stmt, user).limit(MORE_FROM_CAP)
    return list(db.session.execute(stmt).scalars().all())


def _section(identifier: str, title: str, reason: str, games, hydration: DiscoverHydration) -> dict:
    serialized = [
        serialize_discover_game(
            game,
            hydration.cover_for(game),
            **hydration.serializer_kwargs(game),
        )
        for game in games
    ]
    return {
        'identifier': identifier,
        'title': title,
        'reason': reason,
        'item_kind': 'games',
        'layout': 'shelf',
        'games': serialized,
        'total_count': len(serialized),
        'has_more': False,
        'more_href': '',
    }


def build_more_from(game, user) -> dict:
    """Assemble zero, one, or two finite shelves. Empty list is a hide, not a fail."""
    if game is None or user is None:
        return {'sections': []}

    hydration = DiscoverHydration(user)
    sections: list[dict] = []
    shown: set[str] = set()
    exclude = game.uuid
    developer = getattr(game, 'developer', None)
    publisher = getattr(game, 'publisher', None)
    developer_id = getattr(game, 'developer_id', None)
    publisher_id = getattr(game, 'publisher_id', None)

    if developer_id is not None:
        rows = _others(user, exclude_uuid=exclude, developer_id=developer_id)
        if len(rows) >= MIN_OTHERS:
            hydration.prime(rows)
            label = developer.name.strip() if developer and developer.name else 'this developer'
            sections.append(
                _section(
                    f'more_developer:{exclude}',
                    f'More from {label}',
                    'Other titles in this vault from the same developer.',
                    rows,
                    hydration,
                )
            )
            shown.update(row.uuid for row in rows)

    same_house = (
        developer_id is not None
        and publisher_id is not None
        and developer_id == publisher_id
    )
    same_name = bool(
        developer
        and publisher
        and (developer.name or '').strip().lower() == (publisher.name or '').strip().lower()
    )
    if publisher_id is not None and not same_house and not same_name:
        rows = [
            row
            for row in _others(user, exclude_uuid=exclude, publisher_id=publisher_id)
            if row.uuid not in shown
        ]
        if len(rows) >= MIN_OTHERS:
            hydration.prime(rows)
            label = publisher.name.strip() if publisher and publisher.name else 'this publisher'
            sections.append(
                _section(
                    f'more_publisher:{exclude}',
                    f'More from {label}',
                    'Other titles in this vault from the same publisher.',
                    rows,
                    hydration,
                )
            )

    return {'sections': sections}
