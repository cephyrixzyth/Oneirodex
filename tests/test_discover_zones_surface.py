"""Zone membership and the zone index.

Pure logic over resolved rows, so these run without a database — the same
stance as test_discover_feed.py, and for the same reason: this is the stage
that decides whether a member can reach a row at all.
"""

from types import SimpleNamespace

from oneirodex.utils.discover_zones import (
    ZONE_FOR_UNPLACED,
    ZONES,
    resolve_zone,
    rows_in_zone,
    zone_for_row,
    zone_index,
)


def row(identifier, *, family='chart'):
    return SimpleNamespace(
        identifier=identifier,
        spec=SimpleNamespace(identifier=identifier, family=family),
    )


class TestMembership:
    def test_named_rows_land_in_their_zone(self):
        assert zone_for_row(row('continue_playing', family='personal')) == 'for-you'
        assert zone_for_row(row('latest_games')) == 'new'
        assert zone_for_row(row('most_downloaded')) == 'popular'
        assert zone_for_row(row('news', family='editorial')) == 'elsewhere'
        assert zone_for_row(row('free_games', family='editorial')) == 'elsewhere'

    def test_named_membership_beats_family(self):
        """`game_updates` is a personal row, but it belongs to New & updated.

        Family is the fallback, not the rule — otherwise "what changed since I
        last looked" would be split across two surfaces by an implementation
        detail of how the row is generated.
        """
        assert zone_for_row(row('game_updates', family='personal')) == 'new'
        assert zone_for_row(row('extras_missing', family='personal')) == 'elsewhere'

    def test_generated_rows_follow_their_prefix(self):
        """`because_you_played:<uuid>` cannot be listed by name — it is made per
        member, per anchor, at request time."""
        assert zone_for_row(
            row('because_you_played:0000-1111', family='ml')
        ) == 'for-you'

    def test_unknown_row_falls_back_to_family(self):
        assert zone_for_row(row('some_new_chart_row', family='chart')) == 'popular'
        assert zone_for_row(row('an_admin_shelf', family='editorial')) == 'curated'

    def test_unknown_family_still_lands_somewhere(self):
        """A row in no zone is reachable only by scrolling the main feed, which
        is the thing zones exist to stop being the only way."""
        assert zone_for_row(row('mystery', family='brand_new_family')) == ZONE_FOR_UNPLACED

    def test_every_row_belongs_to_exactly_one_zone(self):
        rows = [
            row('continue_playing', family='personal'),
            row('latest_games'),
            row('most_favorited'),
            row('store_deals', family='editorial'),
            row('because_you_played:abc', family='ml'),
        ]
        for candidate in rows:
            slugs = [z.slug for z in ZONES if candidate in rows_in_zone(rows, z.slug)]
            assert len(slugs) == 1, f'{candidate.identifier} in {slugs}'


def section(slug):
    """An assembled shelf payload, as `_assemble_sections` serialises it."""
    return {'zone': slug}


class TestIndex:
    def test_lists_only_zones_with_rendered_shelves(self):
        index = zone_index([section('new'), section('popular')])
        slugs = [entry['slug'] for entry in index]
        assert slugs == ['new', 'popular']
        assert 'for-you' not in slugs

    def test_empty_feed_lists_no_zones(self):
        assert zone_index([]) == []

    def test_index_keeps_declared_order_not_shelf_order(self):
        """The strip is a stable set of destinations; it must not reshuffle
        because one shelf happened to assemble first."""
        index = zone_index([section('popular'), section('for-you')])
        assert [entry['slug'] for entry in index] == ['for-you', 'popular']

    def test_entries_carry_what_the_strip_renders(self):
        entry = zone_index([section('new')])[0]
        assert entry['title'] == 'New & updated'
        assert entry['href'] == '/discover/zone/new'
        assert entry['lede']
        assert entry['shelf_count'] == 1

    def test_a_zone_whose_rows_all_emptied_is_not_listed(self):
        """The regression this shape exists for.

        `latest_games` resolves into the `new` zone, so an index built from
        *resolved rows* listed New & updated — and then `/discover/zones/new`
        404'd, because selection found the row empty and `hide_when_empty`
        dropped it. Assembly produced no section, so no zone.
        """
        assert zone_index([]) == []
        assert zone_index([{'zone': None}]) == []

    def test_sections_without_a_zone_key_are_ignored(self):
        """Virtual shelves (genre hubs) are serialised elsewhere and carry no
        zone. They must not invent one."""
        assert zone_index([{'identifier': 'hub:genre:1:newest'}]) == []


class TestResolve:
    def test_resolves_and_normalises(self):
        assert resolve_zone('for-you').title == 'For you'
        assert resolve_zone('  FOR-YOU  ').slug == 'for-you'

    def test_unknown_slug_is_none(self):
        assert resolve_zone('nope') is None
        assert resolve_zone('') is None
        assert resolve_zone(None) is None

    def test_every_declared_zone_resolves(self):
        for zone in ZONES:
            assert resolve_zone(zone.slug) is zone

    def test_the_unplaced_fallback_is_a_real_zone(self):
        """A typo here would send every unclaimed row to a slug that 404s."""
        assert resolve_zone(ZONE_FOR_UNPLACED) is not None
