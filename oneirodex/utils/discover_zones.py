"""Discover zones — the feed as a few named surfaces instead of one long scroll.

A zone is a landing surface: a slug, a title, and the rows that belong to it.
Twelve rows stacked on one page is a scroll, not a destination; the same twelve
split across "For you", "New & updated", "Popular" and "From the stores" are
four places a member can mean to go.

**Zones own no rows of their own.** A zone is a *filter over the feed* — it
names identifiers that `discover_providers.resolve_feed` already produced, and
the whole pipeline behind that (library ACL, section visibility, schedule
windows, member hide, cross-row dedupe, `hide_when_empty`) runs unchanged. That
is deliberate and load-bearing:

- a shelf an admin hides disappears from its zone without the zone knowing;
- a zone whose rows are all empty resolves to nothing and is dropped from the
  zone list, so the honesty rule that removed empty *rows* removes empty
  *zones* for free;
- adding a row to the registry needs no zone edit — `_FALLBACK_BY_FAMILY`
  places it, and `ZONE_FOR_UNPLACED` catches anything with no family rule.

Nothing here writes to the database and nothing here is admin-configurable yet.
Membership is declared in code because the set of *system* rows is declared in
code; when zones need to be arranged per install, this registry is the thing
that grows a `DiscoverySection`-backed override, not a second mechanism.

**Naming.** Until 2026-09-06 this module's name was one letter from
`discovery_zones.py`, which called a single admin-curated shelf a "custom zone"
(UID-059). That module is now `discovery_shelves.py` and its concept is a
*shelf* throughout, admin copy included, so "zone" means one thing again: a page
of shelves. A custom shelf is one of the things a zone can contain — they land
in ``curated``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from oneirodex.utils.discover_providers import BECAUSE_YOU_PLAYED


@dataclass(frozen=True)
class ZoneSpec:
    """A named surface and the rows that belong to it."""

    slug: str
    title: str
    #: One sentence under the title. Says what the surface is *for*, not what
    #: it contains — the rows say that themselves.
    lede: str
    #: Row identifiers claimed by name. Order here is not the render order:
    #: rows keep the sequence the admin arranged on the Discovery Sections
    #: screen, the same as the main feed, because two screens disagreeing about
    #: row order is worse than either order.
    rows: tuple[str, ...] = ()


#: The surfaces, in the order the zone strip shows them.
#:
#: Four system zones plus one for anything a person built. The split is by
#: *why a member would come looking*, which is why "New & updated" holds both
#: newly-added titles and update files: they are one question ("what changed
#: since I last looked"), even though one is a chart row and the other personal.
ZONES: tuple[ZoneSpec, ...] = (
    ZoneSpec(
        slug='for-you',
        title='For you',
        lede='Built from what you play, and what the people you know are playing.',
        rows=(
            'continue_playing',
            'curated_for_you',
            'friends_playing',
        ),
    ),
    ZoneSpec(
        slug='new',
        title='New & updated',
        lede='What has changed in the vault since you last looked.',
        rows=(
            'latest_games',
            'new_library_games',
            'game_updates',
            'last_updated',
            'upcoming',
        ),
    ),
    ZoneSpec(
        slug='popular',
        title='Popular here',
        lede='What this household actually plays, rates and keeps.',
        rows=(
            'most_downloaded',
            'highest_rated',
            'most_favorited',
        ),
    ),
    ZoneSpec(
        slug='elsewhere',
        title='Elsewhere',
        lede='News, free games, store deals and extras — things that live outside the vault.',
        rows=(
            'news',
            'free_games',
            'store_deals',
            'extras_missing',
        ),
    ),
    ZoneSpec(
        slug='curated',
        title='Curated',
        lede='Shelves someone here built by hand.',
        # Populated entirely by fallback: every admin-authored section lands
        # here, and naming them would mean editing this file whenever an admin
        # adds a shelf.
    ),
)

_BY_SLUG = {zone.slug: zone for zone in ZONES}

#: Where a row goes when no zone claims it by name. Keyed by `RowSpec.family`.
#:
#: `ml` covers the recommender's generated `because_you_played:<uuid>` rows,
#: whose identifiers cannot be listed because they are made per member, per
#: anchor title, at request time.
_FALLBACK_BY_FAMILY = {
    'personal': 'for-you',
    'ml': 'for-you',
    'chart': 'popular',
    'editorial': 'curated',
}

#: Last resort, so a new family cannot make a row unreachable. A row in no zone
#: is a row a member can only find by scrolling the main feed, which is the
#: thing zones exist to stop being the only way.
ZONE_FOR_UNPLACED = 'curated'


def zone_for_row(row) -> str:
    """Which zone a resolved row belongs to.

    Explicit membership wins; then the generated-row prefix; then family; then
    the catch-all. A row is in exactly one zone — a row appearing on two
    surfaces would make the zone strip a set of overlapping views rather than a
    division of the feed, and "I already saw this" is the complaint zones are
    meant to answer.
    """
    identifier = getattr(row, 'identifier', '') or ''
    for zone in ZONES:
        if identifier in zone.rows:
            return zone.slug
    if identifier.split(':', 1)[0] == BECAUSE_YOU_PLAYED:
        return 'for-you'
    family = getattr(getattr(row, 'spec', None), 'family', None)
    return _FALLBACK_BY_FAMILY.get(family, ZONE_FOR_UNPLACED)


def resolve_zone(slug: str) -> Optional[ZoneSpec]:
    return _BY_SLUG.get((slug or '').strip().lower())


def rows_in_zone(rows: Sequence, slug: str) -> list:
    """The subset of ``rows`` belonging to ``slug``, in the order given."""
    return [row for row in rows if zone_for_row(row) == slug]


def zone_index(sections: Sequence) -> list[dict]:
    """Every zone that has at least one *rendered* shelf.

    Built from assembled section payloads, not from resolved rows, and the
    difference is the whole point. Counting resolved rows counts rows that
    selection is about to throw away: on a household install "New & updated"
    resolved one row, listed itself in the strip, and then 404'd when opened
    because that row turned out to be empty and `hide_when_empty` dropped it.
    A strip offering a destination that does not exist is the complaint zones
    were built to answer, so the index has to see what the page sees.

    Each section carries the zone it landed in (`zone_for_row` at serialisation
    time), so this is a group-by over work already done — no second assembly,
    and no way for the strip and the page to disagree.

    Order is the declared order in ``ZONES``, never the order rows happened to
    resolve in: the strip is a stable set of destinations, not a ranking.
    """
    counts: dict[str, int] = {}
    for section in sections:
        slug = (section or {}).get('zone')
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return [
        {
            'slug': zone.slug,
            'title': zone.title,
            'lede': zone.lede,
            'shelf_count': counts[zone.slug],
            'href': f'/discover/zone/{zone.slug}',
        }
        for zone in ZONES
        if counts.get(zone.slug)
    ]
