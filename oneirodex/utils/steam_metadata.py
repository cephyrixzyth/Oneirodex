"""Map Steam store details onto our own Game content fields.

Why this exists
---------------
Stage D (the IGDB-miss store fallback) used to persist only ``name``,
``summary``, ``cover`` and ``steam_app_id``. Two gaps followed:

* the Steam **storesearch** endpoint returns no description at all, so the
  candidate carried ``summary=None`` and the field stayed blank; and
* genres, developer, publisher, release date, game modes and player
  perspectives were never fetched, so a Steam-identified game arrived with
  none of its boxes ticked.

This module closes both: one ``appdetails`` fetch, mapped onto every Game
column and taxonomy relation we actually own.

Fill-don't-clobber
------------------
Everything here only fills fields that are **empty**, and unions taxonomy
rather than replacing it. A better IGDB match must never be downgraded by a
later Steam pass, and re-running a backfill must be safe.
"""

from __future__ import annotations

from datetime import datetime, timezone

from oneirodex import db
from oneirodex.models import Developer, GameMode, Genre, PlayerPerspective, Publisher
from oneirodex.utils.secondary_scrapers import (
    categories_indicate_vr,
    steam_game_mode_names,
    steam_perspective_names,
)
from oneirodex.utils.steam_lookup import fetch_steam_app_details
from oneirodex.utils.steam_store_specs import merge_store_specs, store_specs_from_steam_details

# Steam prints dates as "12 Nov, 2020", "Nov 12, 2020" or just "2020".
_DATE_FORMATS = ('%d %b, %Y', '%b %d, %Y', '%d %B, %Y', '%B %d, %Y', '%Y')


def parse_steam_release_date(raw: str | None) -> datetime | None:
    """Best-effort parse; unknown/'Coming soon' shapes return None rather than guess."""
    text = (raw or '').strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def steam_details_to_metadata(details: dict | None) -> dict:
    """Normalize a raw ``fetch_steam_app_details`` payload into our field names."""
    if not details:
        return {}
    categories = details.get('categories') or []
    return {
        'steam_app_id': details.get('steam_app_id'),
        'name': details.get('name'),
        'summary': details.get('short_description'),
        'cover_url': details.get('header_image'),
        'genres': details.get('genres') or [],
        'developer': (details.get('developers') or [None])[0],
        'publisher': (details.get('publishers') or [None])[0],
        'first_release_date': parse_steam_release_date(details.get('release_date')),
        'game_modes': steam_game_mode_names(categories),
        'player_perspectives': steam_perspective_names(categories),
        'is_vr': categories_indicate_vr(categories),
        'metacritic': details.get('metacritic'),
        'store_specs': store_specs_from_steam_details(details),
    }


def _get_or_create(model, name: str):
    label = (name or '').strip()
    if not label:
        return None
    existing = db.session.execute(
        db.select(model).filter_by(name=label)
    ).scalars().first()
    if existing:
        return existing
    row = model(name=label)
    db.session.add(row)
    db.session.flush()
    return row


def _union_relation(game, attr: str, model, names) -> list[str]:
    """Attach any names not already linked. Returns what was newly added."""
    current = getattr(game, attr, None)
    if current is None:
        return []
    existing = {(getattr(x, 'name', '') or '').strip().lower() for x in current}
    added: list[str] = []
    for name in names or []:
        label = (name or '').strip()
        if not label or label.lower() in existing:
            continue
        row = _get_or_create(model, label)
        if row is None:
            continue
        current.append(row)
        existing.add(label.lower())
        added.append(label)
    return added


def apply_steam_metadata_to_game(game, metadata: dict) -> dict:
    """Fill empty Game fields and union taxonomy from normalized Steam metadata.

    Returns a report of what changed, so scan logs stay honest about whether a
    title actually gained metadata or was already complete.
    """
    report = {
        'summary': False,
        'cover': False,
        'release_date': False,
        'developer': False,
        'publisher': False,
        'genres': [],
        'game_modes': [],
        'player_perspectives': [],
        'steam_app_id': False,
        'store_specs': False,
    }
    if not game or not metadata:
        return report

    if not (game.summary or '').strip() and (metadata.get('summary') or '').strip():
        game.summary = metadata['summary'].strip()
        report['summary'] = True

    if not (getattr(game, 'cover', None) or '') and metadata.get('cover_url'):
        game.cover = metadata['cover_url']
        report['cover'] = True

    if getattr(game, 'first_release_date', None) is None and metadata.get('first_release_date'):
        game.first_release_date = metadata['first_release_date']
        report['release_date'] = True

    if getattr(game, 'developer_id', None) is None and metadata.get('developer'):
        developer = _get_or_create(Developer, metadata['developer'])
        if developer is not None:
            game.developer_id = developer.id
            report['developer'] = True

    if getattr(game, 'publisher_id', None) is None and metadata.get('publisher'):
        publisher = _get_or_create(Publisher, metadata['publisher'])
        if publisher is not None:
            game.publisher_id = publisher.id
            report['publisher'] = True

    if getattr(game, 'steam_app_id', None) is None and metadata.get('steam_app_id'):
        game.steam_app_id = metadata['steam_app_id']
        game.steam_url = f"https://store.steampowered.com/app/{metadata['steam_app_id']}/"
        report['steam_app_id'] = True

    report['genres'] = _union_relation(game, 'genres', Genre, metadata.get('genres'))
    report['game_modes'] = _union_relation(game, 'game_modes', GameMode, metadata.get('game_modes'))
    report['player_perspectives'] = _union_relation(
        game, 'player_perspectives', PlayerPerspective, metadata.get('player_perspectives')
    )

    incoming_specs = metadata.get('store_specs')
    if incoming_specs:
        merged = merge_store_specs(getattr(game, 'store_specs', None), incoming_specs)
        if merged and merged != getattr(game, 'store_specs', None):
            game.store_specs = merged
            report['store_specs'] = True

    return report


def hydrate_game_from_steam(game, *, app_id: int | None = None, fast: bool = False) -> dict:
    """Fetch ``appdetails`` for the game's Steam App ID and map it on.

    No-ops (empty report) when there is no App ID or the store lookup fails —
    identification is never undone by a metadata miss.
    """
    resolved = app_id or getattr(game, 'steam_app_id', None)
    try:
        resolved = int(resolved) if resolved is not None else None
    except (TypeError, ValueError):
        resolved = None
    if not resolved:
        return {}

    details = fetch_steam_app_details(resolved, fast=True) if fast else fetch_steam_app_details(resolved)
    if not details:
        return {}
    return apply_steam_metadata_to_game(game, steam_details_to_metadata(details))
