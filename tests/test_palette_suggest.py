"""On-box palette empty-state: recently played + household favourites."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from oneirodex.models import Game, Library, User, UserGameProgress, user_favorites
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_acl import set_user_library_allowlist
from oneirodex.utils.palette_suggest import clamp_suggest_limit, palette_suggest

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


def _library(db_session, platform=LibraryPlatform.PCWIN):
    library = Library(
        name=f'Palette {uuid4().hex[:6]}',
        platform=platform,
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


def _favorite(db_session, user, game):
    db_session.execute(
        user_favorites.insert().values(user_id=user.id, game_uuid=game.uuid)
    )
    db_session.commit()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_clamp_suggest_limit():
    assert clamp_suggest_limit(None) == 8
    assert clamp_suggest_limit('nope') == 8
    assert clamp_suggest_limit(0) == 1
    assert clamp_suggest_limit(99) == 12


def test_palette_suggest_recent_then_popular_without_overlap(db_session):
    member = _user(db_session, 'member')
    library = _library(db_session)
    played = _game(db_session, library, f'Played {uuid4().hex[:6]}')
    fav_only = _game(db_session, library, f'Fav {uuid4().hex[:6]}')
    _played(db_session, member, played)
    _favorite(db_session, member, played)
    _favorite(db_session, member, fav_only)

    body = palette_suggest(member, limit=8)
    recent_uuids = [row['uuid'] for row in body['recent']]
    popular_uuids = [row['uuid'] for row in body['popular']]
    assert played.uuid in recent_uuids
    assert fav_only.uuid in popular_uuids
    assert played.uuid not in popular_uuids
    assert all(row['hint'] == 'Played recently' for row in body['recent'])
    assert all(row['hint'] == 'Favorited here' for row in body['popular'])


def test_palette_suggest_hides_titles_the_member_cannot_access(db_session):
    member = _user(db_session, 'kid')
    member.role = 'child'
    db_session.commit()
    visible = _library(db_session)
    hidden = _library(db_session, LibraryPlatform.NES)
    seen = _game(db_session, visible, f'Seen {uuid4().hex[:6]}')
    secret = _game(db_session, hidden, f'Secret {uuid4().hex[:6]}')
    _played(db_session, member, seen)
    _played(db_session, member, secret)
    _favorite(db_session, member, secret)
    set_user_library_allowlist(member.id, [visible.uuid])
    db_session.commit()

    body = palette_suggest(member, limit=8)
    uuids = {row['uuid'] for row in body['recent'] + body['popular']}
    assert seen.uuid in uuids
    assert secret.uuid not in uuids
