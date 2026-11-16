"""Member batch mutation errors never serialize database exception details."""

import inspect
from types import SimpleNamespace

from flask import Flask

from oneirodex.routes_apis import game_batch
from oneirodex.schemas.game import BatchFavoriteBody


def _private_database_error():
    return RuntimeError('postgres://private-user:private-password@db/private-db')


def _raise_private_database_error():
    raise _private_database_error()


class _QueryResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, execute_results=()):
        self.execute_results = iter(execute_results)

    def execute(self, _statement):
        result = next(self.execute_results)
        if isinstance(result, Exception):
            raise result
        return _QueryResult(result)

    def add(self, _row):
        pass

    def flush(self):
        raise _private_database_error()

    def commit(self):
        pass

    def rollback(self):
        pass


class _BrokenFavorites:
    def append(self, _game):
        raise _private_database_error()


def test_member_batch_item_errors_redact_database_details(monkeypatch):
    app = Flask(__name__)
    game = SimpleNamespace(
        uuid='game-a', name='Game A', igdb_id=42,
        freshness_checked_at=None, freshness_status=None,
        updates=[], extras=[], urls=[],
    )
    user = SimpleNamespace(id=7, role='user', favorites=_BrokenFavorites())
    monkeypatch.setattr(game_batch, 'current_user', user)
    monkeypatch.setattr(game_batch, 'user_can_access_game', lambda *_args: True)
    monkeypatch.setattr(game_batch, 'can_request_games', lambda *_args: True)

    def invoke(raw, path, payload, session, *, favorite=False):
        monkeypatch.setattr(game_batch, 'db', SimpleNamespace(session=session))
        with app.test_request_context(path, method='POST', json=payload):
            if favorite:
                body = BatchFavoriteBody.model_validate(payload)
                return raw(body=body)
            return raw()

    favorite_result = invoke(
        inspect.unwrap(game_batch.games_batch_favorite),
        '/api/games/batch/favorite',
        {'uuids': ['game-a'], 'favorite': True},
        _Session(([game], [])),
        favorite=True,
    )
    status_result = invoke(
        inspect.unwrap(game_batch.games_batch_status),
        '/api/games/batch/status',
        {'uuids': ['game-a'], 'status': 'completed'},
        _Session(([game], [], _private_database_error())),
    )
    wishlist_result = invoke(
        inspect.unwrap(game_batch.games_batch_wishlist),
        '/api/games/batch/wishlist',
        {'uuids': ['game-a']},
        _Session(([game], [])),
    )
    monkeypatch.setattr(
        'oneirodex.utils.freshness.check_and_store_freshness',
        lambda *_args, **_kwargs: _raise_private_database_error(),
    )
    freshness_result = invoke(
        inspect.unwrap(game_batch.games_batch_freshness_check),
        '/api/games/batch/freshness/check',
        {'uuids': ['game-a'], 'only_stale': False},
        _Session(([game],)),
    )
    monkeypatch.setattr(
        game_batch,
        'run_in_background',
        lambda *_args, **_kwargs: _raise_private_database_error(),
    )
    image_result = invoke(
        inspect.unwrap(game_batch.games_batch_refresh_images),
        '/api/games/batch/refresh_images',
        {'uuids': ['game-a']},
        _Session(([game],)),
    )

    expected = (
        (favorite_result, 'Could not update favorite'),
        (status_result, 'Could not update play status'),
        (wishlist_result, 'Could not create request'),
        (freshness_result, 'Could not check this title'),
        (image_result, 'Could not queue the image refresh'),
    )
    for response, message in expected:
        if isinstance(response, tuple):
            response = response[0]
        payload = response.get_json()
        assert payload['errors'][0]['uuid'] == 'game-a'
        assert payload['errors'][0]['error'] == message
        assert 'private-password' not in response.get_data(as_text=True)
        assert 'postgres://' not in response.get_data(as_text=True)
