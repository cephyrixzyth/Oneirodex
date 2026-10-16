"""Where else in the library the same title exists, and how to launch each one.

A member browsing a grid sees one tile per *row in one library*, so a household
that keeps Chrono Trigger as both a SNES ROM and a PC release shows two
unrelated tiles and the preview for either one implies it is the only copy.
This is the join that was missing: given a game, the same title anywhere the
member can see, grouped by system, each carrying its own play options.

Matching is by normalised title, deliberately, and it is worth saying why the
obvious key does not work: ``Game.igdb_id`` and ``Game.slug`` are both
``unique=True``, so a cross-platform pair *cannot* share either — the second
copy is a different row with a different (or absent) IGDB id. Title is what
those rows actually have in common.

Normalisation is the same shape as ``patch_catalog.local_yaml.normalize_title``
(casefold, collapse anything non-alphanumeric) which is enough for
"Final Fantasy VII" vs "Final Fantasy VII " vs "Final Fantasy: VII", and
deliberately does *not* try to peel editions or regions. Guessing wider here
would list titles that are not the same game, and a wrong system in a launch
menu is worse than a missing one.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, User, UserGameProgress, UserPreference, user_favorites
from oneirodex.utils.browser_player import browser_play_href
from oneirodex.utils.play_url import browse_play_fields
from oneirodex.utils.presence import accepted_friend_ids
from oneirodex.utils.title_grouping import TITLE_KEY_PATTERN

# Imported, not restated. The browse grid groups tiles with the same key
# computed in SQL (`utils/title_grouping.title_key_expr`); if these two
# patterns ever drifted, the grid would collapse a set of copies that the
# preview then refused to list as one title.
_NON_ALNUM = re.compile(TITLE_KEY_PATTERN)

#: Cap on rows considered for one lookup. A library with thousands of copies of
#: one name is a scan fault, not a use case, and the preview shows a handful.
MAX_EDITIONS = 12

#: Tags and household friends on the preview — enough to scan, not a dump.
MAX_PREVIEW_TAGS = 8
MAX_PREVIEW_FRIENDS = 5


def normalize_title(value: str | None) -> str:
    """Casefolded, punctuation-collapsed title used to pair copies across systems."""
    return _NON_ALNUM.sub(' ', (value or '').strip().lower()).strip()


def _core_label(core_id: str) -> str:
    """Human-facing core name. The ids are already the names people use."""
    return str(core_id or '').strip()


def _edition_play(game) -> dict:
    """Play fields for one copy, with a launch URL per browser-playable core.

    ``browse_play_fields`` already resolves the *preferred* core and builds one
    URL from it. The preview offers a choice, so every playable core gets its
    own URL here — same query shape as the one webretro is handed from the
    tile, with the core swapped.
    """
    fields = browse_play_fields(game)
    platform_key = fields.get('library_platform') or ''
    cores = list(fields.get('emulator_cores') or [])
    default_core = fields.get('emulator_core')

    launchers = []
    for core in cores:
        launchers.append({
            'core': core,
            'label': _core_label(core),
            'is_default': core == default_core,
            'play_url': browser_play_href(
                game_uuid=str(game.uuid),
                core=core,
                platform_key=platform_key or None,
            ),
        })

    return {
        'can_play_in_browser': bool(fields.get('can_play_in_browser')),
        'play_url': fields.get('play_url'),
        'play_mode': fields.get('play_mode'),
        'play_blocker': fields.get('play_blocker'),
        'companion_hint': fields.get('companion_hint'),
        'companion_cores': list(fields.get('companion_cores') or []),
        'firmware_missing': bool(fields.get('firmware_missing')),
        'launchers': launchers,
    }


def _http_store_url(value: str | None) -> str | None:
    href = (value or '').strip()
    if not href or href.casefold() == 'not available':
        return None
    lowered = href.casefold()
    if not (lowered.startswith('http://') or lowered.startswith('https://')):
        return None
    return href


def _iter_video_urls(game) -> list[str]:
    """Game.video_urls is a CSV string or a list."""
    raw = getattr(game, 'video_urls', None)
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(',') if part.strip()]
    return []


def store_links_for_games(games) -> list[dict]:
    """Store, catalog, and trailer links for a title, merged across copies.

    Browse tiles send one ``trailer_embed_url`` for muted hover, not the full
    ``Game.urls`` list — GOG / Epic still live there, while Steam is a column.
    The preview already asks for editions once; wrapping those store links on
    that payload is how the popup shows the same marks the details page does
    without inflating the grid. The preview stays a summary: a YouTube mark,
    not a second player.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    def push(url_type: str, url: str | None) -> None:
        href = _http_store_url(url)
        if not href or href in seen:
            return
        seen.add(href)
        rows.append({'type': url_type or '', 'url': href})

    for copy in games:
        steam = getattr(copy, 'steam_url', None)
        steam_app_id = getattr(copy, 'steam_app_id', None)
        if _http_store_url(steam):
            push('steam', steam)
        elif steam_app_id:
            push('steam', f'https://store.steampowered.com/app/{int(steam_app_id)}')
        push('igdb', getattr(copy, 'url_igdb', None) or getattr(copy, 'url', None))
        for row in getattr(copy, 'urls', None) or []:
            push(getattr(row, 'url_type', None) or '', getattr(row, 'url', None))
        # One trailer source is enough for a preview. Extra videos stay on
        # the details / Trailers surfaces.
        for href in _iter_video_urls(copy):
            lowered = href.casefold()
            if 'youtube.com' in lowered or 'youtu.be' in lowered:
                push('youtube', href)
                break
    return rows


def _edition_games(game, user) -> list:
    """Game rows the preview may name, current copy first, ACL-filtered."""
    from oneirodex.utils.library_acl import apply_game_access_filters

    key = normalize_title(getattr(game, 'name', None))
    if not key:
        return [game]

    # Narrow in SQL on the raw name, then confirm on the normalised one in
    # Python. A functional index on the normalisation does not exist, and the
    # candidate set for one title is small, so the cheap prefilter plus an exact
    # check is both correct and honest about what the database can do.
    stmt = (
        select(Game)
        .options(selectinload(Game.urls), joinedload(Game.library))
        .where(Game.name.ilike(f'%{game.name.strip()[:60]}%'))
        .limit(MAX_EDITIONS * 8)
    )
    # ACL first, always: a member must not learn that a title exists in a
    # library they cannot see. `apply_game_access_filters` only adds WHERE
    # clauses on Game, so it composes with the prefilter above without a join.
    stmt = apply_game_access_filters(stmt, user)

    candidates = db.session.execute(stmt).unique().scalars().all()

    rows = [other for other in candidates if normalize_title(other.name) == key]
    if not any(other.uuid == game.uuid for other in rows):
        rows.insert(0, game)

    # Current copy first, then by system label so the list is stable between
    # loads rather than following whatever order the query happened to return.
    rows.sort(key=lambda g: (g.uuid != game.uuid, _platform_key(g), g.uuid))
    return rows[:MAX_EDITIONS]


def editions_for_game(game, user) -> list[dict]:
    """Every copy of *game*'s title the *user* may see, current copy first.

    Always returns at least the game itself, so a caller never has to special
    case "only one system" — the preview renders the same list either way.
    """
    return [_edition_row(other, game) for other in _edition_games(game, user)]


def preview_tags(game, *, limit: int = MAX_PREVIEW_TAGS) -> list[dict]:
    """Facet labels already on the title — modes, genres, themes, perspective.

    Browse often sends genres; the rest live on relationships the grid does not
    carry. The preview already pays for a second request, so the tags ride here
    rather than inflating every tile.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    groups = (
        ('mode', getattr(game, 'game_modes', None) or ()),
        ('genre', getattr(game, 'genres', None) or ()),
        ('theme', getattr(game, 'themes', None) or ()),
        ('perspective', getattr(game, 'player_perspectives', None) or ()),
    )
    for kind, items in groups:
        for item in items:
            name = (getattr(item, 'name', None) or '').strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            rows.append({'label': name, 'kind': kind})
            if len(rows) >= limit:
                return rows
    return rows


def preview_friends(game_uuids, viewer, *, limit: int = MAX_PREVIEW_FRIENDS) -> list[dict]:
    """Accepted friends who played or favourited any copy of this title.

    Same share_activity gate as Discover's friends-playing row: opted-out
    friends stay off this overlay. The current member is never listed.
    """
    uuids = [str(value) for value in (game_uuids or []) if value]
    if not uuids or viewer is None:
        return []

    friend_ids = accepted_friend_ids(viewer.id)
    friend_ids.discard(viewer.id)
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
    sharing = friend_ids - opted_out
    if not sharing:
        return []

    played_ids = {
        row[0]
        for row in db.session.execute(
            select(UserGameProgress.user_id).where(
                UserGameProgress.user_id.in_(sharing),
                UserGameProgress.game_uuid.in_(uuids),
            )
        ).all()
    }
    favorited_ids = {
        row[0]
        for row in db.session.execute(
            select(user_favorites.c.user_id).where(
                user_favorites.c.user_id.in_(sharing),
                user_favorites.c.game_uuid.in_(uuids),
            )
        ).all()
    }
    # Played first — a session is a stronger signal than a favourite heart.
    ordered = [user_id for user_id in sorted(played_ids)]
    ordered.extend(user_id for user_id in sorted(favorited_ids) if user_id not in played_ids)
    chosen = ordered[:limit]
    if not chosen:
        return []

    names = {
        row.id: row.name
        for row in db.session.execute(select(User).where(User.id.in_(chosen))).scalars().all()
    }
    rows = []
    for user_id in chosen:
        name = (names.get(user_id) or '').strip()
        if not name:
            continue
        rows.append({
            'id': user_id,
            'name': name,
            'kind': 'played' if user_id in played_ids else 'favorited',
        })
    return rows


def editions_preview_payload(game, user) -> dict:
    """Editions list plus the store links the preview cannot get from browse."""
    copies = _edition_games(game, user)
    editions = [_edition_row(other, game) for other in copies]
    return {
        'uuid': game.uuid,
        'name': game.name,
        'editions': editions,
        # Distinct systems rather than distinct rows: two copies of one game in
        # two SNES libraries is one system, and the preview says "SNES" once.
        'system_count': len({
            row['library_platform'] for row in editions if row['library_platform']
        }),
        'urls': store_links_for_games(copies),
        'tags': preview_tags(game),
        'friends': preview_friends([copy.uuid for copy in copies], user),
    }


def _platform_key(game) -> str:
    library = getattr(game, 'library', None)
    platform = getattr(library, 'platform', None)
    return str(getattr(platform, 'name', '') or '')


def _edition_row(other, current) -> dict:
    library = getattr(other, 'library', None)
    platform = getattr(library, 'platform', None)
    return {
        'uuid': other.uuid,
        'name': other.name,
        'is_current': other.uuid == current.uuid,
        'library_uuid': getattr(library, 'uuid', None),
        'library_name': getattr(library, 'name', None),
        'library_platform': _platform_key(other) or None,
        'library_platform_label': getattr(platform, 'value', None)
        or _platform_key(other)
        or None,
        'path_missing': (getattr(other, 'path_status', None) == 'missing'),
        **_edition_play(other),
    }
