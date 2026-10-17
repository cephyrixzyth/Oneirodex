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


def test_favorites_pagination_clamps_page_size_and_preserves_requested_page(monkeypatch):
    from oneirodex.utils import browse_query, global_settings, client_lifecycle

    observed = {}

    def paginate(_query, *, page, per_page, session):
        observed.update(page=page, per_page=per_page)
        return [], 205, 3

    monkeypatch.setattr(browse_query, '_native_paginate', paginate)
    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: None)
    monkeypatch.setattr(client_lifecycle, 'load_lifecycle_map', lambda _user_id: {})

    user = SimpleNamespace(id=37, role='user', is_authenticated=True)
    payload = FavoritesData().payload(
        user, MultiDict([('page', '2'), ('per_page', '1000')]),
    )

    assert observed == {'page': 2, 'per_page': 100}
    assert payload == {'games': [], 'total': 205, 'pages': 3, 'current_page': 2}
