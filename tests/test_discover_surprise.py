"""*Surprise me* and the taste picker (INSP-4b).

The draw has to stay inside the member's taste and outside what they have
already touched -- a surprise that offers back a favourite, or a title they
said no to, is not a surprise, it is not listening.
"""

from __future__ import annotations

import random
from uuid import uuid4

from oneirodex.models import Game, Genre, Library, User, UserTasteFacet, user_game_status
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.discover_ml.surprise import DRAW_WIDTH, pick_surprise, taste_genres
from oneirodex.utils.play_status import WONT_PLAY


def _user(db_session):
    tag = uuid4().hex[:8]
    user = User(
        name=f'sp_{tag}', email=f'sp_{tag}@example.test', password_hash='hashed', role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


def _library(db_session):
    library = Library(name=f'Surprise {uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


def _genre(db_session, stem):
    genre = Genre(name=f'{stem} {uuid4().hex[:6]}')
    db_session.add(genre)
    db_session.commit()
    return genre


def _game(db_session, library, genre, *, rating=70.0):
    game = Game(name=f'G {uuid4().hex[:6]}', summary='s', rating=rating, library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()
    game.genres.append(genre)
    db_session.commit()
    return game


def _taste(db_session, user, genre, weight):
    db_session.add(UserTasteFacet(user_id=user.id, facet_type='genre', facet_id=genre.id, weight=weight))
    db_session.commit()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_the_picker_offers_your_strongest_genres_first(db_session):
    user = _user(db_session)
    faint = _genre(db_session, 'Faint')
    strong = _genre(db_session, 'Strong')
    _taste(db_session, user, faint, 0.5)
    _taste(db_session, user, strong, 4.0)

    assert [genre.id for genre in taste_genres(user.id)] == [strong.id, faint.id]


def test_no_profile_means_no_picker(db_session):
    assert taste_genres(_user(db_session).id) == []


def test_a_genre_draw_stays_in_the_genre_and_skips_what_you_said_no_to(db_session):
    user = _user(db_session)
    library = _library(db_session)
    genre = _genre(db_session, 'Pick')
    refused = _game(db_session, library, genre, rating=99.0)
    wanted = _game(db_session, library, genre, rating=60.0)
    db_session.execute(
        user_game_status.insert().values(user_id=user.id, game_uuid=refused.uuid, status=WONT_PLAY)
    )
    db_session.commit()

    for seed in range(8):
        pick = pick_surprise(user, genre=genre, rng=random.Random(seed))
        assert pick.game is not None
        assert pick.game.uuid == wanted.uuid
        assert genre.name in pick.reason


def test_pressing_again_moves_on(db_session):
    user = _user(db_session)
    library = _library(db_session)
    genre = _genre(db_session, 'Again')
    first = _game(db_session, library, genre, rating=80.0)
    second = _game(db_session, library, genre, rating=70.0)

    pick = pick_surprise(user, genre=genre, exclude=[first.uuid], rng=random.Random(0))
    assert pick.game.uuid == second.uuid


def test_an_exhausted_band_starts_over_rather_than_coming_back_empty(db_session):
    user = _user(db_session)
    library = _library(db_session)
    genre = _genre(db_session, 'Only')
    only = _game(db_session, library, genre)

    pick = pick_surprise(user, genre=genre, exclude=[only.uuid])
    assert pick.game.uuid == only.uuid


def test_the_draw_is_limited_to_the_top_of_the_ranking(db_session):
    user = _user(db_session)
    library = _library(db_session)
    genre = _genre(db_session, 'Band')
    games = [_game(db_session, library, genre, rating=float(100 - i)) for i in range(DRAW_WIDTH + 6)]
    band = {game.uuid for game in games[:DRAW_WIDTH]}

    drawn = {pick_surprise(user, genre=genre, rng=random.Random(seed)).game.uuid for seed in range(60)}
    assert drawn <= band
    assert len(drawn) > 1, 'a draw that always lands on the same title is not a surprise'


def test_nothing_left_is_an_answer_not_an_error(db_session):
    user = _user(db_session)
    genre = _genre(db_session, 'Empty')

    pick = pick_surprise(user, genre=genre)
    assert pick.game is None
    assert genre.name in pick.reason


def test_the_route_returns_a_card_and_the_picker(client, db_session, global_settings):
    user = _user(db_session)
    library = _library(db_session)
    genre = _genre(db_session, 'Route')
    game = _game(db_session, library, genre)
    _taste(db_session, user, genre, 2.0)
    _login(client, user)

    response = client.get(f'/api/discover/surprise?genre={genre.id}')
    assert response.status_code == 200
    body = response.get_json()
    data = body.get('data', body)
    assert data['game']['uuid'] == game.uuid
    assert data['genre'] == {'id': genre.id, 'name': genre.name}
    assert {'id': genre.id, 'name': genre.name} in data['genres']


def test_the_route_refuses_a_genre_that_is_not_an_id(client, db_session):
    _login(client, _user(db_session))
    assert client.get('/api/discover/surprise?genre=platformer').status_code == 400
    assert client.get('/api/discover/surprise?genre=999999999').status_code == 404
