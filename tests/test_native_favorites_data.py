from types import SimpleNamespace
from uuid import uuid4

from werkzeug.datastructures import MultiDict

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
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


def test_favorites_adapter_filters_denied_child_library_and_total(
    app, client, db_session, configured_install, monkeypatch,
):
    from oneirodex.utils import client_lifecycle, global_settings
    from oneirodex.utils.library_acl import set_user_library_allowlist

    user_key = str(uuid4())
    child = User(
        name=f'fav-child-{user_key[:8]}',
        email=f'fav-child-{user_key[:8]}@example.com',
        password_hash='unused', role='child', user_id=user_key,
        avatarpath='newstyle/avatar_default.jpg', state=True,
    )
    allowed = Library(name=f'Fav allowed {user_key[:8]}', platform=LibraryPlatform.PCWIN)
    denied = Library(name=f'Fav denied {user_key[:8]}', platform=LibraryPlatform.PCWIN)
    visible_game = Game(
        name='Visible Child Favorite',
        full_disk_path=f'/tmp/fav-child-visible-{user_key}', library=allowed,
    )
    hidden_game = Game(
        name='Hidden Child Favorite',
        full_disk_path=f'/tmp/fav-child-hidden-{user_key}', library=denied,
    )
    child.favorites.extend([visible_game, hidden_game])
    db_session.add(child)
    db_session.commit()
    set_user_library_allowlist(child.id, [allowed.uuid])
    db_session.commit()

    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: None)
    monkeypatch.setattr(client_lifecycle, 'load_lifecycle_map', lambda _user_id: {})

    from oneirodex.runtime_native.runtime_context import runtime_config_scope

    with app.app_context(), runtime_config_scope(app.config):
        payload = FavoritesData().payload(child, MultiDict())

    with client.session_transaction() as session:
        session['_user_id'] = str(child.id)
        session['_fresh'] = True
    response = client.get('/api/favorites')

    assert payload['total'] == 1
    assert payload['pages'] == 1
    assert [game['name'] for game in payload['games']] == ['Visible Child Favorite']
    assert response.status_code == 200
    flask_payload = response.get_json()
    differences = {
        key: (payload['games'][0].get(key), flask_payload['games'][0].get(key))
        for key in payload['games'][0].keys() | flask_payload['games'][0].keys()
        if payload['games'][0].get(key) != flask_payload['games'][0].get(key)
    }
    assert {key: value for key, value in flask_payload.items() if key != 'games'} == {
        key: value for key, value in payload.items() if key != 'games'
    }
    assert not differences, differences


def test_favorites_adapter_multi_page_projection_matches_wsgi_route(
    app, client, db_session, configured_install, monkeypatch,
):
    from oneirodex.utils import client_lifecycle, global_settings
    from oneirodex.runtime_native.runtime_context import runtime_config_scope

    user_key = str(uuid4())
    user = User(
        name=f'fav-pages-{user_key[:8]}',
        email=f'fav-pages-{user_key[:8]}@example.com',
        password_hash='unused', role='user', user_id=user_key,
        avatarpath='newstyle/avatar_default.jpg', state=True,
    )
    library = Library(name=f'Fav pages {user_key[:8]}', platform=LibraryPlatform.PCWIN)
    games = [
        Game(
            name=f'Page Boundary Favorite {index}',
            full_disk_path=f'/tmp/fav-page-boundary-{user_key}-{index}',
            library=library,
        )
        for index in range(3)
    ]
    user.favorites.extend(games)
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: None)
    monkeypatch.setattr(client_lifecycle, 'load_lifecycle_map', lambda _user_id: {})
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True

    with app.app_context(), runtime_config_scope(app.config):
        page_one = FavoritesData().payload(
            user, MultiDict([('page', '1'), ('per_page', '2')]),
        )
        page_two = FavoritesData().payload(
            user, MultiDict([('page', '2'), ('per_page', '2')]),
        )
    wsgi_page_one = client.get('/api/favorites?page=1&per_page=2')
    wsgi_page_two = client.get('/api/favorites?page=2&per_page=2')

    assert page_one['total'] == 3 and page_one['pages'] == 2
    assert page_one['current_page'] == 1 and len(page_one['games']) == 2
    assert page_two['total'] == 3 and page_two['pages'] == 2
    assert page_two['current_page'] == 2 and len(page_two['games']) == 1
    assert wsgi_page_one.status_code == wsgi_page_two.status_code == 200
    assert wsgi_page_one.get_json() == page_one
    assert wsgi_page_two.get_json() == page_two
