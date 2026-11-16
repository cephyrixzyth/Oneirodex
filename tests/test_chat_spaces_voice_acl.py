"""W23-SOCIAL-1/2 — spaces, invites, and voice room ACL.

The voice-room cases are the regression guard for the finding that
``user_may_join_room`` only sniffed room-name strings, so any authenticated
user could mint a token for any room.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from oneirodex import db
from oneirodex.models import Game, Library, LibraryPlatform, User
from oneirodex.utils.chat_spaces import (
    add_space_member,
    channels_for_space,
    create_channel,
    create_space,
    create_space_invite,
    redeem_space_invite,
    revoke_space_invite,
    spaces_for_user,
    user_can_access_channel,
    user_is_space_member,
)
from oneirodex.utils.livekit_rtc import user_may_join_room, voice_room_name


@pytest.fixture(scope='function', autouse=True)
def clean_spaces(db_session):
    db_session.execute(text('TRUNCATE TABLE chat_space_invites RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE chat_space_members RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE chat_channels RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE chat_spaces RESTART IDENTITY CASCADE'))
    db_session.commit()


def _user(db_session, role='user'):
    uid = str(uuid4())
    user = User(
        name=f'{role}_{uid[:8]}',
        email=f'{role}_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role=role,
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5,
        is_email_verified=True,
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def alice(db_session):
    return _user(db_session)


@pytest.fixture
def bob(db_session):
    return _user(db_session)


@pytest.fixture
def kid(db_session):
    return _user(db_session, role='child')


class TestSpaceMembership:
    def test_household_space_includes_every_non_child(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Household', visibility='household')
            assert user_is_space_member(alice, space) is True
            assert user_is_space_member(bob, space) is True

    def test_invite_space_excludes_non_members(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Raid Night', visibility='invite', created_by_user_id=alice.id)
            assert user_is_space_member(alice, space) is True  # creator owns it
            assert user_is_space_member(bob, space) is False

            add_space_member(space, bob.id)
            assert user_is_space_member(bob, space) is True

    def test_child_blocked_from_non_child_safe_space(self, app, db_session, kid):
        with app.app_context():
            space = create_space(name='Grown-ups', visibility='household', is_child_safe=False)
            assert user_is_space_member(kid, space) is False

    def test_spaces_for_user_hides_invite_spaces(self, app, db_session, alice, bob):
        with app.app_context():
            create_space(name='Household', visibility='household')
            create_space(name='Private', visibility='invite', created_by_user_id=alice.id)

            assert {s.name for s in spaces_for_user(bob)} == {'Household'}
            assert {s.name for s in spaces_for_user(alice)} == {'Household', 'Private'}


class TestSpaceInvites:
    def test_redeem_joins_space(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            invite = create_space_invite(space=space, created_by_user_id=alice.id)

            joined, error = redeem_space_invite(invite.token, bob)
            assert error is None
            assert joined.id == space.id
            assert user_is_space_member(bob, space) is True

    def test_revoked_and_expired_invites_refused(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)

            revoked = create_space_invite(space=space, created_by_user_id=alice.id)
            revoke_space_invite(revoked)
            _, error = redeem_space_invite(revoked.token, bob)
            assert error is not None
            assert user_is_space_member(bob, space) is False

            expired = create_space_invite(
                space=space,
                created_by_user_id=alice.id,
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            _, error = redeem_space_invite(expired.token, bob)
            assert error is not None

    def test_max_uses_enforced(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            invite = create_space_invite(space=space, created_by_user_id=alice.id, max_uses=1)

            _, first_error = redeem_space_invite(invite.token, bob)
            assert first_error is None

            other = _user(db_session)
            _, second_error = redeem_space_invite(invite.token, other)
            assert second_error is not None
            assert user_is_space_member(other, space) is False

    def test_existing_member_redemption_does_not_consume_invite_use(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            invite = create_space_invite(space=space, created_by_user_id=alice.id, max_uses=2)

            joined, repeat_error = redeem_space_invite(invite.token, alice)
            assert repeat_error is None
            assert joined.id == space.id
            assert invite.uses == 0

            _, first_new_member_error = redeem_space_invite(invite.token, bob)
            assert first_new_member_error is None
            assert invite.uses == 1

            other = _user(db_session)
            _, second_new_member_error = redeem_space_invite(invite.token, other)
            assert second_new_member_error is None
            assert invite.uses == 2

            final_user = _user(db_session)
            _, exhausted_error = redeem_space_invite(invite.token, final_user)
            assert exhausted_error is not None
            assert user_is_space_member(final_user, space) is False

    def test_unknown_token_refused(self, app, db_session, bob):
        with app.app_context():
            _, error = redeem_space_invite('not-a-real-token', bob)
            assert error is not None


class TestVoiceRoomAcl:
    def test_unknown_room_string_denied(self, app, db_session, alice):
        """The core fix — free-text rooms used to mint a token for anyone."""
        with app.app_context():
            assert user_may_join_room(alice, 'some-room-i-made-up') is False
            assert user_may_join_room(alice, 'voice:not-a-number') is False
            assert user_may_join_room(alice, '') is False

    def test_household_lobby_open_to_adults_not_children(self, app, db_session, alice, kid):
        with app.app_context():
            assert user_may_join_room(alice, 'household:lobby') is True
            assert user_may_join_room(kid, 'household:lobby') is False

    def test_voice_channel_requires_space_membership(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            voice = create_channel(space=space, name='Voice', kind='voice')
            room = voice_room_name(voice.id)

            assert user_may_join_room(alice, room) is True
            assert user_may_join_room(bob, room) is False

            add_space_member(space, bob.id)
            assert user_may_join_room(bob, room) is True

    def test_text_channel_id_is_not_a_voice_room(self, app, db_session, alice):
        with app.app_context():
            space = create_space(name='Household', visibility='household')
            text_channel = create_channel(space=space, name='general', kind='channel')
            assert user_may_join_room(alice, voice_room_name(text_channel.id)) is False

    def test_child_blocked_from_non_child_safe_voice_channel(self, app, db_session, kid):
        with app.app_context():
            space = create_space(name='Household', visibility='household')
            voice = create_channel(space=space, name='Late night', kind='voice', is_child_safe=False)
            assert user_may_join_room(kid, voice_room_name(voice.id)) is False


class TestPartyRoomAcl:
    def test_party_room_requires_game_access(self, app, db_session, alice):
        with app.app_context():
            library = Library(name='Party Lib', platform=LibraryPlatform.PCWIN, display_order=1)
            db.session.add(library)
            db.session.flush()
            # `igdb_id` is unique and `db_session` never rolls back (conftest
            # leaves the schema and its rows in place for speed), so a hardcoded
            # value passes once and then fails every later run against the same
            # database. Same idiom as test_library_health_pulse.
            game = Game(
                library_uuid=library.uuid,
                name='Party Game',
                igdb_id=515151 + (uuid4().int % 100000),
            )
            db.session.add(game)
            db.session.commit()

            assert user_may_join_room(alice, f'household:party:{game.uuid}') is True
            assert user_may_join_room(alice, f'household:party:{uuid4()}') is False


class TestChannelListing:
    def test_channels_scoped_to_space_and_kind(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            create_channel(space=space, name='general', kind='channel')
            create_channel(space=space, name='Voice', kind='voice')

            assert len(channels_for_space(alice, space)) == 2
            assert len(channels_for_space(alice, space, kind='voice')) == 1
            # Non-member sees nothing at all.
            assert channels_for_space(bob, space) == []

    def test_user_can_access_channel_follows_space(self, app, db_session, alice, bob):
        with app.app_context():
            space = create_space(name='Private', visibility='invite', created_by_user_id=alice.id)
            channel = create_channel(space=space, name='general', kind='channel')

            assert user_can_access_channel(alice, channel) is True
            assert user_can_access_channel(bob, channel) is False
