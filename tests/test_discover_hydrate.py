"""Discover hydration stays flat as shelves get deeper.

The point of `oneirodex.utils.discover_hydrate` is that the cost of building the
feed tracks the number of *shelves*, not the number of *tiles*. That property is
invisible in the payload — a feed built with one query per tile returns exactly
the same JSON as one built in a single batch — so nothing but a query count will
notice when it regresses.

It regressed once already, which is why this exists: the serializer grew a
cover-image lookup, three lazy relationships and a companion-presence check, each
correct on its own and each per tile.
"""

from uuid import uuid4

import pytest
from sqlalchemy import event, select

from oneirodex import db
from oneirodex.models import DiscoverySection, Game, Library, User
from oneirodex.platform import LibraryPlatform

SEED_SHELVES = ('latest_games', 'most_downloaded', 'highest_rated')


@pytest.fixture
def hydrate_user(db_session):
    user = User(
        name=f'hydrate_{uuid4().hex[:8]}',
        email=f'hydrate_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def hydrate_library(db_session):
    library = Library(
        name=f'Hydrate Library {uuid4().hex[:6]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def seed_shelves(db_session):
    """Turn on exactly the shelves this test reasons about, and only those.

    Other shelves would add their own constant query cost, which does not break
    the assertion but does make a failure harder to read.
    """
    for section in db.session.execute(select(DiscoverySection)).scalars().all():
        section.is_visible = section.identifier in SEED_SHELVES
    for order, identifier in enumerate(SEED_SHELVES, start=1):
        existing = db.session.execute(
            select(DiscoverySection).filter_by(identifier=identifier)
        ).scalar_one_or_none()
        if existing is None:
            db_session.add(
                DiscoverySection(
                    identifier=identifier,
                    name=identifier.replace('_', ' ').title(),
                    is_visible=True,
                    display_order=order,
                )
            )
    db_session.commit()


def _add_games(db_session, library, count, *, offset=0):
    for i in range(offset, offset + count):
        db_session.add(
            Game(
                name=f'Hydrate Game {i}',
                summary=f'Summary {i}',
                rating=70.0 + i,
                times_downloaded=i + 1,
                library_uuid=library.uuid,
            )
        )
    db_session.commit()


def _count_queries(fn):
    """Run ``fn`` and return (result, number of SQL statements executed)."""
    statements = []

    def before_cursor_execute(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, 'before_cursor_execute', before_cursor_execute)
    try:
        result = fn()
    finally:
        event.remove(engine, 'before_cursor_execute', before_cursor_execute)
    return result, len(statements)


class TestHydrationDoesNotScaleWithTiles:
    def test_query_count_is_flat_as_shelves_deepen(
        self, app, db_session, hydrate_user, hydrate_library, seed_shelves, monkeypatch
    ):
        """Same shelves, deeper rows, identical query count.

        Depth is varied through ``ROW_WINDOW`` rather than by adding games:
        the shared test database already holds enough titles to fill every
        shelf, so seeding more changes nothing. Patching the limit varies
        exactly the dimension under test and holds the shelf count still.
        """
        import oneirodex.utils.discover_builder as discover_builder
        from oneirodex.routes_discover import build_discover_sections

        def build_at_depth(limit):
            # The feed assembly lives in discover_builder; patch its imported
            # window so this varies the depth the selector actually receives.
            monkeypatch.setattr(discover_builder, 'ROW_WINDOW', limit)
            # Nothing cached: a lazy relationship must re-emit its query, or an
            # N+1 would hide behind the identity map instead of being counted.
            db.session.expire_all()
            return _count_queries(lambda: build_discover_sections(hydrate_user))

        _add_games(db_session, hydrate_library, 12)

        with app.app_context(), app.test_request_context('/'):
            shallow, shallow_queries = build_at_depth(2)
            deep, deep_queries = build_at_depth(12)

        shallow_tiles = sum(len(row['games']) for row in shallow)
        deep_tiles = sum(len(row['games']) for row in deep)

        # The premise: the second feed really is deeper than the first.
        assert deep_tiles > shallow_tiles, (
            'both feeds came back the same depth, so the assertion below '
            'proves nothing'
        )

        # Not equality. A `selectinload` skips emitting when no loaded row needs
        # that relationship, so the exact count moves by a statement or two with
        # the shape of the data. What must not happen is growth *proportional*
        # to tiles: one query per tile would put the deep run ~30 statements
        # above the shallow one, not a handful.
        slack = 5
        assert deep_queries <= shallow_queries + slack, (
            f'hydration scaled with tile count: {shallow_tiles} tiles took '
            f'{shallow_queries} queries, {deep_tiles} tiles took {deep_queries} '
            f'(allowed {shallow_queries + slack}). Something in the card '
            f'serializer is querying per game again.'
        )

    def test_feed_ships_a_window_not_the_whole_row(
        self, app, db_session, hydrate_user, hydrate_library, seed_shelves
    ):
        from oneirodex.routes_discover import build_discover_sections
        from oneirodex.utils.discover_providers import ROW_MAX, ROW_WINDOW

        _add_games(db_session, hydrate_library, ROW_MAX * 2)

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(hydrate_user)

        assert sections, 'expected the seeded shelves to render'
        for row in sections:
            assert len(row['games']) <= ROW_WINDOW, (
                'the feed shipped more than one window of tiles'
            )
            # The window is the head of the row, not the whole of it: the row
            # still reports how deep it goes so the client can page the rest.
            assert row['total_count'] >= len(row['games'])
            assert row['total_count'] <= ROW_MAX


class TestHydrationBatch:
    def test_prime_is_idempotent_and_incremental(
        self, app, db_session, hydrate_user, hydrate_library
    ):
        """Re-priming a game already in the batch must not re-query it.

        Windowed rows depend on this: loading tiles 13-40 primes against the
        same instance, and would otherwise re-fetch the whole feed each page.
        """
        from oneirodex.utils.discover_hydrate import DiscoverHydration

        _add_games(db_session, hydrate_library, 4)

        with app.app_context(), app.test_request_context('/'):
            games = db.session.execute(
                select(Game).filter_by(library_uuid=hydrate_library.uuid)
            ).scalars().all()

            db.session.expire_all()
            hydration = DiscoverHydration(hydrate_user)

            _, first = _count_queries(lambda: hydration.prime(games))
            _, second = _count_queries(lambda: hydration.prime(games))

        assert first > 0, 'priming a fresh batch should hit the database'
        assert second == 0, (
            f're-priming the same games issued {second} queries; prime() is '
            f'meant to skip uuids it has already fetched'
        )

    def test_client_connected_is_resolved_once_per_feed(
        self, app, db_session, hydrate_user, hydrate_library
    ):
        """Companion presence depends on the member, not the game.

        It used to be asked per tile, which was a full ClientDevice query for
        every card on the page and always the same answer.
        """
        from oneirodex.utils.discover_hydrate import DiscoverHydration

        _add_games(db_session, hydrate_library, 3)

        with app.app_context(), app.test_request_context('/'):
            hydration = DiscoverHydration(hydrate_user)
            games = db.session.execute(
                select(Game).filter_by(library_uuid=hydrate_library.uuid)
            ).scalars().all()

            _, queries = _count_queries(
                lambda: [hydration.serializer_kwargs(game) for game in games]
            )

        assert queries == 0, (
            f'building serializer kwargs issued {queries} queries; every value '
            f'it returns is supposed to come from the primed batch'
        )
