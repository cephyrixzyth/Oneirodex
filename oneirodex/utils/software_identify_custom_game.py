"""Custom kinded games for Stage D: mint a custom IGDB id, attach store URLs,
create / upsert the ``Game`` row, hydrate Steam content.

Split out of ``software_identify`` in the v11 cycle (H-D.4) as a pure move.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import Game, GameURL
from oneirodex.utils.item_kind import (
    DEFAULT_ITEM_KIND,
    ITEM_KINDS,
    normalize_item_kind,
)
from oneirodex.utils.software_identify_store import scrub_stage_d_payload

logger = logging.getLogger(__name__)

CUSTOM_IGDB_BASE = 2000000420


def _next_custom_igdb_id() -> int:
    highest = db.session.execute(
        select(func.max(Game.igdb_id)).filter(Game.igdb_id >= CUSTOM_IGDB_BASE)
    ).scalar()
    return CUSTOM_IGDB_BASE if highest is None else int(highest) + 1


def _attach_store_url(game, *, url_type: str, url: str | None) -> None:
    store_url = (url or '').strip()
    if not store_url or not game:
        return
    lowered = store_url.lower()
    if any(token in lowered for token in ('download', 'install', 'checkout', 'cart', 'magnet')):
        return
    already = any(
        (getattr(row, 'url_type', '') or '').lower() == url_type
        for row in (game.urls or [])
    )
    if already:
        return
    db.session.add(GameURL(
        game_uuid=game.uuid,
        url_type=url_type,
        url=store_url,
    ))


def create_custom_kinded_game(
    *,
    name: str,
    full_disk_path: str,
    library_uuid: str,
    item_kind: str = DEFAULT_ITEM_KIND,
    steam_app_id: int | None = None,
    gog_id: int | None = None,
    gog_url: str | None = None,
    epic_url: str | None = None,
    summary: str | None = None,
    cover: str | None = None,
    size: int = 0,
) -> Game:
    """
    Create a custom-range Game with item_kind (no real IGDB id).

    Used by Unmatched mark_kind, Stage D store cascade, and software identify.
    GOG / Epic identity is register-only via GameURL (no dedicated gog_id column).
    """
    kind = normalize_item_kind(item_kind)
    if kind not in ITEM_KINDS:
        kind = DEFAULT_ITEM_KIND
    custom_id = _next_custom_igdb_id()
    game = Game(
        igdb_id=custom_id,
        name=(name or '').strip() or 'Untitled',
        summary=summary,
        full_disk_path=full_disk_path,
        library_uuid=library_uuid,
        cover=cover,
        size=int(size or 0),
        steam_app_id=steam_app_id,
        item_kind=kind,
        date_created=datetime.now(timezone.utc),
        date_identified=datetime.now(timezone.utc),
        slug=f"custom-{custom_id}-{uuid4().hex[:8]}",
        path_status='ok',
    )
    if steam_app_id:
        game.steam_url = f'https://store.steampowered.com/app/{int(steam_app_id)}/'
    db.session.add(game)
    db.session.flush()
    try:
        from oneirodex.utils.rom_language import apply_rom_language_fields

        apply_rom_language_fields(game, full_disk_path or name)
    except Exception:
        pass
    if gog_id or gog_url:
        store_url = (gog_url or '').strip()
        if not store_url and gog_id:
            # Product id alone — store as typed register link without inventing a download URL.
            store_url = f'https://www.gog.com/game/{int(gog_id)}'
        _attach_store_url(game, url_type='gog', url=store_url)
    if epic_url:
        _attach_store_url(game, url_type='epic', url=epic_url)
    return game


def upsert_stage_d_custom_game(
    *,
    candidate: dict,
    full_disk_path: str,
    library_uuid: str,
    size: int = 0,
) -> Game:
    """
    Create or update a custom-range Game from a Stage D store candidate.

    Update applies only when a custom Game already exists for the same path
    (and matching store id when present). Never attaches DRM install URLs.
    """
    candidate = scrub_stage_d_payload(candidate or {})
    name = (candidate.get('name') or '').strip() or 'Untitled'
    kind = normalize_item_kind(candidate.get('item_kind'))
    steam_app_id = candidate.get('steam_app_id')
    try:
        steam_app_id = int(steam_app_id) if steam_app_id is not None else None
    except (TypeError, ValueError):
        steam_app_id = None
    gog_id = candidate.get('gog_id')
    try:
        gog_id = int(gog_id) if gog_id is not None else None
    except (TypeError, ValueError):
        gog_id = None
    summary = candidate.get('summary')
    cover = candidate.get('cover_url') or candidate.get('cover')
    gog_url = candidate.get('url') if candidate.get('source') == 'gog' else None
    epic_url = candidate.get('url') if candidate.get('source') == 'epic' else None

    existing = db.session.execute(
        select(Game).filter(
            Game.full_disk_path == full_disk_path,
            Game.library_uuid == library_uuid,
            Game.igdb_id >= CUSTOM_IGDB_BASE,
        )
    ).scalar_one_or_none()

    if existing is None and steam_app_id is not None:
        existing = db.session.execute(
            select(Game).filter(
                Game.library_uuid == library_uuid,
                Game.steam_app_id == steam_app_id,
                Game.full_disk_path == full_disk_path,
                Game.igdb_id >= CUSTOM_IGDB_BASE,
            )
        ).scalar_one_or_none()

    if existing is not None:
        existing.name = name
        if summary:
            existing.summary = summary
        if cover:
            existing.cover = cover
        existing.item_kind = kind
        existing.date_identified = datetime.now(timezone.utc)
        existing.path_status = 'ok'
        if steam_app_id:
            existing.steam_app_id = steam_app_id
            existing.steam_url = f'https://store.steampowered.com/app/{int(steam_app_id)}/'
        if gog_id or gog_url:
            store_url = (gog_url or '').strip()
            if not store_url and gog_id:
                store_url = f'https://www.gog.com/game/{int(gog_id)}'
            _attach_store_url(existing, url_type='gog', url=store_url)
        if epic_url:
            _attach_store_url(existing, url_type='epic', url=epic_url)
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(existing, full_disk_path or name)
        except Exception:
            pass
        _hydrate_steam_content(existing, steam_app_id)
        return existing

    created = create_custom_kinded_game(
        name=name,
        full_disk_path=full_disk_path,
        library_uuid=library_uuid,
        item_kind=kind,
        steam_app_id=steam_app_id,
        gog_id=gog_id,
        gog_url=gog_url,
        epic_url=epic_url,
        summary=summary,
        cover=cover,
        size=size,
    )
    _hydrate_steam_content(created, steam_app_id)
    return created


def hydrate_steam_for_game(game, steam_app_id, *, fast: bool = False) -> dict:
    """Map Steam ``appdetails`` onto ``game`` inside a SAVEPOINT; never raises.

    Returns the report from ``hydrate_game_from_steam`` (``{}`` when Steam had
    nothing or the call failed -- logged, not swallowed silently).
    """
    if not game or not steam_app_id:
        return {}
    try:
        from oneirodex import db
        from oneirodex.utils.steam_metadata import hydrate_game_from_steam

        with db.session.begin_nested():
            report = hydrate_game_from_steam(game, app_id=steam_app_id, fast=fast)
        if not report:
            logger.warning('Steam hydrate for %r (app %s) returned nothing', getattr(game, 'name', '?'), steam_app_id)
        return report or {}
    except Exception as exc:  # noqa: BLE001 -- a metadata miss must not undo an identification
        logger.warning('Steam hydrate for %r (app %s) failed: %s', getattr(game, 'name', '?'), steam_app_id, exc)
        return {}


def _hydrate_steam_content(game, steam_app_id) -> None:
    """Pull full store content (summary, genres, dev/publisher, release, modes).

    The storesearch hit that identified the title carries no description and no
    taxonomy, so without this a Stage D game lands with every box empty.

    A Steam App ID gets the direct ``appdetails`` path, which is the richest
    source we have. Everything else — a GOG-identified title, or a console ROM
    that never touched a PC store — falls through to the multi-source cascade,
    which used to be skipped entirely: this function returned early without an
    App ID, so those titles got no enrichment at all.

    Failures are swallowed on purpose — a metadata miss must not undo an
    identification.
    """
    if not game:
        return

    try:
        if steam_app_id:
            hydrate_steam_for_game(game, steam_app_id)
            # Steam answered on the fields it covers; anything still empty is
            # worth one more pass through the other sources.
            from oneirodex.utils.secondary_scrapers import missing_core_fields

            if not missing_core_fields({
                'summary': getattr(game, 'summary', None),
                'genres': list(getattr(game, 'genres', []) or []),
                'developer': getattr(game, 'developer_id', None),
            }):
                return

        from oneirodex.utils.metadata_cascade import hydrate_game_from_cascade

        # With an App ID we already pulled Steam's own appdetails above, which
        # is strictly richer than what the cascade's name search would return.
        hydrate_game_from_cascade(game, skip=('steam',) if steam_app_id else ())
    except Exception as exc:  # noqa: BLE001
        logger.warning('Content hydrate skipped for %r: %s', getattr(game, 'name', '?'), exc)
