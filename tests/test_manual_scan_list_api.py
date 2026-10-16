"""Manual scan keeps its idle-preview and busy-queue contract in the native API."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from oneirodex.models import Library, LibraryPlatform, User


def _admin(db_session):
    token = uuid4().hex[:10]
    user = User(name=f'manual_scan_admin_{token}', email=f'manual_scan_{token}@example.test', role='admin', user_id=str(uuid4()), state=True, is_email_verified=True)
    user.set_password('review-only-password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def _library(db_session):
    library = Library(name=f'Manual scan {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


def test_idle_manual_list_returns_candidates_without_starting_scan(client, app, db_session, tmp_path, monkeypatch):
    import oneirodex.routes_apis.library_tools as route
    import oneirodex.utils.scan_queue as queue

    user = _admin(db_session)
    _login(client, user)
    library = _library(db_session)
    folder = tmp_path / 'Manual'
    folder.mkdir()
    app.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    monkeypatch.setattr(route, 'resolve_scan_path', lambda *_args: (str(folder), None))
    monkeypatch.setattr(route, 'resolve_scan_mode_for_path', lambda _path, _mode: 'folders')
    monkeypatch.setattr(route, 'load_scanning_filter_patterns', lambda: ([], []))
    monkeypatch.setattr(route, 'get_game_names_from_folder', lambda *_args, **_kwargs: [{'name': 'Metroid', 'full_path': str(folder / 'Metroid')}])
    monkeypatch.setattr('oneirodex.utils.global_settings.global_settings_row', lambda: SimpleNamespace(write_local_metadata=False))
    busy = Mock(return_value=False)
    start = Mock()
    monkeypatch.setattr(queue, 'is_scan_busy', busy)
    monkeypatch.setattr(queue, 'start_or_queue_scan', start)

    response = client.post('/api/library_tools/manual_identify/list', json={
        'library_uuid': library.uuid, 'folder': 'Manual', 'root': 'games', 'scan_mode': 'folders',
    })
    assert response.status_code == 200
    assert response.get_json()['action'] == 'preview'
    assert response.get_json()['games'][0]['name'] == 'Metroid'
    assert response.get_json()['read_only'] is True
    assert response.headers['Cache-Control'] == 'no-store'
    busy.assert_called_once()
    start.assert_not_called()


def test_busy_manual_list_queues_same_folder_and_manual_options(client, app, db_session, tmp_path, monkeypatch):
    import oneirodex.routes_apis.library_tools as route
    import oneirodex.utils.scan_queue as queue

    user = _admin(db_session)
    _login(client, user)
    library = _library(db_session)
    folder = tmp_path / 'Manual'
    folder.mkdir()
    app.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    monkeypatch.setattr(route, 'resolve_scan_path', lambda *_args: (str(folder), None))
    monkeypatch.setattr(route, 'resolve_scan_mode_for_path', lambda _path, _mode: 'files')
    monkeypatch.setattr(queue, 'is_scan_busy', lambda: True)
    start = Mock(return_value={'status': 'queued', 'message': 'Queued manual scan.', 'job_id': 'job-1', 'position': 2})
    monkeypatch.setattr(queue, 'start_or_queue_scan', start)

    response = client.post('/api/library_tools/manual_identify/list', json={
        'library_uuid': library.uuid, 'folder': 'Manual', 'root': 'games', 'scan_mode': 'auto',
        'force_updates_extras_scan': True, 'fetch_hltb': False, 'force_hltb_refetch': True,
        'queue_policy': 'queue',
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body['action'] == 'queued' and body['read_only'] is False
    assert body['job_id'] == 'job-1' and body['position'] == 2
    assert start.call_args.kwargs == {
        'folder_path': str(folder),
        'library_uuid': library.uuid,
        'scan_mode': 'files',
        'remove_missing': False,
        'download_missing_images': False,
        'force_updates_extras_scan': True,
        'fetch_hltb': False,
        'force_hltb_refetch': True,
        'schedule': None,
        'queue_policy': 'queue',
        'allow_force': True,
        'app': app,
    }


def test_busy_manual_inspect_returns_conflict_without_queuing(client, app, db_session, tmp_path, monkeypatch):
    import oneirodex.routes_apis.library_tools as route
    import oneirodex.utils.scan_queue as queue

    user = _admin(db_session)
    _login(client, user)
    library = _library(db_session)
    folder = tmp_path / 'Manual'
    folder.mkdir()
    app.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    monkeypatch.setattr(route, 'resolve_scan_path', lambda *_args: (str(folder), None))
    monkeypatch.setattr(route, 'resolve_scan_mode_for_path', lambda _path, _mode: 'folders')
    monkeypatch.setattr(queue, 'is_scan_busy', lambda: True)
    start = Mock()
    monkeypatch.setattr(queue, 'start_or_queue_scan', start)

    response = client.post('/api/library_tools/manual_identify/list', json={
        'library_uuid': library.uuid, 'folder': 'Manual', 'root': 'games', 'scan_mode': 'folders',
    })
    assert response.status_code == 200
    assert response.get_json()['action'] == 'conflict'
    assert response.get_json()['read_only'] is True
    assert response.headers['Cache-Control'] == 'no-store'
    start.assert_not_called()
