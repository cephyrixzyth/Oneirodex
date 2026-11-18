"""Genre hub assembly — virtual Discover rows, not admin sections."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from oneirodex.models import Game, Genre, Library, User, UserGameProgress, user_favorites
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.discover_hubs import build_genre_hub, catalog_href_for_genre, resolve_genre

NOW = datetime.now(timezone.utc)


def _user(db_session, tag='h'):
    user = User(
        name=f'{tag}_{uuid4().hex[:8]}',
        email=f'{tag}_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


def _library(db_session):
    library = Library(
        name=f'Hub {uuid4().hex[:6]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


def _genre(db_session, name):
    genre = Genre(name=name)
    db_session.add(genre)
    db_session.commit()
    return genre


def _game(db_session, library, name, genre, *, days_ago=0, rating=70.0):
    game = Game(
        name=name,
        summary='s',
        rating=rating,
        date_created=NOW.replace(tzinfo=None) - timedelta(days=days_ago),
        library_uuid=library.uuid,
    )
    db_session.add(game)
    db_session.flush()
    game.genres.append(genre)
    db_session.commit()
    return game


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_resolve_genre_is_case_insensitive(db_session):
    name = f'Roguelike {uuid4().hex[:6]}'
    genre = _genre(db_session, name)
    found = resolve_genre(name.lower())
    assert found is not None
    assert found.id == genre.id


def test_build_genre_hub_unknown_is_none(db_session):
    user = _user(db_session)
    assert build_genre_hub(user, 'no-such-genre-zzzz') is None


def test_build_genre_hub_hides_empty_rows_and_splits_unplayed(
    db_session, global_settings,
):
    user = _user(db_session, 'hub')
    library = _library(db_session)
    genre = _genre(db_session, f'Puzzle {uuid4().hex[:6]}')
    unplayed = _game(db_session, library, f'Unplayed {uuid4().hex[:6]}', genre, days_ago=2)
    played = _game(db_session, library, f'Played {uuid4().hex[:6]}', genre, days_ago=1)
    db_session.add(
        UserGameProgress(
            user_id=user.id,
            game_uuid=played.uuid,
            total_seconds=120,
            session_count=1,
            last_played_at=NOW,
        )
    )
    db_session.execute(
        user_favorites.insert().values(user_id=user.id, game_uuid=played.uuid)
    )
    db_session.commit()

    hub = build_genre_hub(user, genre.name)
    assert hub is not None
    assert hub['genre'] == genre.name
    assert hub['catalog_href'] == catalog_href_for_genre(genre)
    by_id = {row['identifier'].rsplit(':', 1)[-1]: row for row in hub['sections']}
    assert 'unplayed' in by_id
    names = [game['name'] for game in by_id['unplayed']['games']]
    assert unplayed.name in names
    assert played.name not in names
    assert 'loved' in by_id
    loved_names = [game['name'] for game in by_id['loved']['games']]
    assert played.name in loved_names
    assert 'newest' in by_id


def test_genre_hub_api_404_and_ok(client, db_session, configured_install, global_settings):
    user = _user(db_session, 'api')
    library = _library(db_session)
    genre = _genre(db_session, f'Action {uuid4().hex[:6]}')
    _game(db_session, library, f'Hub API {uuid4().hex[:6]}', genre)
    _login(client, user)

    missing = client.get('/api/discover/hubs/genre/no-such-genre-zzzz')
    assert missing.status_code == 404
    body = missing.get_json()
    assert body['ok'] is False
    assert body['error_code'] == 'not_found'

    ok = client.get(f'/api/discover/hubs/genre/{genre.name}')
    assert ok.status_code == 200
    payload = ok.get_json()
    assert payload['ok'] is True
    assert payload['genre'] == genre.name
    assert payload['sections']


