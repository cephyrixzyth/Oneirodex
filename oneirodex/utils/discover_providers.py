"""The Discover row registry.

Every shelf on Discover used to be a branch in one ``if/elif`` chain inside
``build_discover_sections``, which meant the feed had no stage that could see all
its rows at once — so capping the feed, deduping titles across rows, or letting a
member pin one were not merely unimplemented, they were inexpressible.

A row is now a :class:`RowSpec` plus a selector: a callable that takes a member
and a limit and returns ``Game`` rows. Selectors do not serialize, do not know
about other rows, and do not decide whether they will be displayed. That last
part is what later phases need — the feed can drop, reorder, or thin a row
without the row's own code participating.

The fields on ``RowSpec`` beyond ``identifier`` are carried now and consumed
later: ``family`` and ``priority`` feed the slot budget, ``dedupe_mode`` and
``min_fill`` feed cross-row dedupe. They are declared here so a row added in the
meantime already answers the questions those stages will ask.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from sqlalchemy import func, or_, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    Announcement,
    DiscoverySection,
    FreeGameOffer,
    Game,
    GameExtra,
    GameUpdate,
    UserFriendship,
    UserGameProgress,
    UserPreference,
    user_favorites,
)
from oneirodex.utils.discovery_shelves import resolve_custom_shelf_games
from oneirodex.utils.library_acl import apply_game_access_filters
from oneirodex.utils.free_games import steam_image_fallback_url
from oneirodex.utils.storefront import build_storefront_shelf

#: Tiles shipped with the feed. The rest of a row arrives when it is scrolled —
#: the constraint is payload size, not query count, since hydration batches.
ROW_WINDOW = 12

#: The most tiles a row will ever hold. A ceiling, not a quota: a row shows what
#: it honestly has, and the "see all" tile appears only when there is genuinely
#: more than this.
ROW_MAX = 40

logger = logging.getLogger(__name__)

Selector = Callable[[object, int], Iterable[Game]]


@dataclass(frozen=True)
class RowSpec:
    """What a row is, independent of whether it gets shown."""

    identifier: str
    #: Which card component renders an item: games | updates | articles.
    item_kind: str = 'games'
    #: Diversity grouping for the slot budget — personal | chart | genre |
    #: editorial | ml. Keeps one family from flooding the feed.
    family: str = 'chart'
    #: ``pool`` takes part in cross-row dedupe; ``exempt`` neither filters nor
    #: contributes, which is how "continue playing" keeps showing what you play.
    dedupe_mode: str = 'pool'
    #: Below this many items *left by dedupe* the row is dropped rather than
    #: shown thin. A row that was always this short is kept — see
    #: `oneirodex/utils/discover_feed.py`, which is the only reader.
    min_fill: int = 4
    #: Rank for the unreserved slots.
    priority: float = 0.0
    #: Human sentence for the row subtitle. Required for anything ranked, so an
    #: algorithmic row can always say why it is there.
    reason: Optional[str] = None
    #: Drop the row entirely when it has nothing, rather than rendering a
    #: heading over empty space.
    #:
    #: Default True, because a row the *system* generates has no claim on the
    #: page beyond the titles it found: "Friends playing" with no friends and
    #: "Continue playing" with no progress are not informative, they are twelve
    #: headings pretending to be a feed. Only four identifiers used to get this
    #: treatment, hard-coded as ``STOREFRONT_SHELF_IDS`` in routes_discover.py.
    #:
    #: A shelf a person curated sets this False — see ``resolve_section``. An
    #: admin who builds a zone and watches it vanish has been overruled by the
    #: feed, and the fix for an empty curated zone is to tell them it is empty,
    #: not to hide it.
    hide_when_empty: bool = True


@dataclass(frozen=True)
class ResolvedRow:
    """A spec bound to the section that configures it and its selector."""

    spec: RowSpec
    section: DiscoverySection
    selector: Selector
    #: Query string for the Library page when the row is expressible as a
    #: library filter, else None — meaning the generic row page.
    library_filter: Optional[dict] = None

    @property
    def identifier(self) -> str:
        return self.spec.identifier

    @property
    def title(self) -> str:
        return self.section.name

    def select(self, user, limit: int) -> list[Game]:
        games = self.selector(user, limit)
        if hasattr(games, 'all'):
            games = games.all()
        return [game[0] if isinstance(game, tuple) else game for game in games]


_REGISTRY: dict[str, tuple[RowSpec, Selector]] = {}


def register(spec: RowSpec, selector: Selector) -> None:
    _REGISTRY[spec.identifier] = (spec, selector)


def registered_identifiers() -> frozenset[str]:
    return frozenset(_REGISTRY)


# ---------------------------------------------------------------------------
# seed selectors
# ---------------------------------------------------------------------------


def _access_filtered(query, user, limit: int) -> list[Game]:
    return db.session.execute(
        apply_game_access_filters(query.limit(limit), user)
    ).scalars().all()


def _latest_games(user, limit):
    """Newest *to the world*, not newest to this install.

    This ordered by `date_created` — the moment a scan first wrote the row — so
    "Latest Games" was a list of whatever was imported most recently, and a
    fresh install led with a thirty-year-old cartridge under a heading that
    promises new releases.

    Future dates are excluded rather than sorted to the top: an unreleased title
    is the Upcoming row's subject, and letting it lead this one makes both rows
    open with the same game. Naive UTC, because `first_release_date` is
    TIMESTAMP WITHOUT TIME ZONE and Postgres will not compare that against an
    aware value.

    The question the old ordering answered is still worth asking, and it has its
    own row now — see `_new_library_games`.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return _access_filtered(
        select(Game)
        .filter(Game.first_release_date.isnot(None), Game.first_release_date <= now)
        .order_by(Game.first_release_date.desc()),
        user,
        limit,
    )


def _new_library_games(user, limit):
    """What "Latest Games" used to mean: newest row in *this* library."""
    return _access_filtered(
        select(Game).order_by(Game.date_created.desc()), user, limit
    )


def _most_downloaded(user, limit):
    return _access_filtered(
        select(Game)
        .filter(Game.times_downloaded > 0)
        .order_by(Game.times_downloaded.desc()),
        user,
        limit,
    )


def _highest_rated(user, limit):
    return _access_filtered(
        select(Game).filter(Game.rating.isnot(None)).order_by(Game.rating.desc()),
        user,
        limit,
    )


def _last_updated(user, limit):
    return _access_filtered(
        select(Game)
        .filter(Game.last_updated.isnot(None))
        .order_by(Game.last_updated.desc()),
        user,
        limit,
    )


def _most_favorited(user, limit):
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
        .order_by(fav_counts.c.favorite_count.desc()),
        user,
        limit,
    )


# ---------------------------------------------------------------------------
# personal selectors
# ---------------------------------------------------------------------------


def _continue_playing(user, limit):
    """What the member actually has on the go, most recent first."""
    return _access_filtered(
        select(Game)
        .join(UserGameProgress, UserGameProgress.game_uuid == Game.uuid)
        .where(
            UserGameProgress.user_id == user.id,
            UserGameProgress.last_played_at.isnot(None),
        )
        .order_by(UserGameProgress.last_played_at.desc()),
        user,
        limit,
    )


def _sharing_friend_ids(user_id) -> list[int]:
    """Accepted friends who have not switched activity sharing off.

    A friendship is stored as one row for the direction it was requested in, so
    an accepted one turns up under either column depending on who asked.

    Sharing defaults on, and a member with no preferences row at all has not
    opted out — so absence counts as sharing, and only an explicit ``False`` is
    treated as a refusal.
    """
    sent = select(UserFriendship.friend_user_id).where(
        UserFriendship.user_id == user_id,
        UserFriendship.status == 'accepted',
    )
    received = select(UserFriendship.user_id).where(
        UserFriendship.friend_user_id == user_id,
        UserFriendship.status == 'accepted',
    )
    friend_ids = {row[0] for row in db.session.execute(sent).all()}
    friend_ids.update(row[0] for row in db.session.execute(received).all())
    if not friend_ids:
        return []

    opted_out = {
        row[0]
        for row in db.session.execute(
            select(UserPreference.user_id).where(
                UserPreference.user_id.in_(friend_ids),
                UserPreference.share_activity.is_(False),
            )
        ).all()
    }
    return sorted(friend_ids - opted_out)


def _friends_playing(user, limit):
    """Titles the member's friends have been playing, most recent first.

    Grouped by game before ordering: two friends on the same title is one tile,
    dated by whichever of them played it last, rather than the same tile twice.
    """
    friend_ids = _sharing_friend_ids(user.id)
    if not friend_ids:
        return []

    recent = (
        select(
            UserGameProgress.game_uuid.label('game_uuid'),
            func.max(UserGameProgress.last_played_at).label('played_at'),
        )
        .where(
            UserGameProgress.user_id.in_(friend_ids),
            UserGameProgress.last_played_at.isnot(None),
        )
        .group_by(UserGameProgress.game_uuid)
        .subquery()
    )
    return _access_filtered(
        select(Game)
        .join(recent, Game.uuid == recent.c.game_uuid)
        .order_by(recent.c.played_at.desc()),
        user,
        limit,
    )


#: How many engaged titles we will inspect for missing extras. A full-vault
#: ``os.path.exists`` walk is the thing this shelf must not do.
EXTRAS_MISSING_ENGAGED_CAP = 80


def _extra_file_present(extra) -> bool:
    path = getattr(extra, 'file_path', None) or ''
    if not path:
        return False
    try:
        return os.path.exists(path)
    except OSError:
        return False


def _engaged_game_uuids(user, cap: int = EXTRAS_MISSING_ENGAGED_CAP) -> list[str]:
    user_id = getattr(user, 'id', None)
    if user_id is None:
        return []
    played = db.session.execute(
        select(UserGameProgress.game_uuid)
        .where(UserGameProgress.user_id == user_id)
        .order_by(UserGameProgress.last_played_at.desc().nullslast())
        .limit(cap)
    ).scalars().all()
    fav = db.session.execute(
        select(user_favorites.c.game_uuid)
        .where(user_favorites.c.user_id == user_id)
        .limit(cap)
    ).scalars().all()
    seen: list[str] = []
    for uuid in list(played) + list(fav):
        if uuid in seen:
            continue
        seen.append(uuid)
        if len(seen) >= cap:
            break
    return seen


def _extras_missing(user, limit):
    """Engaged titles whose catalogued extras are not on the vault.

    Disc siblings are the multi-disc set, not extras to acquire. Unplayed and
    unfavourited titles are skipped so a long scan never stats the whole box.
    """
    engaged = _engaged_game_uuids(user)
    if not engaged:
        return []

    extras = db.session.execute(
        select(GameExtra).where(
            GameExtra.game_uuid.in_(engaged),
            or_(GameExtra.extra_kind.is_(None), GameExtra.extra_kind != 'disc'),
        )
    ).scalars().all()

    missing: list[str] = []
    seen: set[str] = set()
    for extra in extras:
        uuid = extra.game_uuid
        if uuid in seen:
            continue
        if _extra_file_present(extra):
            continue
        seen.add(uuid)
        missing.append(uuid)
        if len(missing) >= limit:
            break

    if not missing:
        return []

    order = {uuid: index for index, uuid in enumerate(engaged)}
    games = _access_filtered(
        select(Game).where(Game.uuid.in_(missing)), user, limit
    )
    games.sort(key=lambda game: order.get(game.uuid, len(order)))
    return games


def _game_updates(user, limit):
    """Titles whose update files landed recently.

    Distinct from the ``last_updated`` shelf, which reads ``Game.last_updated``
    — a metadata timestamp. This row is about actual update files on disk.
    """
    recent = (
        select(
            GameUpdate.game_uuid.label('game_uuid'),
            func.max(GameUpdate.created_at).label('updated_at'),
        )
        .group_by(GameUpdate.game_uuid)
        .subquery()
    )
    return _access_filtered(
        select(Game)
        .join(recent, Game.uuid == recent.c.game_uuid)
        .order_by(recent.c.updated_at.desc()),
        user,
        limit,
    )


def _news_items(user, limit):
    """Announcements and live free-game offers, newest first.

    Returns article payloads rather than ``Game`` rows — this row is the reason
    ``RowSpec.item_kind`` exists. None of it needs hydration, so it reaches the
    client as selected.
    """
    articles = []

    announcements = db.session.execute(
        select(Announcement)
        .where(Announcement.published.is_(True))
        .order_by(Announcement.created_at.desc())
        .limit(limit)
    ).scalars().all()
    for row in announcements:
        body = row.body or ''
        articles.append({
            'kind': 'announcement',
            'id': f'announcement-{row.id}',
            'title': row.title,
            'summary': body[:280],
            'image_url': None,
            'href': '/news',
            'published_at': row.created_at.isoformat() if row.created_at else None,
        })

    now = datetime.now(timezone.utc)
    offers = db.session.execute(
        select(FreeGameOffer)
        .where(FreeGameOffer.active.is_(True))
        .order_by(FreeGameOffer.last_seen_at.desc())
        .limit(limit)
    ).scalars().all()
    for row in offers:
        ends = row.ends_at
        if ends is not None and ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        # An expired giveaway on a "free now" row is worse than a shorter row.
        if ends is not None and ends < now:
            continue
        articles.append({
            'kind': 'free_game',
            'id': f'free-{row.id}',
            'title': row.title,
            'summary': row.description or '',
            'image_url': row.image_url,
            'image_fallback_url': steam_image_fallback_url(row.image_url),
            'href': '/news#free-games',
            'store': row.store,
            'published_at': row.last_seen_at.isoformat() if row.last_seen_at else None,
        })

    articles.sort(key=lambda item: item.get('published_at') or '', reverse=True)
    return articles[:limit]


register(
    RowSpec(
        'continue_playing',
        family='personal',
        # Exempt from cross-row dedupe: what the member is actually playing
        # belongs here whether or not it also appears somewhere else.
        dedupe_mode='exempt',
        priority=1.0,
        reason='Pick up where you left off',
    ),
    _continue_playing,
)
register(
    RowSpec(
        'friends_playing',
        family='personal',
        dedupe_mode='exempt',
        priority=0.95,
        reason='Popular with people you know',
    ),
    _friends_playing,
)
register(
    RowSpec(
        'game_updates',
        family='personal',
        priority=0.9,
        reason='New update files landed',
    ),
    _game_updates,
)
register(
    RowSpec(
        'extras_missing',
        family='personal',
        priority=0.88,
        reason='Extras for games you play that are not on the vault',
    ),
    _extras_missing,
)
register(
    RowSpec(
        'news',
        item_kind='articles',
        family='editorial',
        priority=0.85,
        reason='From the server and the stores',
    ),
    _news_items,
)


def _store_deals(user, limit):
    """Deep discounts across Steam / GOG / Humble / Epic (CheapShark).

    Articles only — HTTPS store redirects, never checkout or Game prices.
    """
    from oneirodex.utils.store_deals import list_deep_discount_articles

    return list_deep_discount_articles(user, limit=limit)


def _upcoming(user, limit):
    """What is coming that the household does not hold (plus wishlisted titles).

    Was the generic storefront selector, which listed *library* games with a
    future date -- titles the household already has, which is not what
    "upcoming" means to a person (human, 2026-09-06). Article tiles so the
    IGDB half (no cover, not in the library) can sit beside wishlisted library
    titles, each with its release date as the badge date.
    """
    from oneirodex.utils.storefront import build_upcoming_articles

    return build_upcoming_articles(user, limit=limit)


register(
    RowSpec(
        'upcoming',
        item_kind='articles',
        family='editorial',
        priority=0.7,
        reason='Releasing soon on systems you hold, or on your wishlist',
        min_fill=1,
    ),
    _upcoming,
)


register(
    RowSpec(
        'store_deals',
        item_kind='articles',
        family='editorial',
        priority=0.82,
        reason='Steep discounts on stores you claim in the browser',
        min_fill=1,
    ),
    _store_deals,
)


register(RowSpec('latest_games', family='chart', priority=0.5), _latest_games)
register(
    RowSpec('new_library_games', family='chart', priority=0.45),
    _new_library_games,
)
register(RowSpec('most_downloaded', family='chart', priority=0.4), _most_downloaded)
register(RowSpec('highest_rated', family='chart', priority=0.4), _highest_rated)
register(RowSpec('last_updated', family='chart', priority=0.3), _last_updated)
register(RowSpec('most_favorited', family='chart', priority=0.3), _most_favorited)


# ---------------------------------------------------------------------------
# section-backed rows
# ---------------------------------------------------------------------------

#: Custom zone filters the Library page can express in its URL. ``library`` is
#: deliberately absent — the Library page has no library-scoped filter, so a
#: library zone goes to the generic row page rather than to a link that would
#: quietly show everything.
_LIBRARY_FILTER_PARAM = {
    'genre': 'genre',
    'platform': 'library_platform',
}


def _library_filter_for(section: DiscoverySection) -> Optional[dict]:
    config = getattr(section, 'config', None) or {}
    if str(config.get('mode') or '').lower() != 'filter':
        return None
    param = _LIBRARY_FILTER_PARAM.get(str(config.get('filter_type') or '').lower())
    value = config.get('filter_value')
    if not param or not value:
        return None
    return {param: str(value)}


def _custom_zone_selector(section: DiscoverySection) -> Selector:
    def select_zone(user, limit):
        return resolve_custom_shelf_games(section.config, user, limit=limit)

    return select_zone


def _curated_for_you_selector() -> Selector:
    """Unplayed titles ranked against the member's stored taste profile.

    Supersedes the genre-affinity draft this shelf shipped with: same intent,
    but scored across genre, theme, perspective and developer, weighted by how
    much intent each signal carried and damped by what the member has already
    been shown and ignored.

    Falls back to the original storefront query when there is no profile yet —
    a fresh account has given no signal, and a ranking built on nothing is worse
    than the simple answer.
    """

    def select_curated(user, limit):
        from oneirodex.utils.discover_ml.scoring import already_engaged, rank_candidates

        profile_rows = db.session.execute(
            apply_game_access_filters(
                select(Game).where(Game.rating.isnot(None)).limit(limit * 10),
                user,
            )
        ).scalars().all()
        if not profile_rows:
            return build_storefront_shelf('curated_for_you', user, limit=limit) or []

        engaged = already_engaged(user.id)
        # A "for you" row showing what you already play is a mirror, not a
        # recommendation.
        candidates = [game for game in profile_rows if game.uuid not in engaged]
        ranked = rank_candidates(user.id, candidates, limit=limit)
        if ranked:
            return ranked
        return build_storefront_shelf('curated_for_you', user, limit=limit) or []

    return select_curated


def _storefront_selector(identifier: str) -> Selector:
    def select_shelf(user, limit):
        return build_storefront_shelf(identifier, user, limit=limit) or []

    return select_shelf


# ---------------------------------------------------------------------------
# generated rows
# ---------------------------------------------------------------------------

#: Prefix for the rows the recommender generates, one per anchor title.
BECAUSE_YOU_PLAYED = 'because_you_played'

#: How many anchor rows a feed will generate. Kept at or below the diversity cap
#: in `discover_feed`, so the recommender competes for the tail rather than
#: flooding it.
MAX_GENERATED_ROWS = 3


def _because_you_played_selector(anchor_uuid: str) -> Selector:
    def select_neighbours(user, limit):
        from oneirodex.utils.discover_ml.similarity import neighbours_of

        scored = neighbours_of(anchor_uuid, limit=limit * 2)
        if not scored:
            return []
        order = {uuid: rank for rank, (uuid, _score) in enumerate(scored)}
        games = db.session.execute(
            apply_game_access_filters(
                select(Game).where(Game.uuid.in_(list(order))), user
            )
        ).scalars().all()
        # Access filtering does not preserve the neighbour ranking, so it is
        # reapplied here rather than handing back rows in database order.
        games.sort(key=lambda game: order.get(game.uuid, len(order)))
        return games[:limit]

    return select_neighbours


def generated_rows(user, parent: DiscoverySection) -> list[ResolvedRow]:
    """Recommender rows, one per title the member has really played.

    They hang off a single ``because_you_played`` section, which is what an
    admin hides to switch the whole set off. Generating rows without a section
    of their own would put them outside the visibility control the admin screen
    presents as authoritative.
    """
    from oneirodex.utils.discover_ml.scoring import top_anchors

    user_id = getattr(user, 'id', None)
    if user_id is None:
        return []

    rows: list[ResolvedRow] = []
    for anchor in top_anchors(user_id, limit=MAX_GENERATED_ROWS):
        rows.append(
            ResolvedRow(
                spec=RowSpec(
                    f'{BECAUSE_YOU_PLAYED}:{anchor.uuid}',
                    family='ml',
                    priority=0.7,
                    reason=f'Because you played {anchor.name}',
                ),
                section=parent,
                selector=_because_you_played_selector(anchor.uuid),
            )
        )
    return rows


def _generated_parent(identifier: str) -> Optional[DiscoverySection]:
    """The section that switches a generated row's whole family on or off."""
    base = identifier.split(':', 1)[0]
    if base != BECAUSE_YOU_PLAYED:
        return None
    section = db.session.execute(
        select(DiscoverySection).filter_by(identifier=BECAUSE_YOU_PLAYED)
    ).scalar_one_or_none()
    if section is None or not section.is_live():
        return None
    return section


def resolve_section(section: DiscoverySection) -> Optional[ResolvedRow]:
    """Bind a configured shelf to the selector that fills it.

    Returns None for a section this feed does not render — today only the
    ``libraries`` shelf, which carries no games.
    """
    identifier = section.identifier
    if identifier == 'libraries':
        return None
    if identifier == BECAUSE_YOU_PLAYED:
        # A template, not a row. It carries the visibility switch for the rows
        # the recommender generates and renders nothing on its own.
        return None

    registered = _REGISTRY.get(identifier)
    if registered is not None:
        spec, selector = registered
        return ResolvedRow(spec=spec, section=section, selector=selector)

    if section.section_type == 'custom':
        # A person built this one. It stays on the page even when empty, so the
        # admin who curated it can see that it is empty.
        return ResolvedRow(
            spec=RowSpec(
                identifier,
                family='editorial',
                priority=0.6,
                hide_when_empty=False,
            ),
            section=section,
            selector=_custom_zone_selector(section),
            library_filter=_library_filter_for(section),
        )

    if identifier == 'curated_for_you':
        return ResolvedRow(
            spec=RowSpec(
                identifier,
                family='ml',
                priority=0.75,
                reason='Picked from what you play',
            ),
            section=section,
            selector=_curated_for_you_selector(),
        )

    return ResolvedRow(
        spec=RowSpec(identifier, family='editorial', priority=0.6),
        section=section,
        selector=_storefront_selector(identifier),
    )


def live_sections() -> list[DiscoverySection]:
    """Visible shelves that are inside their schedule window, in display order."""
    return [
        section
        for section in db.session.execute(
            select(DiscoverySection)
            .filter_by(is_visible=True)
            .order_by(DiscoverySection.display_order)
        ).scalars().all()
        if section.is_live()
    ]


def resolve_feed(user) -> list[ResolvedRow]:
    """Every row the feed will consider, in configured order.

    Generated rows are appended after the configured ones, so they compete for
    the tail of the page rather than displacing anything an admin arranged.
    """
    rows = []
    generated_parent = None
    for section in live_sections():
        if section.identifier == BECAUSE_YOU_PLAYED:
            generated_parent = section
            continue
        resolved = resolve_section(section)
        if resolved is not None:
            rows.append(resolved)

    if generated_parent is not None:
        try:
            rows.extend(generated_rows(user, generated_parent))
        except Exception:  # noqa: BLE001 — a feed without them is still a feed
            # Logged, not swallowed. A recommender that quietly produces nothing
            # looks identical to a member with no history, so a bug here could
            # sit undetected for as long as it took to notice the rows missing.
            logger.exception('Discover: generated rows failed; serving without them')
    return rows


def resolve_identifier(identifier: str) -> Optional[ResolvedRow]:
    """Look up one row by identifier, for the row endpoint and row page.

    Resolution goes through ``DiscoverySection`` rather than the registry alone,
    so a row that is hidden or outside its schedule window is unreachable by
    direct URL too — otherwise the row endpoint would be a way around the
    visibility toggle the admin screen presents as authoritative.
    """
    parent = _generated_parent(identifier)
    if parent is not None:
        anchor_uuid = identifier.split(':', 1)[1] if ':' in identifier else ''
        if not anchor_uuid:
            return None
        anchor = db.session.execute(
            select(Game).filter_by(uuid=anchor_uuid)
        ).scalar_one_or_none()
        if anchor is None:
            return None
        return ResolvedRow(
            spec=RowSpec(
                identifier,
                family='ml',
                priority=0.7,
                reason=f'Because you played {anchor.name}',
            ),
            section=parent,
            selector=_because_you_played_selector(anchor_uuid),
        )

    section = db.session.execute(
        select(DiscoverySection).filter_by(identifier=identifier)
    ).scalar_one_or_none()
    if section is None or not section.is_live():
        return None
    return resolve_section(section)
