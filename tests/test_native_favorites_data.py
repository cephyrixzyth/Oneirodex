from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

from oneirodex.runtime_native.favorites import FavoritesData


def test_empty_favorites_payload_is_a_normal_empty_page(monkeypatch):
    from oneirodex.utils import browse_query, global_settings, client_lifecycle

    monkeypatch.setattr(browse_query, '_native_paginate', lambda *args, **kwargs: ([], 0, 0))
    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: None)
    monkeypatch.setattr(client_lifecycle, 'load_lifecycle_map', lambda _user_id: {})

    user = SimpleNamespace(id=37, role='user', is_authenticated=True)
    payload = FavoritesData().payload(user, MultiDict())

    assert payload == {'games': [], 'total': 0, 'pages': 0, 'current_page': 1}
