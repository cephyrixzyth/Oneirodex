"""DB-free regression checks for ambiguous IDs and nondestructive repeat sync."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from oneirodex.utils import store_ownership_common as ownership


@pytest.mark.parametrize('candidates,expected', [([], None), (['one'], 'one'), (['one', 'two'], None)])
def test_steam_id_requires_one_library_candidate(monkeypatch, candidates, expected):
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = candidates
    monkeypatch.setattr(ownership, 'db', SimpleNamespace(session=session))
    assert ownership.match_title_to_library_game('steam', '123') == expected
    statement = session.execute.call_args.args[0]
    assert statement.compile().params['steam_app_id_1'] == 123
    assert statement._limit_clause.value == 2


@pytest.mark.parametrize('previous,candidate,expected', [
    ('edition-a', None, 'edition-a'),
    ('edition-a', 'edition-b', 'edition-a'),
    (None, 'edition-b', 'edition-b'),
])
def test_repeat_sync_preserves_mapping_and_scopes_entitlement(monkeypatch, previous, candidate, expected):
    existing = SimpleNamespace(name='old', matched_game_uuid=previous, last_synced_at=None, match_reviewed=False)
    session = MagicMock()
    session.execute.return_value.scalars.return_value.first.return_value = existing
    monkeypatch.setattr(ownership, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(ownership, 'match_title_to_library_game', lambda *args: candidate)
    assert ownership.upsert_owned_title(42, 'steam', '123', 'new name') is existing
    assert existing.matched_game_uuid == expected
    assert existing.name == 'new name'
    assert existing.last_synced_at is not None
    params = session.execute.call_args.args[0].compile().params
    assert params == {'user_id_1': 42, 'store_1': 'steam', 'external_app_id_1': '123'}
    session.add.assert_not_called()
