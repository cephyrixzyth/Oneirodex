"""The personal, social, update and news rows added in Phase 2."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import (
    Announcement,
    DiscoverySection,
    FreeGameOffer,
    Game,
    GameExtra,
    GameUpdate,
    Library,
    User,
    UserFriendship,
    UserGameProgress,
    UserPreference,
    user_favorites,
)
from oneirodex.platform import LibraryPlatform

NOW = datetime.now(timezone.utc)


def _user(db_session, tag='p'):
    user = User(
        name=f'{tag}_{uuid4().hex[:8]}',
        email=f'{tag}_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member(db_session):
    return _user(db_session, 'member')


PERSONAL_SHELVES = {
    'continue_playing': ('Continue Playing', -40),
    'friends_playing': ('Friends Are Playing', -30),
    'game_updates': ('Recently Updated Files', -20),
    'news': ('News', -10),
}


@pytest.fixture(autouse=True)
def personal_shelves(db_session):
    """Ensure the Phase 2 shelves exist and are visible.

    A row resolves through its `DiscoverySection`, so on a database seeded
    before these shelves existed they resolve to nothing. Startup seeding adds
    them to a real install; this fixture does the same for the test database.
    """
    for identifier, (name, order) in PERSONAL_SHELVES.items():
        section = db.session.execute(
            select(DiscoverySection).filter_by(identifier=identifier)
        ).scalar_one_or_none()
        if section is None:
            section = DiscoverySection(
                identifier=identifier, name=name, display_order=order
            )
            db_session.add(section)
        section.is_visible = True
        section.starts_at = None
        section.ends_at = None
    db_session.commit()


@pytest.fixture
def personal_library(db_session):
    library = Library(
        name=f'Personal {uuid4().hex[:6]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, library, name):
    game = Game(name=name, summary='s', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()
    return game


def _played(db_session, user, game, *, minutes_ago=1):
    db_session.add(
        UserGameProgress(
            user_id=user.id,
            game_uuid=game.uuid,
            total_seconds=600,
            session_count=1,
            last_played_at=NOW - timedelta(minutes=minutes_ago),
        )
    )
    db_session.commit()


def _befriend(db_session, a, b):
    db_session.add(
        UserFriendship(user_id=a.id, friend_user_id=b.id, status='accepted')
    )
    db_session.commit()


def _share_activity(db_session, user, value):
    prefs = db.session.execute(
        select(UserPreference).filter_by(user_id=user.id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = UserPreference(user_id=user.id)
        db_session.add(prefs)
    prefs.share_activity = value
    db_session.commit()


class TestContinuePlaying:
    def test_lists_what_the_member_played_most_recently_first(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        older = _game(db_session, personal_library, 'Played Earlier')
        newer = _game(db_session, personal_library, 'Played Just Now')
        _played(db_session, member, older, minutes_ago=600)
        _played(db_session, member, newer, minutes_ago=1)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('continue_playing')
            games = row.select(member, 10)

        names = [game.name for game in games]
        assert names[:2] == ['Played Just Now', 'Played Earlier']

    def test_is_exempt_from_cross_row_dedupe(self, app):
        """What you are actually playing belongs here even if it is elsewhere."""
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            row = resolve_identifier('continue_playing')
            assert row.spec.dedupe_mode == 'exempt'

    def test_another_members_playing_does_not_leak_in(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        stranger = _user(db_session, 'stranger')
        theirs = _game(db_session, personal_library, 'Not Mine')
        _played(db_session, stranger, theirs)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('continue_playing')
            games = row.select(member, 10)

        assert 'Not Mine' not in [game.name for game in games]


class TestFriendsPlaying:
    def test_shows_what_an_accepted_friend_played(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        friend = _user(db_session, 'friend')
        _befriend(db_session, member, friend)
        game = _game(db_session, personal_library, 'Friend Favourite')
        _played(db_session, friend, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Friend Favourite' in [game.name for game in games]

    def test_friendship_is_found_from_either_direction(
        self, app, db_session, member, personal_library
    ):
        """A friendship row records who asked, not who is whose friend."""
        from oneirodex.utils.discover_providers import resolve_identifier

        friend = _user(db_session, 'asker')
        # The friend sent the request, so the member is the *target* row.
        _befriend(db_session, friend, member)
        game = _game(db_session, personal_library, 'Reverse Friendship')
        _played(db_session, friend, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Reverse Friendship' in [game.name for game in games]

    def test_a_stranger_is_not_a_friend(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        stranger = _user(db_session, 'stranger')
        game = _game(db_session, personal_library, 'Stranger Game')
        _played(db_session, stranger, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Stranger Game' not in [game.name for game in games]

    def test_a_pending_request_is_not_a_friendship(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        pending = _user(db_session, 'pending')
        db_session.add(
            UserFriendship(
                user_id=member.id, friend_user_id=pending.id, status='pending'
            )
        )
        db_session.commit()
        game = _game(db_session, personal_library, 'Pending Game')
        _played(db_session, pending, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Pending Game' not in [game.name for game in games]

    def test_a_friend_who_opted_out_is_not_shown(
        self, app, db_session, member, personal_library
    ):
        """The opt-out is the whole point of the preference."""
        from oneirodex.utils.discover_providers import resolve_identifier

        friend = _user(db_session, 'private')
        _befriend(db_session, member, friend)
        _share_activity(db_session, friend, False)
        game = _game(db_session, personal_library, 'Private Game')
        _played(db_session, friend, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Private Game' not in [game.name for game in games]

    def test_a_friend_with_no_preferences_row_still_counts_as_sharing(
        self, app, db_session, member, personal_library
    ):
        """Absence is not an opt-out. Only an explicit False is."""
        from oneirodex.utils.discover_providers import resolve_identifier

        friend = _user(db_session, 'nodefaults')
        _befriend(db_session, member, friend)
        assert db.session.execute(
            select(UserPreference).filter_by(user_id=friend.id)
        ).scalar_one_or_none() is None

        game = _game(db_session, personal_library, 'Default Sharing Game')
        _played(db_session, friend, game)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 10)

        assert 'Default Sharing Game' in [game.name for game in games]

    def test_two_friends_on_one_title_is_one_tile(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        one = _user(db_session, 'f1')
        two = _user(db_session, 'f2')
        _befriend(db_session, member, one)
        _befriend(db_session, member, two)
        game = _game(db_session, personal_library, 'Shared Obsession')
        _played(db_session, one, game, minutes_ago=30)
        _played(db_session, two, game, minutes_ago=5)

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            games = row.select(member, 20)

        names = [game.name for game in games]
        assert names.count('Shared Obsession') == 1

    def test_no_friends_means_an_empty_row_not_an_error(
        self, app, db_session, member
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('friends_playing')
            assert row.select(member, 10) == []


class TestGameUpdates:
    def test_orders_by_the_most_recent_update_file(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        stale = _game(db_session, personal_library, 'Patched Long Ago')
        fresh = _game(db_session, personal_library, 'Patched Today')
        db_session.add(
            GameUpdate(
                game_uuid=stale.uuid,
                file_path='/x/old.bin',
                created_at=NOW - timedelta(days=30),
            )
        )
        db_session.add(
            GameUpdate(
                game_uuid=fresh.uuid,
                file_path='/x/new.bin',
                created_at=NOW - timedelta(minutes=5),
            )
        )
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('game_updates')
            games = row.select(member, 100)

        # By uuid, not name. This row is library-wide, so it also returns
        # whatever else on the box has update files — including same-named rows
        # left by an earlier run, since this suite's database is not rolled back
        # between tests.
        uuids = [game.uuid for game in games]
        assert fresh.uuid in uuids and stale.uuid in uuids
        assert uuids.index(fresh.uuid) < uuids.index(stale.uuid)

    def test_a_title_with_several_updates_appears_once(
        self, app, db_session, member, personal_library
    ):
        from oneirodex.utils.discover_providers import resolve_identifier

        game = _game(db_session, personal_library, 'Much Patched')
        for i in range(3):
            db_session.add(
                GameUpdate(
                    game_uuid=game.uuid,
                    file_path=f'/x/p{i}.bin',
                    created_at=NOW - timedelta(days=i),
                )
            )
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('game_updates')
            games = row.select(member, 100)

        assert [g.uuid for g in games].count(game.uuid) == 1


class TestNewsRow:
    def test_carries_articles_rather_than_games(self, app):
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            row = resolve_identifier('news')
            assert row.spec.item_kind == 'articles'

    def test_published_announcements_appear(self, app, db_session, member):
        from oneirodex.utils.discover_providers import resolve_identifier

        db_session.add(
            Announcement(
                title='Server maintenance Sunday',
                body='Back by evening.',
                published=True,
                created_at=NOW,
            )
        )
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('news')
            items = row.select(member, 20)

        titles = [item['title'] for item in items]
        assert 'Server maintenance Sunday' in titles

    def test_unpublished_announcements_do_not(self, app, db_session, member):
        from oneirodex.utils.discover_providers import resolve_identifier

        db_session.add(
            Announcement(
                title='Draft nobody should see',
                body='...',
                published=False,
                created_at=NOW,
            )
        )
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('news')
            items = row.select(member, 20)

        assert 'Draft nobody should see' not in [item['title'] for item in items]

    def test_an_expired_giveaway_is_dropped(self, app, db_session, member):
        """A "free now" row showing a finished giveaway is worse than a short row."""
        from oneirodex.utils.discover_providers import resolve_identifier

        db_session.add(
            FreeGameOffer(
                store='epic',
                external_id=f'exp-{uuid4().hex[:8]}',
                title='Giveaway That Ended',
                active=True,
                ends_at=NOW - timedelta(days=2),
                last_seen_at=NOW,
            )
        )
        db_session.add(
            FreeGameOffer(
                store='gog',
                external_id=f'live-{uuid4().hex[:8]}',
                title='Giveaway Still Running',
                active=True,
                ends_at=NOW + timedelta(days=2),
                last_seen_at=NOW,
            )
        )
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            row = resolve_identifier('news')
            titles = [item['title'] for item in row.select(member, 20)]

        assert 'Giveaway Still Running' in titles
        assert 'Giveaway That Ended' not in titles


class TestArticleRowPayload:
    def test_article_rows_ship_items_not_games(
        self, app, db_session, member
    ):
        """`item_kind` says which key to read; sending both would double the payload."""
        from oneirodex.utils.discover_builder import build_discover_row

        db_session.add(
            Announcement(title='Payload shape', body='b', published=True, created_at=NOW)
        )
        section = db.session.execute(
            select(DiscoverySection).filter_by(identifier='news')
        ).scalar_one_or_none()
        if section is None:
            section = DiscoverySection(
                identifier='news', name='News', display_order=-10
            )
            db_session.add(section)
        section.is_visible = True
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            payload = build_discover_row(member, 'news', limit=10)

        assert payload['item_kind'] == 'articles'
        assert 'items' in payload
        assert 'games' not in payload

    def test_game_rows_keep_the_games_key(self, app, db_session, member):
        from oneirodex.utils.discover_builder import build_discover_row

        section = db.session.execute(
            select(DiscoverySection).filter_by(identifier='continue_playing')
        ).scalar_one_or_none()
        if section is None:
            section = DiscoverySection(
                identifier='continue_playing', name='Continue Playing', display_order=-40
            )
            db_session.add(section)
        section.is_visible = True
        db_session.commit()

        with app.app_context(), app.test_request_context('/'):
            payload = build_discover_row(member, 'continue_playing', limit=10)

        assert payload['item_kind'] == 'games'
        assert 'games' in payload
        assert 'items' not in payload

    def test_ranked_rows_state_why_they_are_there(self, app):
        """An unexplained recommendation reads as an ad; a named one reads as a feature."""
        from oneirodex.utils.discover_providers import resolve_identifier

        with app.app_context():
            for identifier in ('continue_playing', 'friends_playing', 'game_updates', 'news'):
                row = resolve_identifier(identifier)
                if row is None:
                    continue
                assert row.spec.reason, f'{identifier} has no reason'


class TestSharingPreference:
    def test_preferences_endpoint_round_trips_share_activity(
        self, app, client, db_session
    ):
        user = _user(db_session, 'prefs')
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        first = client.get('/api/notifications/preferences')
        assert first.status_code == 200
        assert first.get_json()['share_activity'] is True

        client.post(
            '/api/notifications/preferences',
            json={'share_activity': False},
        )

        again = client.get('/api/notifications/preferences')
        assert again.get_json()['share_activity'] is False


def _seed_extras_missing(db_session):
    section = db.session.execute(
        select(DiscoverySection).filter_by(identifier='extras_missing')
    ).scalar_one_or_none()
    if section is None:
        section = DiscoverySection(
            identifier='extras_missing',
            name='Extras not on the vault',
            display_order=-15,
        )
        db_session.add(section)
    section.is_visible = True
    section.starts_at = None
    section.ends_at = None
    db_session.commit()
    return section


class TestExtrasMissing:
    def test_hidden_when_empty(self, app, db_session, member):
        from oneirodex.utils.discover_builder import build_discover_sections

        _seed_extras_missing(db_session)
        with app.app_context():
            ids = [row['identifier'] for row in build_discover_sections(member)]
        assert 'extras_missing' not in ids

    def test_shows_engaged_title_with_absent_file(
        self, app, db_session, member, personal_library, global_settings,
    ):
        from oneirodex.utils.discover_builder import build_discover_sections

        _seed_extras_missing(db_session)
        engaged = Game(
            name=f'Engaged Extra {uuid4().hex[:6]}',
            summary='s',
            library_uuid=personal_library.uuid,
        )
        stranger = Game(
            name=f'Stranger Extra {uuid4().hex[:6]}',
            summary='s',
            library_uuid=personal_library.uuid,
        )
        db_session.add_all([engaged, stranger])
        db_session.flush()
        db_session.add(
            GameExtra(
                game_uuid=engaged.uuid,
                file_path=f'/no/such/extra/{uuid4().hex}',
            )
        )
        db_session.add(
            GameExtra(
                game_uuid=stranger.uuid,
                file_path=f'/also/missing/{uuid4().hex}',
            )
        )
        db_session.execute(
            user_favorites.insert().values(user_id=member.id, game_uuid=engaged.uuid)
        )
        db_session.commit()

        with app.app_context():
            sections = build_discover_sections(member)
        row = next(s for s in sections if s['identifier'] == 'extras_missing')
        names = [game['name'] for game in row['games']]
        assert engaged.name in names
        assert stranger.name not in names
        assert 'sale' not in (row.get('reason') or '').lower()
        assert '%' not in (row.get('reason') or '')

    def test_disc_extras_are_not_acquire_nags(
        self, app, db_session, member, personal_library, global_settings,
    ):
        from oneirodex.utils.discover_builder import build_discover_sections

        _seed_extras_missing(db_session)
        game = Game(
            name=f'Disc Extra {uuid4().hex[:6]}',
            summary='s',
            library_uuid=personal_library.uuid,
        )
        db_session.add(game)
        db_session.flush()
        db_session.add(
            GameExtra(
                game_uuid=game.uuid,
                extra_kind='disc',
                file_path=f'/missing/disc/{uuid4().hex}',
            )
        )
        db_session.execute(
            user_favorites.insert().values(user_id=member.id, game_uuid=game.uuid)
        )
        db_session.commit()

        with app.app_context():
            ids = [row['identifier'] for row in build_discover_sections(member)]
        assert 'extras_missing' not in ids
