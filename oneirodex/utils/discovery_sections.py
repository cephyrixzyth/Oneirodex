"""Framework-neutral discovery shelf projections shared by route adapters."""
from __future__ import annotations

from datetime import datetime, timezone


def discovery_sections_data():
    from sqlalchemy import func, select

    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import DiscoverySection, Game, Genre, Library, user_favorites
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.discovery_shelves import (
        count_custom_shelf_games, describe_shelf_config,
    )

    sections = db.session.execute(
        select(DiscoverySection).order_by(DiscoverySection.display_order)
    ).scalars().all()
    section_counts = {}
    shelf_descriptions = {}
    for section in sections:
        if section.identifier == 'libraries':
            count = db.session.execute(select(func.count(Library.uuid))).scalar()
        elif section.identifier == 'latest_games':
            count = db.session.execute(
                select(func.count(Game.id)).where(Game.first_release_date.is_not(None))
            ).scalar()
        elif section.identifier == 'new_library_games':
            count = db.session.execute(select(func.count(Game.id))).scalar()
        elif section.identifier == 'most_downloaded':
            count = db.session.execute(
                select(func.count(Game.id)).where(Game.times_downloaded > 0)
            ).scalar()
        elif section.identifier == 'highest_rated':
            count = db.session.execute(
                select(func.count(Game.id)).where(Game.rating.is_not(None))
            ).scalar()
        elif section.identifier == 'last_updated':
            count = db.session.execute(
                select(func.count(Game.id)).where(Game.last_updated.is_not(None))
            ).scalar()
        elif section.identifier == 'most_favorited':
            count = db.session.execute(
                select(func.count(func.distinct(Game.uuid)))
                .join(user_favorites, Game.uuid == user_favorites.c.game_uuid)
            ).scalar()
        elif section.section_type == 'custom':
            count = count_custom_shelf_games(section.config)
            shelf_descriptions[section.id] = describe_shelf_config(section.config)
        else:
            count = 0
        section_counts[section.identifier] = count

    libraries = db.session.execute(select(Library).order_by(Library.name)).scalars().all()
    genres = db.session.execute(select(Genre).order_by(Genre.name)).scalars().all()
    return {
        'sections': sections, 'section_counts': section_counts,
        'shelf_descriptions': shelf_descriptions, 'libraries': libraries,
        'genres': genres, 'platforms': list(LibraryPlatform),
    }


def discovery_section_public(section, data):
    config = section.config or {}
    return {
        'id': section.id,
        'name': section.name,
        'identifier': section.identifier,
        'section_type': section.section_type,
        'is_visible': bool(section.is_visible),
        'display_order': section.display_order,
        'count': data['section_counts'].get(section.identifier, 0),
        'description': data['shelf_descriptions'].get(section.id, ''),
        'config': {
            key: config[key]
            for key in ('mode', 'game_uuids', 'filter_type', 'filter_value')
            if key in config
        },
        'layout': section.layout or 'shelf',
        'starts_at': _timestamp(section.starts_at),
        'ends_at': _timestamp(section.ends_at),
        'pin_rank': section.pin_rank,
        'is_live': section.is_live(),
    }


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _timestamp(value):
    return utc_naive(value).isoformat() + 'Z' if value else None
