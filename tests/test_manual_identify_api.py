"""Focused contracts for the native manual-identify API."""

from uuid import uuid4
from sqlalchemy import select

from oneirodex.models import Game, Library, LibraryPlatform, UnmatchedFolder, User


def _admin(db_session):
    token = uuid4().hex[:10]
    user = User(
        name=f'identify_admin_{token}', email=f'identify_{token}@example.test',
        role='admin', user_id=str(uuid4()), state=True, is_email_verified=True,
    )
    user.set_password('review-only-password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_options_requires_admin_and_returns_legacy_form_choices(client, db_session):
    _login(client, _admin(db_session))
    response = client.get('/api/admin/manual-identify/options')
    body = response.get_json()
    assert response.status_code == 200, response.location
    assert body['ok'] is True
    assert isinstance(body['libraries'], list)
    assert set(body['taxonomies']) == {
        'genres', 'game_modes', 'themes', 'platforms', 'player_perspectives',
    }
    assert body['categories'] and body['statuses']
    assert response.headers['Cache-Control'] == 'no-store'


def test_save_rejects_invalid_payload_and_unknown_fields_before_database_work(client, db_session):
    _login(client, _admin(db_session))
    response = client.post('/api/admin/manual-identify', json={
        'igdb_id': 0, 'name': '', 'full_disk_path': '/private/path',
        'library_uuid': 'missing', 'unexpected': 'ignored',
    })
    body = response.get_json()
    assert response.status_code == 422
    assert body['ok'] is False
    assert 'igdb_id' in body['detail']
    assert 'unexpected' in body['detail']
    assert '/private/path' not in response.get_data(as_text=True)


def test_save_rejects_unknown_library_before_path_or_game_mutation(client, db_session):
    _login(client, _admin(db_session))
    response = client.post('/api/admin/manual-identify', json={
        'igdb_id': 123,
        'name': 'Review title',
        'full_disk_path': '/outside/root/review-title',
        'library_uuid': str(uuid4()),
    })
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    assert 'outside/root' not in response.get_data(as_text=True)


def test_save_creates_game_and_clears_matching_unmatched_row(client, app, db_session, tmp_path, monkeypatch):
    import oneirodex.routes_apis.manual_identify as route

    user = _admin(db_session)
    _login(client, user)
    folder = tmp_path / 'Recognized Game'
    folder.mkdir()
    app.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    library = Library(name=f'Identify Library {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    unmatched = UnmatchedFolder(
        library_uuid=library.uuid, folder_path=str(folder), content_type='Games', status='Pending',
    )
    db_session.add(unmatched)
    db_session.commit()
    monkeypatch.setattr(route, 'check_existing_game_by_igdb_id', lambda _igdb_id: None)
    monkeypatch.setattr(route, 'ensure_manual_identify_taxonomy', lambda *_args: None)
    monkeypatch.setattr(route, 'log_system_event', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('oneirodex.utils.background.run_in_background', lambda *_args, **_kwargs: None)

    response = client.post('/api/admin/manual-identify?from_unmatched=true', json={
        'igdb_id': 7654321,
        'name': 'Recognized Game',
        'full_disk_path': str(folder),
        'library_uuid': library.uuid,
        'aggregated_rating': 87.5,
        'first_release_date': '2024-05-06',
    })
    assert response.status_code == 201
    payload = response.get_json()
    game = db_session.execute(select(Game).filter_by(uuid=payload['game_uuid'])).scalar_one()
    assert game.name == 'Recognized Game'
    assert game.aggregated_rating == 87.5
    assert game.library_uuid == library.uuid
    assert payload['redirect_url'] == '/admin/unmatched'
    assert db_session.get(UnmatchedFolder, unmatched.id) is None

    state = client.get(f"/api/admin/manual-identify/{payload['game_uuid']}")
    assert state.status_code == 200
    assert state.get_json()['game']['name'] == 'Recognized Game'
    updated = client.put(f"/api/admin/manual-identify/{payload['game_uuid']}", json={
        'igdb_id': 7654321,
        'name': 'Renamed Game',
        'full_disk_path': str(folder),
        'library_uuid': library.uuid,
        'aggregated_rating': 90,
    })
    assert updated.status_code == 200
    assert updated.get_json()['redirect_url'] == '/libraries'
    assert db_session.execute(select(Game).filter_by(uuid=payload['game_uuid'])).scalar_one().name == 'Renamed Game'
