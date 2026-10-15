from __future__ import annotations

import sys
from types import SimpleNamespace

from oneirodex.utils import social_projections


def test_community_settings_projection_has_default_label(monkeypatch):
    row = SimpleNamespace(community_chat_url='https://chat.example.test', community_chat_label='')

    class Result:
        def scalars(self):
            return self

        def first(self):
            return row

    import oneirodex

    monkeypatch.setattr(
        oneirodex,
        'db',
        SimpleNamespace(session=SimpleNamespace(execute=lambda _query: Result())),
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.models',
        SimpleNamespace(GlobalSettings=type('GlobalSettings', (), {'id': object()})),
    )
    import sqlalchemy

    class Query:
        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

    monkeypatch.setattr(sqlalchemy, 'select', lambda *_args: Query())

    assert social_projections.community_settings() == {
        'community_chat_url': 'https://chat.example.test',
        'community_chat_label': 'Open community',
    }


def test_user_public_projection_keeps_only_public_presence_fields(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.utils.presence',
        SimpleNamespace(presence_for_user=lambda _user_id, *, viewer: {
            'status': 'playing', 'game_uuid': 'abc', 'game_name': 'Example', 'private': 'hidden',
        }),
    )
    user = SimpleNamespace(id=12, name='player', role='member')

    assert social_projections.user_public(user, viewer=SimpleNamespace(id=1)) == {
        'id': 12,
        'name': 'player',
        'role': 'user',
        'presence': {'status': 'playing', 'game_uuid': 'abc', 'game_name': 'Example'},
    }
