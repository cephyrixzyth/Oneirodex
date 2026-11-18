"""Saying "Won't play" has to mean something (INSP-4, with INSP-21 folded in).

The status has been recordable for a long time and **nothing read it**: a
member could mark a game Won't play and Discover would keep offering it, which
looks like not listening. It was also missing from the batch allow-list, so the
multi-select bar could set four of the five statuses and silently refused the
fifth.
"""

from __future__ import annotations

from uuid import uuid4

from oneirodex import db
from oneirodex.models import Game, Library, User, user_game_status
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.discover_ml.scoring import already_engaged
from oneirodex.utils.play_status import PLAY_STATUS_VALUES, WONT_PLAY


def _user(session):
    tag = uuid4().hex[:8]
    user = User(
        name=f'wp-{tag}', email=f'wp-{tag}@example.com', password_hash='unused',
        role='user', user_id=str(uuid4()), state=True,
    )
    user.set_password('password123')
    session.add(user)
    session.commit()
    return user


def _game(session, library, name):
    game = Game(
        uuid=str(uuid4()),
        name=name,
        library_uuid=library.uuid,
        full_disk_path=f'/test/{uuid4().hex}.nes',
    )
    session.add(game)
    session.flush()
    return game


def _library(session):
    library = Library(uuid=str(uuid4()), name='WontPlay', platform=LibraryPlatform.NES)
    session.add(library)
    session.flush()
    return library


def _mark(session, user, game, status):
    session.execute(
        user_game_status.insert().values(
            user_id=user.id, game_uuid=game.uuid, status=status
        )
    )
    session.flush()


def test_a_title_you_said_no_to_stops_being_recommended(db_session):
    user = _user(db_session)
    library = _library(db_session)
    refused = _game(db_session, library, 'Refused')
    untouched = _game(db_session, library, 'Untouched')
    _mark(db_session, user, refused, WONT_PLAY)

    engaged = already_engaged(user.id)

    assert refused.uuid in engaged
    assert untouched.uuid not in engaged


def test_clearing_a_status_is_not_the_same_as_saying_no(db_session):
    """"No opinion" and "no" are different answers; only one suppresses."""
    user = _user(db_session)
    library = _library(db_session)
    cleared = _game(db_session, library, 'Cleared')
    _mark(db_session, user, cleared, '')

    assert cleared.uuid not in already_engaged(user.id)


def test_another_members_no_does_not_narrow_your_shelves(db_session):
    """The signal is per-member, like every other taste signal."""
    mine = _user(db_session)
    theirs = _user(db_session)
    library = _library(db_session)
    game = _game(db_session, library, 'Shared shelf')
    _mark(db_session, theirs, game, WONT_PLAY)

    assert game.uuid not in already_engaged(mine.id)
    assert game.uuid in already_engaged(theirs.id)


def test_the_vocabulary_has_one_definition():
    from oneirodex.models.catalog import get_status_info

    # The status map that drives icons and labels must not know a value the
    # allow-list refuses, or the UI offers something the API rejects.
    for status in PLAY_STATUS_VALUES:
        if not status:
            continue
        assert get_status_info(status)['label']
