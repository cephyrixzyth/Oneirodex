"""Query service for the ``/browse_games`` library grid.

``routes.browse_games`` was a ~300-line view that built the ``select()``,
applied a dozen optional filters, hand-wrote the ``DISTINCT ON`` representative
pick, ran the per-page batch lookups (statuses / update counts / patch flags /
covers / favourites / edition platforms) and then serialised. This module owns
everything up to and including the batch lookups; :mod:`oneirodex.utils.browse_payload`
owns the row serialisation. The view is left with: call :func:`run_browse_query`
→ hand the result to the payload builder → ``jsonify``.

The response shape is unchanged. Early filters that can only ever return an
empty page (no installed games, no library access, an unknown platform enum, a
play-mode with no matching platforms) return :meth:`BrowseQueryResult.empty`,
which the payload builder renders as the *same* ``{games: [], total: 0,
pages: 0, current_page: N}`` body the success path produces.
"""

from __future__ import annotations

from math import ceil
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import joinedload, lazyload

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    Category,
    Game,
    GameExtra,
    GameMode,
    GameUpdate,
    Genre,
    GlobalSettings,
    Image,
    Library,
    Platform,
    PlayerPerspective,
    Theme,
    user_favorites,
    user_game_status,
)
from oneirodex.platform import LibraryPlatform, platforms_for_play_mode
from oneirodex.utils.browse_filters import apply_badge_filters, apply_filter_tree
from oneirodex.utils.browse_pagination import normalize_page_size
from oneirodex.utils.client_lifecycle import installed_game_uuids, load_lifecycle_map
from oneirodex.utils.game_editions import normalize_title
from oneirodex.utils.library_acl import apply_game_access_filters, user_can_access_library
from oneirodex.utils.lifecycle import web_client_connected
from oneirodex.utils.store_ownership import get_matched_owned_game_uuids
from oneirodex.utils.title_grouping import (
    editions_by_title_key,
    platform_rank_case,
    title_key_expr,
)


@dataclass
class BrowseQueryResult:
    """Everything the payload builder needs for one page of the browse grid.

    An "empty" result (see :meth:`empty`) carries an empty ``games`` list and
    zeroed pagination; every lookup mapping defaults empty so the payload
    builder can treat both paths identically.
    """

    page: int
    games: list = field(default_factory=list)
    total: int = 0
    pages: int = 0
    current_user_id: Any = None
    edition_platforms_by_key: dict = field(default_factory=dict)
    user_statuses: dict = field(default_factory=dict)
    update_counts: dict = field(default_factory=dict)
    patch_game_uuids: set = field(default_factory=set)
    preferred_locale: str = "en-US"
    settings: Any = None
    owned_game_uuids: set = field(default_factory=set)
    lifecycle_map: dict = field(default_factory=dict)
    client_connected: bool = False
    favorite_uuids: set = field(default_factory=set)
    covers_by_uuid: dict = field(default_factory=dict)
    # game uuid -> {slot_name, updated_at} of this member's newest state.
    resume_by_uuid: dict = field(default_factory=dict)

    @classmethod
    def empty(cls, page: int) -> "BrowseQueryResult":
        """A guaranteed-empty page — same body the old short-circuits returned."""
        return cls(page=page)


def run_browse_query(args, user) -> BrowseQueryResult:
    """Build + run the browse query for ``args`` (a ``request.args`` MultiDict).

    ``user`` is the current (authenticated) user. Returns a
    :class:`BrowseQueryResult`; callers pass it straight to
    :func:`oneirodex.utils.browse_payload.build_browse_payload`.
    """
    page = args.get("page", 1, type=int)
    per_page = normalize_page_size(args.get("per_page", 20, type=int))
    library_uuid = args.get("library_uuid")
    library_platform = args.get("library_platform")
    igdb_platform = args.get("igdb_platform")
    category = args.get("category")
    genre = args.get("genre")
    rating = args.get("rating", type=int)
    game_mode = args.get("game_mode")
    player_perspective = args.get("player_perspective")
    theme = args.get("theme")
    sort_by = args.get("sort_by", "name")
    sort_order = args.get("sort_order", "asc")
    installed_only = args.get("installed_only", "").lower() in ("1", "true", "yes")

    query = select(Game).options(
        joinedload(Game.genres),
        joinedload(Game.player_perspectives),
        joinedload(Game.library),
    )
    query = apply_game_access_filters(query, user)

    current_user_id = user.id if user.is_authenticated else None

    if installed_only:
        installed = installed_game_uuids(current_user_id)
        if not installed:
            return BrowseQueryResult.empty(page)
        query = query.filter(Game.uuid.in_(installed))
    if library_uuid:
        if not user_can_access_library(user, library_uuid):
            return BrowseQueryResult.empty(page)
        query = query.filter(Game.library_uuid == library_uuid)
    if library_platform:
        try:
            platform_enum = LibraryPlatform[library_platform]
        except KeyError:
            return BrowseQueryResult.empty(page)
        query = query.filter(Game.library.has(Library.platform == platform_enum))
    play_mode = (args.get("play_mode") or "").strip().lower()
    if play_mode in ("browser", "companion", "catalog"):
        matching = platforms_for_play_mode(play_mode)
        if not matching:
            return BrowseQueryResult.empty(page)
        query = query.filter(Game.library.has(Library.platform.in_(matching)))
    if igdb_platform:
        query = query.filter(Game.platforms.any(Platform.name == igdb_platform))
    if category:
        query = query.filter(Game.category.has(Category.name == category))
    if genre:
        query = query.filter(Game.genres.any(Genre.name == genre))
    if rating is not None:
        query = query.filter(Game.rating >= rating)
    if game_mode:
        query = query.filter(Game.game_modes.any(GameMode.name == game_mode))
    if player_perspective:
        query = query.filter(
            Game.player_perspectives.any(PlayerPerspective.name == player_perspective)
        )
    if theme:
        query = query.filter(Game.themes.any(Theme.name == theme))
    query = apply_badge_filters(query, args, user=user)
    # INSP-3: a saved filter's nested AND/OR tree, when one is in play.
    # A FilterTreeError propagates to the route, which turns it into a 400
    # naming the offending part -- a silently ignored filter would show the
    # member a full library and let them think that was the answer.
    query = apply_filter_tree(query, args, user=user)

    # One tile per title, not per row in one library.
    #
    # A household keeping Chrono Trigger on SNES, PC and Switch had three
    # unrelated tiles; the copies are reachable from the preview's "Available
    # on" list, which is where they belong. Titles pair on the normalised name
    # because `igdb_id` and `slug` are both unique per row and so cannot be
    # shared across systems — see utils/title_grouping.
    #
    # `DISTINCT ON` picks the representative inside the query, so `db.paginate`
    # still counts titles rather than rows and every page stays full. Ordering
    # is (key, recency desc, id): the copy on the latest system the title was
    # released on wins, and `id` makes the choice deterministic when two copies
    # sit on equally recent hardware.
    #
    # The whereclause is reused rather than the filters re-applied, so the
    # representative is always chosen from rows the member can actually see and
    # that match what they filtered — every filter above is a WHERE on Game
    # (the `.has()` / `.any()` ones are correlated EXISTS, not joins), so this
    # cannot drift from the query it mirrors. With a system filter active that
    # is exactly what makes the surviving copy the one on *that* system.
    platform_of_library = (
        select(Library.platform)
        .where(Library.uuid == Game.library_uuid)
        .scalar_subquery()
    )
    grouping_key = title_key_expr(Game.name)
    hardware_recency = platform_rank_case(platform_of_library)

    representatives = select(Game.id.label("id"))
    if query.whereclause is not None:
        representatives = representatives.where(query.whereclause)
    representatives = (
        representatives.distinct(grouping_key)
        .order_by(grouping_key, hardware_recency.desc(), Game.id)
        .subquery()
    )
    query = query.filter(Game.id.in_(select(representatives.c.id)))

    if sort_by == "name":
        query = query.order_by(
            Game.name.asc() if sort_order == "asc" else Game.name.desc()
        )
    elif sort_by == "rating":
        query = query.order_by(
            Game.rating.asc() if sort_order == "asc" else Game.rating.desc()
        )
    elif sort_by == "first_release_date":
        query = query.order_by(
            Game.first_release_date.asc()
            if sort_order == "asc"
            else Game.first_release_date.desc()
        )
    elif sort_by == "size":
        query = query.order_by(
            Game.size.asc() if sort_order == "asc" else Game.size.desc()
        )
    elif sort_by == "date_identified":
        query = query.order_by(
            Game.date_identified.asc()
            if sort_order == "asc"
            else Game.date_identified.desc()
        )

    games, total, pages = _native_paginate(query, page=page, per_page=per_page)

    result = BrowseQueryResult(
        page=page,
        games=games,
        total=total,
        pages=pages,
        current_user_id=current_user_id,
    )

    # Which systems each surviving title exists on — one query for the page.
    #
    # Deliberately ACL-scoped but *not* filtered by the member's current view.
    # With a system filter active the browse query can only see that system's
    # copies, and the badge has to say "NES" plus how many other systems hold
    # the title — which are exactly the rows that filter excluded. One bulk
    # lookup keyed on the same grouping expression, so a page of a thousand
    # tiles costs one round trip rather than a thousand.
    page_title_keys = sorted(
        {normalize_title(game.name) for game in games if game.name}
    )
    if page_title_keys:
        edition_query = (
            select(grouping_key.label("title_key"), Library.platform)
            .select_from(Game)
            .join(Library, Library.uuid == Game.library_uuid)
            .where(grouping_key.in_(page_title_keys))
        )
        edition_query = apply_game_access_filters(edition_query, user)
        result.edition_platforms_by_key = editions_by_title_key(
            (row[0], getattr(row[1], "name", None))
            for row in db.session.execute(edition_query).all()
        )

    game_uuids = [game.uuid for game in games]

    # Get all user statuses for games in this page (batch query for performance)
    if current_user_id and game_uuids:
        status_results = db.session.execute(
            select(user_game_status.c.game_uuid, user_game_status.c.status).where(
                and_(
                    user_game_status.c.user_id == current_user_id,
                    user_game_status.c.game_uuid.in_(game_uuids),
                )
            )
        ).all()
        result.user_statuses = {row[0]: row[1] for row in status_results}

    if game_uuids:
        update_results = db.session.execute(
            select(GameUpdate.game_uuid, func.count())
            .where(GameUpdate.game_uuid.in_(game_uuids))
            .group_by(GameUpdate.game_uuid)
        ).all()
        result.update_counts = {row[0]: row[1] for row in update_results}
        result.patch_game_uuids = {
            row[0]
            for row in db.session.execute(
                select(GameExtra.game_uuid)
                .where(
                    GameExtra.game_uuid.in_(game_uuids),
                    GameExtra.extra_kind == "translation_patch",
                )
                .distinct()
            ).all()
        }

    preferred_locale = "en-US"
    prefs = getattr(user, "preferences", None) if current_user_id else None
    if prefs is not None:
        preferred_locale = getattr(prefs, "preferred_game_locale", None) or "en-US"
    result.preferred_locale = preferred_locale

    result.settings = (
        db.session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
        )
        .scalars()
        .first()
    )
    result.owned_game_uuids = (
        get_matched_owned_game_uuids(current_user_id) if current_user_id else set()
    )
    result.lifecycle_map = load_lifecycle_map(current_user_id)
    result.client_connected = (
        web_client_connected(user_id=current_user_id) if current_user_id else False
    )

    if game_uuids:
        cover_rows = (
            db.session.execute(
                select(Image).where(
                    Image.game_uuid.in_(game_uuids),
                    Image.image_type == "cover",
                )
            )
            .scalars()
            .all()
        )
        result.covers_by_uuid = {row.game_uuid: row for row in cover_rows}
        if current_user_id:
            from oneirodex.utils.emulator_saves import latest_state_by_game

            result.resume_by_uuid = latest_state_by_game(current_user_id, game_uuids)
            result.favorite_uuids = {
                row[0]
                for row in db.session.execute(
                    select(user_favorites.c.game_uuid).where(
                        and_(
                            user_favorites.c.user_id == current_user_id,
                            user_favorites.c.game_uuid.in_(game_uuids),
                        )
                    )
                ).all()
            }

    return result


def _native_paginate(query, *, page: int, per_page: int, session=None):
    """Execute Flask-SQLAlchemy-compatible pagination without request state."""
    page = page if page and page > 0 else 1
    per_page = per_page if per_page and per_page > 0 else 20
    per_page = min(per_page, 1000)
    session = session or db.session
    count_query = query.options(lazyload("*")).order_by(None).subquery()
    total = session.execute(
        select(func.count()).select_from(count_query)
    ).scalar() or 0
    items = session.execute(
        query.limit(per_page).offset((page - 1) * per_page)
    ).unique().scalars().all()
    return items, total, ceil(total / per_page) if total else 0
