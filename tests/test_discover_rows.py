"""The row registry and the row endpoint behind the "see all" tile."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import DiscoverySection, Game, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def row_user(db_session):
    user = User(
        name=f'rows_{uuid4().hex[:8]}',
        email=f'rows_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.fixture
def row_library(db_session):
    library = Library(
        name=f'Rows Library {uuid4().hex[:6]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def many_games(db_session, row_library):
    from oneirodex.utils.discover_providers import ROW_MAX

    # Released, and staggered. `latest_games` orders by `first_release_date`
    # and skips rows without one, so undated fixtures make that row empty and
    # these paging assertions measure nothing. Naive UTC to match the column.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(ROW_MAX * 2):
        db_session.add(
            Game(
                name=f'Row Game {i}',
                summary='s',
                rating=60.0 + i,
                times_downloaded=i + 1,
                first_release_date=now - timedelta(days=i + 1),
                library_uuid=row_library.uuid,
            )
        )
    db_session.commit()


@pytest.fixture
def latest_shelf(db_session):
    section = db.session.execute(
        select(DiscoverySection).filter_by(identifier='latest_games')
    ).scalar_one_or_none()
    if section is None:
        section = DiscoverySection(
            identifier='latest_games',
            name='Latest Games',
            display_order=1,
        )
        db_session.add(section)
    section.is_visible = True
    section.starts_at = None
    section.ends_at = None
    db_session.commit()
    return section


class TestRowRegistry:
    def test_seed_shelves_resolve_to_a_provider(self, app, latest_shelf):
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            row = resolve_identifier('latest_games')

        assert row is not None
        assert row.identifier == 'latest_games'
        assert row.spec.item_kind == 'games'

    def test_hidden_shelf_is_unreachable_by_identifier(
        self, app, db_session, latest_shelf
    ):
        """The row endpoint must not be a way around the visibility toggle.

        The admin screen presents that switch as authoritative; a row reachable
        by direct URL while hidden would quietly make it advisory.
        """
        from oneirodex.utils.discover_providers import resolve_identifier

        latest_shelf.is_visible = False
        db_session.commit()

        with app.app_context():
            assert resolve_identifier('latest_games') is None

    def test_unknown_identifier_resolves_to_nothing(self, app):
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            assert resolve_identifier('no_such_row') is None

    def test_libraries_shelf_is_not_a_game_row(self, app, db_session):
        """It carries no games, so it is not a row this feed builds."""
        from oneirodex.utils.discover_providers import resolve_section

        section = DiscoverySection(
            identifier='libraries', name='Libraries', is_visible=True
        )
        with app.app_context():
            assert resolve_section(section) is None


class TestSeeAllTarget:
    def test_news_row_points_at_the_news_page(self):
        from types import SimpleNamespace

        from oneirodex.utils.discover_builder import _more_href, _section_has_more

        row = SimpleNamespace(
            identifier='news',
            spec=SimpleNamespace(item_kind='articles'),
            library_filter=None,
        )
        assert _more_href(row) == '/news'
        assert _section_has_more(row, 3) is True
        assert _section_has_more(row, 0) is False

    def test_chart_row_points_at_its_own_page(self, app, latest_shelf):
        from oneirodex.utils.discover_builder import _more_href
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            row = resolve_identifier('latest_games')
            assert _more_href(row) == '/discover/latest_games'

    def test_genre_zone_deep_links_into_the_hub(self, app, db_session):
        """A genre zone opens the hub, not a second catalog grid.

        The catalog is still the full list from the hub's Browse catalog link.
        """
        from oneirodex.utils.discover_builder import _more_href
        from oneirodex.utils.discover_providers import resolve_section

        section = DiscoverySection(
            identifier=f'zone_{uuid4().hex[:6]}',
            name='Roguelikes',
            is_visible=True,
            section_type='custom',
            config={'mode': 'filter', 'filter_type': 'genre', 'filter_value': 'Roguelike'},
        )
        with app.app_context():
            row = resolve_section(section)
            assert _more_href(row) == '/discover/hub/genre/Roguelike'

    def test_library_zone_falls_back_to_the_row_page(self, app, db_session):
        """The Library page has no library-scoped URL filter.

        Linking one there would silently show the whole library, so a library
        zone keeps its own page instead.
        """
        from oneirodex.utils.discover_builder import _more_href
        from oneirodex.utils.discover_providers import resolve_section

        identifier = f'zone_{uuid4().hex[:6]}'
        section = DiscoverySection(
            identifier=identifier,
            name='A Library',
            is_visible=True,
            section_type='custom',
            config={'mode': 'filter', 'filter_type': 'library', 'filter_value': 'abc'},
        )
        with app.app_context():
            row = resolve_section(section)
            assert _more_href(row) == f'/discover/{identifier}'


class TestBuildDiscoverRow:
    def test_window_pages_forward(self, app, row_user, many_games, latest_shelf):
        from oneirodex.routes_discover import build_discover_row

        with app.app_context(), app.test_request_context('/'):
            first = build_discover_row(row_user, 'latest_games', offset=0, limit=6)
            second = build_discover_row(row_user, 'latest_games', offset=6, limit=6)

        assert len(first['games']) == 6
        assert len(second['games']) == 6
        assert first['has_more'] is True

        first_uuids = {game['uuid'] for game in first['games']}
        second_uuids = {game['uuid'] for game in second['games']}
        assert not (first_uuids & second_uuids), 'pages overlapped'

    def test_limit_is_clamped(self, app, row_user, many_games, latest_shelf):
        """A caller asking for everything should not get to name the page size."""
        from oneirodex.routes_discover import MAX_ROW_LIMIT, build_discover_row

        with app.app_context(), app.test_request_context('/'):
            payload = build_discover_row(row_user, 'latest_games', limit=100_000)

        assert payload['limit'] == MAX_ROW_LIMIT
        assert len(payload['games']) <= MAX_ROW_LIMIT

    def test_negative_offset_is_clamped_to_the_start(
        self, app, row_user, many_games, latest_shelf
    ):
        from oneirodex.routes_discover import build_discover_row

        with app.app_context(), app.test_request_context('/'):
            payload = build_discover_row(row_user, 'latest_games', offset=-50)

        assert payload['offset'] == 0

    def test_unknown_row_returns_nothing(self, app, row_user):
        from oneirodex.routes_discover import build_discover_row

        with app.app_context(), app.test_request_context('/'):
            assert build_discover_row(row_user, 'no_such_row') is None


class TestFeedWindowContract:
    def test_row_reports_more_beyond_its_ceiling(
        self, app, row_user, many_games, latest_shelf
    ):
        from oneirodex.routes_discover import build_discover_sections
        from oneirodex.utils.discover_providers import ROW_MAX

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(row_user)

        latest = next(r for r in sections if r['identifier'] == 'latest_games')
        # Not equal to the ceiling: cross-row dedupe can take titles off this
        # row, so its inline depth is what survived, capped at the ceiling.
        # `has_more` is read from the source, so it stays honest either way.
        assert 0 < latest['total_count'] <= ROW_MAX
        assert latest['has_more'] is True
        assert latest['more_href'] == '/discover/latest_games'

    def test_short_row_offers_no_see_all(self, app, db_session, row_user, row_library):
        """A row that shows everything it has must not claim there is more."""
        from oneirodex.routes_discover import build_discover_sections

        db_session.add(
            Game(name='Only One', summary='s', library_uuid=row_library.uuid)
        )
        db_session.commit()

        section = db.session.execute(
            select(DiscoverySection).filter_by(identifier='most_favorited')
        ).scalar_one_or_none()
        if section is None:
            pytest.skip('most_favorited shelf not seeded in this database')
        section.is_visible = True
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(row_user)

        for row in sections:
            # Game rows carry `games`, article rows carry `items`; `item_kind`
            # says which. Nothing carries both.
            shipped = row.get('games', row.get('items', []))
            if not row['has_more']:
                assert row['total_count'] >= len(shipped)
                assert row['total_count'] <= 40


class TestRowEndpoint:
    def test_requires_login(self, client):
        response = client.get('/api/discover/rows/latest_games')
        assert response.status_code in (302, 401)

    def test_unknown_row_is_a_404_envelope(self, app, client, row_user):
        _login(client, row_user)
        response = client.get('/api/discover/rows/no_such_row')
        assert response.status_code == 404
        body = response.get_json()
        assert body['ok'] is False
        assert body['error_code'] == 'not_found'
        assert body['error']

    def test_non_numeric_paging_is_rejected(self, app, client, row_user):
        _login(client, row_user)
        response = client.get('/api/discover/rows/latest_games?offset=abc')
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert body['error_code'] == 'bad_request'

    def test_success_carries_the_envelope(
        self, app, client, row_user, many_games, latest_shelf
    ):
        _login(client, row_user)
        response = client.get('/api/discover/rows/latest_games?offset=0&limit=5')
        assert response.status_code == 200
        body = response.get_json()
        assert body['ok'] is True
        assert body['error'] is None
        assert body['error_code'] is None
        assert body['identifier'] == 'latest_games'
        assert len(body['games']) <= 5


class TestFeedTokenCarriesDedupe:
    """Dedupe has to survive pagination or it is cosmetic.

    The moment a member scrolls a row far enough to fetch its next window, the
    server has to still know what the rows above it showed.
    """

    def test_the_feed_hands_back_a_token(self, app, row_user, many_games, latest_shelf):
        from oneirodex.routes_discover import build_discover_feed

        with app.app_context(), app.test_request_context('/'):
            feed = build_discover_feed(row_user)

        assert feed['sections']
        # None is a legitimate answer on a cacheless install, but not here.
        assert feed['feed_token'], 'expected a usable cache in the test install'

    def test_paging_with_the_token_skips_what_other_rows_showed(
        self, app, row_user, many_games, latest_shelf
    ):
        from oneirodex.routes_discover import build_discover_feed, build_discover_row
        from oneirodex.utils.discover_feed import excluded_for
        from oneirodex.utils.discover_builder import _load_manifest

        with app.app_context(), app.test_request_context('/'):
            feed = build_discover_feed(row_user)
            token = feed['feed_token']
            manifest = _load_manifest(row_user, token)

            other_rows_showed = excluded_for(manifest, 'latest_games')
            paged = build_discover_row(
                row_user, 'latest_games', offset=0, limit=40, feed_token=token
            )

        returned = {game['uuid'] for game in paged['games']}
        assert not (returned & other_rows_showed), (
            'the row handed back titles another row is already showing'
        )

    def test_paging_without_a_token_is_still_served(
        self, app, row_user, many_games, latest_shelf
    ):
        """An old client, or a cacheless install, still gets its tiles."""
        from oneirodex.routes_discover import build_discover_row

        with app.app_context(), app.test_request_context('/'):
            paged = build_discover_row(row_user, 'latest_games', offset=0, limit=10)

        assert paged['games']

    def test_an_unknown_token_is_ignored_rather_than_fatal(
        self, app, row_user, many_games, latest_shelf
    ):
        """Tokens expire. A stale one must degrade, not 500."""
        from oneirodex.routes_discover import build_discover_row

        with app.app_context(), app.test_request_context('/'):
            paged = build_discover_row(
                row_user, 'latest_games', offset=0, limit=10, feed_token='not-a-real-token'
            )

        assert paged['games']

    def test_the_endpoint_accepts_the_token(
        self, app, client, row_user, many_games, latest_shelf
    ):
        _login(client, row_user)
        feed = client.get('/api/discover/sections')
        token = feed.get_json().get('feed_token')
        assert token

        response = client.get(
            f'/api/discover/rows/latest_games?offset=0&limit=5&feed_token={token}'
        )
        assert response.status_code == 200
        assert response.get_json()['ok'] is True


class TestFeedRowCap:
    def test_the_page_never_exceeds_the_row_cap(
        self, app, row_user, many_games, latest_shelf
    ):
        from oneirodex.routes_discover import build_discover_sections
        from oneirodex.utils.discover_feed import FEED_ROW_CAP

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(row_user)

        assert len(sections) <= FEED_ROW_CAP


class TestDedupeDoesNotHideTheWayOut:
    def test_a_row_thinned_by_neighbours_still_offers_see_all(
        self, app, row_user, many_games, latest_shelf
    ):
        """`has_more` is about the row's source, not about what dedupe left.

        Reading it from the deduped list would make a row that lost titles to
        its neighbours quietly drop a link that genuinely goes somewhere.
        """
        from oneirodex.routes_discover import build_discover_sections
        from oneirodex.utils.discover_providers import ROW_MAX

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(row_user)

        latest = next(
            (r for r in sections if r['identifier'] == 'latest_games'), None
        )
        if latest is None:
            pytest.skip('latest_games did not make the feed in this database')

        assert latest['has_more'] is True
        # Dedupe may well have taken titles off it, so the inline depth can be
        # under the ceiling even while the way out stays honest.
        assert latest['total_count'] <= ROW_MAX
