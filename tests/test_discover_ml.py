"""The on-box recommender: taste profile, similarity, impressions, rotation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import (
    DiscoverySection,
    Game,
    Genre,
    Library,
    Theme,
    User,
    UserGameProgress,
    UserTasteFacet,
    user_favorites,
)
from oneirodex.platform import LibraryPlatform

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- discover ML row generation over the member set.

NOW = datetime.now(timezone.utc)


@pytest.fixture
def ml_user(db_session):
    user = User(
        name=f'ml_{uuid4().hex[:8]}',
        email=f'ml_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def ml_library(db_session):
    library = Library(name=f'ML {uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def genres(db_session):
    made = []
    for name in (f'MLGenreA-{uuid4().hex[:6]}', f'MLGenreB-{uuid4().hex[:6]}'):
        genre = Genre(name=name)
        db_session.add(genre)
        made.append(genre)
    db_session.commit()
    return made


def _game(db_session, library, name, *, genres=(), themes=(), rating=None):
    game = Game(name=name, summary='s', library_uuid=library.uuid, rating=rating)
    game.genres = list(genres)
    game.themes = list(themes)
    db_session.add(game)
    db_session.commit()
    return game


def _favorite(db_session, user, game):
    db_session.execute(
        user_favorites.insert().values(user_id=user.id, game_uuid=game.uuid)
    )
    db_session.commit()


def _play(db_session, user, game, *, hours=1.0, days_ago=0):
    db_session.add(
        UserGameProgress(
            user_id=user.id,
            game_uuid=game.uuid,
            total_seconds=int(hours * 3600),
            session_count=1,
            last_played_at=NOW - timedelta(days=days_ago),
        )
    )
    db_session.commit()


class TestTasteProfile:
    def test_a_member_with_no_signal_has_no_profile(self, app, ml_user):
        from oneirodex.utils.discover_ml.profile import build_profile

        with app.app_context():
            assert build_profile(ml_user.id) == {}

    def test_favouriting_a_game_weights_its_genres(
        self, app, db_session, ml_user, ml_library, genres
    ):
        from oneirodex.utils.discover_ml.profile import build_profile

        loved = _game(db_session, ml_library, 'Loved', genres=[genres[0]])
        _favorite(db_session, ml_user, loved)

        profile = build_profile(ml_user.id)

        assert profile.get(('genre', genres[0].id), 0) > 0
        assert ('genre', genres[1].id) not in profile

    def test_playtime_is_scaled_logarithmically(
        self, app, db_session, ml_user, ml_library, genres
    ):
        """One 400-hour obsession must not drown out a broader taste."""
        from oneirodex.utils.discover_ml.profile import collect_signals

        modest = _game(db_session, ml_library, 'Modest', genres=[genres[0]])
        obsession = _game(db_session, ml_library, 'Obsession', genres=[genres[1]])
        _play(db_session, ml_user, modest, hours=10)
        _play(db_session, ml_user, obsession, hours=400)

        scores = collect_signals(ml_user.id)

        # 40x the hours, nothing like 40x the score.
        assert scores[obsession.uuid] < scores[modest.uuid] * 3

    def test_older_signals_weigh_less(
        self, app, db_session, ml_user, ml_library, genres
    ):
        from oneirodex.utils.discover_ml.profile import collect_signals

        recent = _game(db_session, ml_library, 'Recent', genres=[genres[0]])
        stale = _game(db_session, ml_library, 'Stale', genres=[genres[1]])
        _play(db_session, ml_user, recent, hours=10, days_ago=0)
        _play(db_session, ml_user, stale, hours=10, days_ago=365)

        scores = collect_signals(ml_user.id)

        assert scores[recent.uuid] > scores[stale.uuid]

    def test_the_profile_round_trips_through_storage(
        self, app, db_session, ml_user, ml_library, genres
    ):
        from oneirodex.utils.discover_ml.profile import load_profile, rebuild_profile

        loved = _game(db_session, ml_library, 'Stored', genres=[genres[0]])
        _favorite(db_session, ml_user, loved)

        written = rebuild_profile(ml_user.id)
        assert written > 0
        assert load_profile(ml_user.id).get(('genre', genres[0].id), 0) > 0

    def test_a_rebuild_replaces_rather_than_merges(
        self, app, db_session, ml_user, ml_library, genres
    ):
        """A facet that drops out of a taste must disappear, not linger."""
        from oneirodex.utils.discover_ml.profile import rebuild_profile

        loved = _game(db_session, ml_library, 'Was Loved', genres=[genres[0]])
        _favorite(db_session, ml_user, loved)
        rebuild_profile(ml_user.id)

        db_session.execute(
            user_favorites.delete().where(user_favorites.c.user_id == ml_user.id)
        )
        db_session.commit()
        rebuild_profile(ml_user.id)

        remaining = db.session.execute(
            select(UserTasteFacet).where(UserTasteFacet.user_id == ml_user.id)
        ).scalars().all()
        assert remaining == []


class TestContentSimilarity:
    def test_titles_sharing_facets_are_neighbours(
        self, app, db_session, ml_library, genres
    ):
        from oneirodex.utils.discover_ml.similarity import content_neighbours

        one = _game(db_session, ml_library, 'Alike One', genres=[genres[0]])
        two = _game(db_session, ml_library, 'Alike Two', genres=[genres[0]])
        apart = _game(db_session, ml_library, 'Apart', genres=[genres[1]])

        neighbours = content_neighbours([one.uuid, two.uuid, apart.uuid])

        assert two.uuid in dict(neighbours.get(one.uuid, []))
        assert apart.uuid not in dict(neighbours.get(one.uuid, []))

    def test_a_title_with_no_facets_has_no_neighbours(
        self, app, db_session, ml_library
    ):
        from oneirodex.utils.discover_ml.similarity import content_neighbours

        bare = _game(db_session, ml_library, 'Bare')

        assert content_neighbours([bare.uuid]).get(bare.uuid) is None

    def test_overlap_is_normalised_by_union(
        self, app, db_session, ml_library, genres
    ):
        """Jaccard, so a title tagged with everything is not everyone's neighbour."""
        from oneirodex.utils.discover_ml.similarity import content_neighbours

        theme = Theme(name=f'MLTheme-{uuid4().hex[:6]}')
        db_session.add(theme)
        db_session.commit()

        precise = _game(db_session, ml_library, 'Precise', genres=[genres[0]])
        twin = _game(db_session, ml_library, 'Twin', genres=[genres[0]])
        broad = _game(
            db_session, ml_library, 'Broad',
            genres=[genres[0], genres[1]], themes=[theme],
        )

        neighbours = dict(
            content_neighbours([precise.uuid, twin.uuid, broad.uuid]).get(precise.uuid, [])
        )

        assert neighbours[twin.uuid] > neighbours[broad.uuid]


class TestCollaborativeFloor:
    def test_a_small_install_does_not_run_collaborative_filtering(self, app):
        """With a handful of members, co-occurrence is noise wearing a lab coat."""
        from oneirodex.utils.discover_ml.similarity import collab_is_meaningful

        with app.app_context():
            # The shared test database is nowhere near 25 members with real
            # play history, which is exactly the situation this guards.
            assert collab_is_meaningful() is False

    def test_neighbours_fall_back_to_content_below_the_floor(
        self, app, db_session, ml_library, genres
    ):
        from oneirodex.utils.discover_ml import similarity

        one = _game(db_session, ml_library, 'Fallback One', genres=[genres[0]])
        two = _game(db_session, ml_library, 'Fallback Two', genres=[genres[0]])

        similarity.store_neighbours(
            'content', similarity.content_neighbours([one.uuid, two.uuid])
        )
        blended = dict(similarity.neighbours_of(one.uuid))

        assert two.uuid in blended
        assert blended[two.uuid] > 0

    def test_collab_neighbours_are_empty_below_the_floor(self, app):
        from oneirodex.utils.discover_ml.similarity import collab_neighbours

        with app.app_context():
            assert collab_neighbours() == {}


class TestImpressionDamping:
    def test_a_title_never_shown_is_not_damped(self, app, ml_user):
        from oneirodex.utils.discover_ml.impressions import damping_for

        with app.app_context():
            assert damping_for(ml_user.id) == {}

    def test_repeated_impressions_damp_a_title(
        self, app, db_session, ml_user, ml_library
    ):
        from oneirodex.utils.discover_ml.impressions import (
            damping_for,
            record_impressions,
        )

        ignored = _game(db_session, ml_library, 'Ignored')
        for _ in range(6):
            record_impressions(ml_user.id, [ignored.uuid])

        damping = damping_for(ml_user.id)

        assert 0 < damping[ignored.uuid] < 1

    def test_damping_has_a_floor(self, app, db_session, ml_user, ml_library):
        """A member who ignored everything should still get a feed."""
        from oneirodex.utils.discover_ml.impressions import (
            MIN_DAMPING,
            damping_for,
            record_impressions,
        )

        ignored = _game(db_session, ml_library, 'Very Ignored')
        for _ in range(50):
            record_impressions(ml_user.id, [ignored.uuid])

        assert damping_for(ml_user.id)[ignored.uuid] >= MIN_DAMPING


    def test_recording_the_same_feed_twice_counts_twice(
        self, app, db_session, ml_user, ml_library
    ):
        from oneirodex.utils.discover_ml.impressions import record_impressions
        from oneirodex.models import UserDiscoverImpression

        shown = _game(db_session, ml_library, 'Counted')
        record_impressions(ml_user.id, [shown.uuid])
        record_impressions(ml_user.id, [shown.uuid])

        row = db.session.execute(
            select(UserDiscoverImpression).where(
                UserDiscoverImpression.user_id == ml_user.id,
                UserDiscoverImpression.game_uuid == shown.uuid,
            )
        ).scalar_one()
        assert row.shown_count == 2

    def test_a_duplicated_uuid_in_one_feed_counts_once(
        self, app, db_session, ml_user, ml_library
    ):
        """An exempt row can legitimately repeat a title the feed already had."""
        from oneirodex.utils.discover_ml.impressions import record_impressions
        from oneirodex.models import UserDiscoverImpression

        shown = _game(db_session, ml_library, 'Repeated In One Feed')
        record_impressions(ml_user.id, [shown.uuid, shown.uuid, shown.uuid])

        row = db.session.execute(
            select(UserDiscoverImpression).where(
                UserDiscoverImpression.user_id == ml_user.id,
                UserDiscoverImpression.game_uuid == shown.uuid,
            )
        ).scalar_one()
        assert row.shown_count == 1


class TestRanking:
    def test_no_profile_leaves_the_callers_order_alone(
        self, app, db_session, ml_user, ml_library
    ):
        """A ranking built on nothing is worse than the simple answer."""
        from oneirodex.utils.discover_ml.scoring import rank_candidates

        games = [_game(db_session, ml_library, f'Unranked {i}') for i in range(3)]

        assert [g.uuid for g in rank_candidates(ml_user.id, games)] == [
            g.uuid for g in games
        ]

    def test_taste_beats_a_higher_rating(
        self, app, db_session, ml_user, ml_library, genres
    ):
        """The quality prior nudges; it must not overrule affinity."""
        from oneirodex.utils.discover_ml.profile import rebuild_profile
        from oneirodex.utils.discover_ml.scoring import rank_candidates

        loved = _game(db_session, ml_library, 'Taste Anchor', genres=[genres[0]])
        _favorite(db_session, ml_user, loved)
        rebuild_profile(ml_user.id)

        in_taste = _game(
            db_session, ml_library, 'In Taste', genres=[genres[0]], rating=60.0
        )
        acclaimed = _game(
            db_session, ml_library, 'Acclaimed Elsewhere', genres=[genres[1]], rating=99.0
        )

        ranked = rank_candidates(ml_user.id, [acclaimed, in_taste])

        assert ranked[0].uuid == in_taste.uuid

    def test_anchors_come_from_what_was_really_played(
        self, app, db_session, ml_user, ml_library
    ):
        """A row anchored on something you bounced off reads as a misunderstanding."""
        from oneirodex.utils.discover_ml.scoring import top_anchors

        bounced = _game(db_session, ml_library, 'Bounced Off')
        sunk = _game(db_session, ml_library, 'Hours Sunk')
        _play(db_session, ml_user, bounced, hours=0.2)
        _play(db_session, ml_user, sunk, hours=80)

        anchors = top_anchors(ml_user.id, limit=1)

        assert [a.uuid for a in anchors] == [sunk.uuid]


class TestGeneratedRows:
    @pytest.fixture(autouse=True)
    def because_shelf(self, db_session):
        section = db.session.execute(
            select(DiscoverySection).filter_by(identifier='because_you_played')
        ).scalar_one_or_none()
        if section is None:
            section = DiscoverySection(
                identifier='because_you_played',
                name='Because You Played',
                display_order=8,
            )
            db_session.add(section)
        section.is_visible = True
        section.starts_at = None
        section.ends_at = None
        db_session.commit()
        return section

    def test_the_template_section_is_not_itself_a_row(self, app, because_shelf):
        from oneirodex.utils.discover_providers import resolve_section

        with app.app_context():
            assert resolve_section(because_shelf) is None

    def test_a_generated_row_states_its_anchor(
        self, app, db_session, ml_user, ml_library
    ):
        from oneirodex.utils.discover_providers import generated_rows

        anchor = _game(db_session, ml_library, 'The Anchor')
        _play(db_session, ml_user, anchor, hours=50)

        rows = generated_rows(ml_user, because_shelf_section())

        assert rows
        assert rows[0].spec.reason == 'Because you played The Anchor'
        assert rows[0].spec.family == 'ml'

    def test_a_member_who_played_nothing_generates_no_rows(
        self, app, ml_user
    ):
        from oneirodex.utils.discover_providers import generated_rows

        with app.app_context():
            assert generated_rows(ml_user, because_shelf_section()) == []

    def test_hiding_the_template_makes_generated_rows_unreachable(
        self, app, db_session, ml_user, ml_library, because_shelf
    ):
        """The switch an admin sees has to actually switch the family off."""
        from oneirodex.utils.discover_providers import resolve_identifier

        anchor = _game(db_session, ml_library, 'Hidden Family Anchor')
        because_shelf.is_visible = False
        db_session.commit()

        with app.app_context():
            assert resolve_identifier(f'because_you_played:{anchor.uuid}') is None

    def test_a_generated_row_resolves_by_identifier_when_visible(
        self, app, db_session, ml_user, ml_library, because_shelf
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        anchor = _game(db_session, ml_library, 'Resolvable Anchor')

        with app.app_context():
            row = resolve_identifier(f'because_you_played:{anchor.uuid}')

        assert row is not None
        assert row.spec.family == 'ml'

    def test_an_anchor_that_no_longer_exists_resolves_to_nothing(
        self, app, because_shelf
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            assert resolve_identifier(f'because_you_played:{uuid4()}') is None


def because_shelf_section():
    return db.session.execute(
        select(DiscoverySection).filter_by(identifier='because_you_played')
    ).scalar_one()


class TestRebuildJob:
    def test_a_rebuild_reports_what_it_did(self, app, db_session, ml_library, genres, configured_install):
        from oneirodex.utils.discover_ml.job import rebuild_all

        _game(db_session, ml_library, 'Job One', genres=[genres[0]])
        _game(db_session, ml_library, 'Job Two', genres=[genres[0]])

        stats = rebuild_all()

        assert stats['members'] >= 1
        assert stats['content_pairs'] >= 2
        # Below the floor on any realistic self-hosted install.
        assert stats['collab_ran'] is False
