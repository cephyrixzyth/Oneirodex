"""Framework-independent Discover feed assembly shared by ASGI and legacy routes."""
from __future__ import annotations

from urllib.parse import quote, urlencode
from uuid import uuid4

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.utils.cache import cache
from oneirodex.utils.discover_feed import (
    FEED_ROW_CAP, assemble, excluded_for, manifest_from,
)
from oneirodex.utils.discover_hydrate import DiscoverHydration
from oneirodex.utils.discover_projections import serialize_discover_game
from oneirodex.utils.discover_providers import (
    ROW_MAX, ROW_WINDOW, resolve_feed, resolve_identifier,
)
from oneirodex.utils.discover_pins import admin_forced, hidden_rows, member_pins
from oneirodex.utils.discover_zones import (
    resolve_zone, rows_in_zone, zone_for_row, zone_index,
)

MAX_ROW_OFFSET = 2000
MAX_ROW_LIMIT = 60
TOTAL_PROBE = 200
FEED_MANIFEST_TTL_SECONDS = 1800

def _more_href(row) -> str:
    """Where this row's "see all" tile goes.

    The news row opens the News page — the full list, not a second Discover
    shelf of the same articles. Genre filter zones open the genre hub — the
    same tile in honest shelves — rather than dumping straight into the catalog.
    Other library filters still deep-link to Game Catalog. Everything else
    keeps its own row page.
    """
    spec = getattr(row, 'spec', None)
    item_kind = getattr(spec, 'item_kind', 'games') if spec is not None else 'games'
    identifier = getattr(row, 'identifier', None)
    # News has its own page. Other article shelves (deep discounts) keep a
    # Discover row page that renders NewsCards, not GameGrid.
    if identifier == 'news':
        return '/news'
    if item_kind == 'articles' and identifier:
        return f'/discover/{identifier}'
    if row.library_filter:
        genre = row.library_filter.get('genre')
        if genre:
            return f'/discover/hub/genre/{quote(str(genre), safe="")}'
        return f'/library?{urlencode(row.library_filter)}'
    return f'/discover/{row.identifier}'

def _section_has_more(row, raw_len: int) -> bool:
    """Whether a See all control is honest for this feed row.

    News always has a real destination (the News page) when it has any items.
    Game rows only offer See all when the source is deeper than the row ceiling.
    """
    spec = getattr(row, 'spec', None)
    item_kind = getattr(spec, 'item_kind', 'games') if spec is not None else 'games'
    identifier = getattr(row, 'identifier', None)
    if identifier == 'news' or item_kind == 'articles':
        return raw_len > 0
    return raw_len > ROW_MAX

def _row_payload(games, hydration):
    return [
        serialize_discover_game(
            game,
            hydration.cover_for(game),
            **hydration.serializer_kwargs(game),
        )
        for game in games
    ]

def _row_items(row, selected, hydration):
    """The items a row ships, keyed the way that kind of row is read.

    Game rows keep the ``games`` key they have always had. Rows of anything
    else — today the news row — carry ``items`` instead, and the payload's
    ``item_kind`` says which to read. Emitting both would mean serializing every
    tile twice for no reader's benefit.
    """
    if row.spec.item_kind != 'games':
        return {'items': list(selected)}
    return {'games': _row_payload(selected, hydration)}

def _feed_cache_key(user_id, token: str) -> str:
    return f'discover:feed:{user_id}:{token}'

def _store_manifest(user, manifest: dict) -> str | None:
    """Stash what each row claimed, and hand back the token that finds it.

    Returns None when the install has no usable cache — the feed still works,
    it just cannot carry dedupe into pagination, which is a degradation rather
    than a failure.
    """
    if not manifest:
        return None
    token = uuid4().hex
    try:
        cache.set(
            _feed_cache_key(getattr(user, 'id', None), token),
            manifest,
            timeout=FEED_MANIFEST_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 — a cacheless install still gets a feed
        return None
    return token

def _load_manifest(user, token: str | None) -> dict:
    if not token:
        return {}
    try:
        return cache.get(_feed_cache_key(getattr(user, 'id', None), token)) or {}
    except Exception:  # noqa: BLE001 — same stance as above
        return {}

def build_discover_feed(user) -> dict:
    """The whole feed: rows plus the token that keeps dedupe alive.

    The token names a cached record of which titles each row claimed. Row
    pagination passes it back so tiles 13-40 of one row skip what rows above it
    already showed — without it the dedupe is undone by the first scroll.
    """
    sections, manifest = _assemble_sections(user)
    return {
        'sections': sections,
        # The zone strip rides along with the feed rather than being a second
        # endpoint. Two reasons, both learned the hard way: a separate call
        # meant a second full assembly for a navigation aid, and — worse — the
        # two could disagree, which is exactly what happened (the strip offered
        # a zone whose page 404'd). Derived from these sections, it cannot.
        'zones': zone_index(sections),
        'feed_token': _store_manifest(user, manifest),
    }

def build_discover_sections(user) -> list[dict]:
    """Shelf payloads alone, for callers that do not page rows."""
    return _assemble_sections(user)[0]

def build_discover_zone(user, slug: str) -> dict | None:
    """One zone's rows, or None when the slug is unknown or has nothing live.

    Note the second half of that: a zone with no rows left after assembly is
    *not* an empty page with a heading. It is the same call the feed makes about
    an empty row, made one level up.
    """
    zone = resolve_zone(slug)
    if zone is None:
        return None
    sections, manifest = _assemble_sections(user, zone_slug=zone.slug)
    if not sections:
        return None
    return {
        'slug': zone.slug,
        'title': zone.title,
        'lede': zone.lede,
        'sections': sections,
        'feed_token': _store_manifest(user, manifest),
    }

def _assemble_sections(user, zone_slug: str | None = None):
    """Build Discover shelf payloads for the signed-in user.

    Rows ship a *window* rather than their whole contents: hydration batches, so
    the cost of a deep row is payload size rather than query count, and 20 rows
    of 40 serialized games is megabytes the member has not scrolled to yet. The
    rest of a row arrives from ``/api/discover/rows/<identifier>``.

    ``zone_slug`` narrows the page to one zone. It filters the *resolved* rows
    and then lets everything downstream run untouched, so a zone page is the
    feed pipeline with a smaller input rather than a second implementation —
    ACL, member hide, dedupe, the slot budget and `hide_when_empty` all behave
    as they do on the main feed, and none of them had to learn what a zone is.

    Returns ``(sections, manifest)``.
    """
    rows = resolve_feed(user)
    if zone_slug is not None:
        rows = rows_in_zone(rows, zone_slug)

    # Rows this member excluded. Applied before selection, not after, so a
    # hidden row costs no query and — more importantly — releases the titles it
    # would have claimed back to the rows below it. Filtering after assembly
    # would leave the dedupe pass having already spent those titles on a row
    # nobody was going to see, which reads as "hiding a row emptied the next
    # one".
    #
    # `resolve_feed` is the source for both this and `available` in the pins
    # endpoint, so the two agree on what a valid identifier is.
    excluded = set(hidden_rows(user, available=[row.identifier for row in rows]))
    if excluded:
        rows = [row for row in rows if row.identifier not in excluded]

    hydration = DiscoverHydration(user)

    # Pass 1 - selection. One query per row. Over-fetching by one past the
    # ceiling is what lets a row say whether there is more than it will ever
    # hold, without a second COUNT query per row.
    selected = {row.identifier: row.select(user, ROW_MAX + 1) for row in rows}

    # Pass 2 - assembly. Caps the page and strips titles an earlier row already
    # showed, together, because dropping a starved row frees a slot. Reserved
    # rows go first; both blocks are capped so neither side starves the other.
    available = [row.identifier for row in rows]
    assembled = assemble(
        rows,
        selected,
        window=ROW_WINDOW,
        cap=FEED_ROW_CAP,
        forced=admin_forced(),
        pinned=member_pins(user, available=available),
    )

    # Only the window is hydrated, and only for rows made of games. The
    # candidates past the window cost a row in the result set and nothing else.
    hydration.prime(
        game
        for entry in assembled
        if entry.row.spec.item_kind == 'games'
        for game in entry.games[:ROW_WINDOW]
    )

    discover_sections = []
    for entry in assembled:
        row = entry.row
        candidates = entry.games
        # What this row still had before dedupe took titles off it. The two
        # counts below answer different questions and must not share a source:
        # how deep this row goes *inline* is what survived dedupe, while
        # whether a "see all" is honest is about the row's own source.
        raw = selected.get(row.identifier, [])
        items = _row_items(row, candidates[:ROW_WINDOW], hydration)
        shipped = next(iter(items.values()))
        # An article row can hydrate to nothing even when it selected something
        # (a news item whose article body failed to resolve), which assembly
        # cannot see — it counts selected rows, not rendered items. Games rows
        # are already handled upstream by `hide_when_empty`.
        if not shipped and row.spec.item_kind != 'games' and row.spec.hide_when_empty:
            continue
        section = row.section
        discover_sections.append({
            'identifier': row.identifier,
            'title': row.title,
            'layout': section.layout or 'shelf',
            'item_kind': row.spec.item_kind,
            'reason': row.spec.reason,
            # Which surface this shelf belongs to. Recorded here, at the one
            # point where the resolved row and its payload are both in hand, so
            # the zone strip is a group-by over shelves that actually rendered
            # rather than a second guess at what will.
            'zone': zone_for_row(row),
            'is_event': bool(section.starts_at or section.ends_at),
            'ends_at': section.ends_at.isoformat() if section.ends_at else None,
            **items,
            # Tiles this row holds after dedupe, so the client knows when to
            # stop asking for more. Capped at the row ceiling.
            'total_count': min(len(candidates), ROW_MAX),
            # True when the row's source is not the whole story - the only
            # condition under which a "see all" tile is honest. Read from the
            # source rather than from what dedupe left, or a row thinned by its
            # neighbours would hide a way out that genuinely exists.
            'has_more': _section_has_more(row, len(raw)),
            'more_href': _more_href(row),
        })

    manifest = manifest_from(assembled)

    # Note what the member was shown, so the recommender can stop insisting on
    # tiles they keep scrolling past. Best-effort by design: an un-recorded
    # impression costs a little freshness, and a feed that failed to render
    # because a bookkeeping write went wrong costs a lot more.
    try:
        from oneirodex.utils.discover_ml.impressions import record_impressions

        record_impressions(
            getattr(user, 'id', None),
            [uuid for claimed in manifest.values() for uuid in claimed],
        )
    except Exception:  # noqa: BLE001
        db.session.rollback()

    return discover_sections, manifest

def build_discover_row(user, identifier, *, offset=0, limit=ROW_WINDOW, feed_token=None):
    """One row's games, windowed. Returns None when the row is not available.

    Unavailable covers hidden and out-of-schedule as well as unknown: a row
    resolves through its ``DiscoverySection``, so this endpoint is not a way
    around the visibility toggle the admin screen presents as authoritative.

    ``feed_token`` carries the cross-row dedupe from the feed into pagination.
    Without it this row would hand back the titles the rows above it are already
    showing, undoing the dedupe on the member's first scroll.
    """
    row = resolve_identifier(identifier)
    if row is None:
        return None

    offset = max(0, min(int(offset or 0), MAX_ROW_OFFSET))
    limit = max(1, min(int(limit or ROW_WINDOW), MAX_ROW_LIMIT))

    excluded = set()
    if row.spec.dedupe_mode != 'exempt':
        excluded = excluded_for(_load_manifest(user, feed_token), identifier)

    # One past the window, so "is there another page" needs no extra query.
    # Excluded titles are dropped after selection, so the row is over-fetched by
    # what the exclusion set could remove — otherwise a heavily deduped row
    # returns a short page and looks finished before it is.
    #
    # Then raised to TOTAL_PROBE, because the caller needs to know how much is
    # left and not merely whether anything is. Same single query either way: a
    # selector's limit becomes a LIMIT, and the feed already runs these at
    # ROW_MAX + 1.
    fetch = max(offset + limit + 1 + len(excluded), TOTAL_PROBE)
    asked = min(fetch, MAX_ROW_OFFSET + MAX_ROW_LIMIT + ROW_MAX)
    candidates = list(row.select(user, asked))
    # Short of what was asked for means the source ran out inside the probe, so
    # what came back is everything there is. Measured before the exclusion pass,
    # which removes rows without saying anything about how deep the source went.
    exhausted = len(candidates) < asked
    if excluded:
        candidates = [
            game for game in candidates if getattr(game, 'uuid', None) not in excluded
        ]
    window = candidates[offset:offset + limit]

    hydration = DiscoverHydration(user)
    if row.spec.item_kind == 'games':
        hydration.prime(window)

    section = row.section
    return {
        'identifier': row.identifier,
        'title': row.title,
        'layout': section.layout or 'shelf',
        'item_kind': row.spec.item_kind,
        'reason': row.spec.reason,
        'offset': offset,
        'limit': limit,
        **_row_items(row, window, hydration),
        'has_more': len(candidates) > offset + limit,
        # How many items this row holds in total, so a Load more control can say
        # what is left instead of only that something is. `null` when the probe
        # hit its ceiling without exhausting the source — the honest answer is
        # "more than we counted", and a client that gets `null` falls back to
        # `has_more`, which is what it had before this field existed.
        'total': len(candidates) if exhausted else None,
        'total_is_estimate': not exhausted,
        'more_href': _more_href(row),
    }
