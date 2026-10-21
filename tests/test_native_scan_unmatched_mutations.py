from __future__ import annotations

import asyncio
import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager
from types import SimpleNamespace

from oneirodex.runtime_native.scan_unmatched_mutations import (
    MutationProblem,
    ScanUnmatchedMutationData,
    create_scan_unmatched_mutations_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


def test_explicit_actor_audit_helpers_do_not_require_flask_app_context(monkeypatch):
    flask_app = Flask('unmatched-audit-context-test')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    events = []
    monkeypatch.setattr('oneirodex.utils.event_logging.log_system_event',
                        lambda *args, **kwargs: events.append((args, kwargs)))
    data = ScanUnmatchedMutationData()

    data.audit_batch_fix(flask_app, 'merge', 'Admin', 1, 2, 7)
    data.audit_single_fix(flask_app, '/roms/Game', 'keep', 'Admin', 7)

    assert len(events) == 2
    assert all(event[1]['audit_user'] == 7 for event in events)


def test_place_update_rejects_outside_root_without_flask_app_context(tmp_path, monkeypatch):
    import oneirodex
    from oneirodex.models import Library, UnmatchedFolder

    storage = tmp_path / 'storage'
    root = storage / 'library'
    source = tmp_path / 'outside' / 'Update Package'
    root.mkdir(parents=True)
    source.mkdir(parents=True)
    folder = SimpleNamespace(id=1, status='Unmatched', library_uuid='l1', folder_path=str(source))
    library = SimpleNamespace(uuid='l1', last_scan_folder=str(root))
    rows = {('UnmatchedFolder', 1): folder, ('Library', 'l1'): library}
    fake_db = SimpleNamespace(session=SimpleNamespace(
        get=lambda model, key: rows.get((model.__name__, key)),
        rollback=lambda: None,
    ))
    monkeypatch.setattr(oneirodex, 'db', fake_db)
    flask_app = Flask('unmatched-place-update-root-check')
    flask_app.config.update(DATA_FOLDER_GAMES=str(storage), BASE_FOLDER_POSIX=str(storage))
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))

    with pytest.raises(MutationProblem, match='outside the configured library paths'):
        ScanUnmatchedMutationData().place_update(flask_app, 1, 'Game')


def test_mark_kind_mutation_uses_explicit_actor_without_flask_app_context(monkeypatch):
    import oneirodex
    from oneirodex.models import UnmatchedFolder

    folder = SimpleNamespace(id=4, folder_path='/library/Utility', library_uuid='library-1')
    calls = []
    fake_db = SimpleNamespace(session=SimpleNamespace(
        get=lambda model, key: folder if model is UnmatchedFolder and key == 4 else None,
        commit=lambda: calls.append(('commit',)),
        rollback=lambda: calls.append(('rollback',)),
    ))
    monkeypatch.setattr(oneirodex, 'db', fake_db)
    game = SimpleNamespace(
        uuid='game-4', name='Utility', item_kind='software', igdb_id=None,
        steam_app_id=None, full_disk_path=folder.folder_path,
    )
    monkeypatch.setattr('oneirodex.utils.software_identify.mark_unmatched_as_kind',
                        lambda *args, **kwargs: game)
    monkeypatch.setattr('oneirodex.utils.event_logging.log_system_event',
                        lambda *args, **kwargs: calls.append(('audit', kwargs)))
    flask_app = Flask('unmatched-mark-kind-context-test')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))

    result = ScanUnmatchedMutationData().mark_kind(
        flask_app, 4, 'software', 'Utility', None, None, actor_id=19,
    )

    assert result['game_uuid'] == 'game-4'
    assert ('commit',) in calls
    assert calls[-1] == ('audit', {'event_type': 'identify', 'event_level': 'information', 'audit_user': 19})


class FakeMutationData:
    def __init__(self):
        self.calls = []

    def amend_name(self, folder_id, payload):
        self.calls.append(('amend_name', folder_id, payload))
        if folder_id == 'missing':
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        return {'id': folder_id, 'folder_path': '/roms/Game', 'folder_name': 'Game',
                'search_name': payload.get('search_name') or payload.get('name'),
                'display_name': payload.get('display_name'), 'effective_search_name': 'Game',
                'changed': {'search_name': payload.get('search_name') or payload.get('name')},
                'disk_rename': False, 'note': 'Soft naming only; disk folder_path unchanged.'}

    def clear_one(self, folder_id):
        self.calls.append(('clear', folder_id))
        if folder_id == 'missing':
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        return {'id': folder_id, 'ok': True, 'result': 'cleared'}

    def clear_all_compat(self):
        self.calls.append(('clear_all_compat',))
        return 4

    def toggle_status_compat(self, folder_id):
        self.calls.append(('toggle_status_compat', folder_id))
        return None if folder_id in (None, 'missing') else 'Ignore'

    def mark_kind_one(self, _app, folder_id, kind, name, summary):
        self.calls.append(('mark_kind_one', folder_id, kind, name, summary))
        if folder_id == 'missing':
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        return {'id': folder_id, 'ok': True, 'game_uuid': f'game-{folder_id}',
                'name': name or 'Game', 'item_kind': kind}

    def fix_one(self, folder_id, action, notes, actor_id):
        self.calls.append(('fix_one', folder_id, action, notes, actor_id))
        if folder_id == 'missing':
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        return {'ok': True, 'id': folder_id, 'action': action, 'folder_id': folder_id,
                'folder_path': '/roms/Game', 'result_status': 'cleared' if action == 'merge' else action,
                'matched_game_uuid': None, 'match_reason': 'same_path', 'match_score': .9}

    def commit(self):
        self.calls.append(('commit',))

    def rollback(self):
        self.calls.append(('rollback',))

    def audit_batch_fix(self, _app, action, actor_name, fixed, total, actor_id):
        self.calls.append(('audit_batch_fix', action, actor_name, fixed, total, actor_id))

    def audit_single_fix(self, _app, path, action, actor_name, actor_id):
        self.calls.append(('audit_single_fix', path, action, actor_name, actor_id))

    def amend_one(self, folder_id, payload):
        self.calls.append(('amend_one', folder_id, payload))
        if folder_id == 'missing':
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        if not any(key in payload for key in ('search_name', 'display_name', 'name')):
            return {'id': folder_id, 'ok': False, 'error': 'search_name_or_display_name_required'}
        return {'id': folder_id, 'ok': True, 'search_name': payload.get('search_name') or payload.get('name'),
                'display_name': payload.get('display_name'), 'changed': {'search_name': 'new'}}

    def latest_fix_log_id(self, folder_id, action):
        self.calls.append(('latest_fix_log_id', folder_id, action))
        return 42

    def mark_kind(self, _app, folder_id, kind, name, steam_app_id, summary, *, actor_id):
        self.calls.append(('mark_kind', folder_id, kind, name, steam_app_id, summary, actor_id))
        if folder_id == 'missing':
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        return {'game_uuid': 'game-1', 'name': name or 'Game', 'item_kind': kind,
                'content_kind': kind, 'igdb_id': 2000000420,
                'steam_app_id': steam_app_id, 'full_disk_path': '/library/Game'}

    def retry_match(self, _app, folder_id):
        self.calls.append(('retry_match', folder_id))
        if folder_id == 'unsafe':
            raise MutationProblem('The folder is outside the configured library paths')
        if folder_id == 'missing':
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        return {'matched': True, 'game_uuid': 'game-1', 'name': 'Matched', 'search_name': 'Clean Name'}

    def place_update(self, _app, folder_id, name):
        self.calls.append(('place_update', folder_id, name))
        if folder_id == 'missing':
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        if folder_id == 'conflict':
            raise MutationProblem('An update with that folder name already exists', code='conflict', status=409)
        return {'placed': True, 'game_root_name': name or 'Game',
                'created_game_root': True, 'matched_game_uuid': None}


@pytest.fixture
def runtime():
    import oneirodex
    from oneirodex.runtime_native.db_session import native_session_scope

    flask_app = Flask('unmatched-mutation-test')
    flask_app.config.update(
        SECRET_KEY='unmatched-mutation-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    oneirodex.db.init_app(flask_app)
    users = {
        'admin': SimpleNamespace(id=1, name='Admin Name', role='admin', state=True,
                                 is_active=True, is_authenticated=True,
                                 session_fingerprint=lambda: 'fp'),
        'librarian': SimpleNamespace(id=2, name='Librarian', role='librarian', state=True,
                                     is_active=True, is_authenticated=True,
                                     session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=3, name='Member', role='user', state=True,
                                  is_active=True, is_authenticated=True,
                                  session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeMutationData()
    app = FastAPI()
    app.include_router(create_scan_unmatched_mutations_router(
        flask_app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=data,
        database_scope=lambda app: native_session_scope(app, oneirodex.db),
    ))
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    cookies = {
        name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                  'unmatched-mutation-secret')
        for name, user in users.items()
    }
    yield app, flask_app, data, users, cookies
    oneirodex.db._app_engines[flask_app][None].dispose()


def _request(app, path, *, cookie=None, method='GET', json=None, form=None, headers=None):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, json=json, data=form, headers=headers or {}, follow_redirects=False)

    return asyncio.run(perform())


def test_auth_librarian_admin_and_csrf_order(runtime):
    app, flask_app, data, _users, cookies = runtime
    anon = _request(app, '/api/unmatched_folders/batch/clear', method='POST', json={'ids': ['1']})
    member = _request(app, '/api/unmatched_folders/batch/clear', cookie=cookies['member'],
                      method='POST', json={'ids': ['1']})
    admin_only = _request(app, '/api/unmatched_folders/1/fix', cookie=cookies['librarian'],
                          method='POST', json={'action': 'keep'})
    assert anon.status_code == 302 and anon.headers['location'].startswith('/login?next=')
    assert member.status_code == 403 and member.json()['error_code'] == 'forbidden'
    assert admin_only.status_code == 302 and admin_only.headers['location'] == '/login'

    flask_app.config['WTF_CSRF_ENABLED'] = True
    csrf_before_auth = _request(app, '/api/unmatched_folders/batch/clear', method='POST', json={'ids': ['1']})
    assert csrf_before_auth.status_code == 400
    assert not any(call[0] == 'clear' for call in data.calls)


def test_legacy_unmatched_form_mutations_require_admin(runtime):
    app, _flask_app, data, _users, cookies = runtime
    requests = [
        ('/clear_unmatched_entry/8', {}),
        ('/update_unmatched_folder_status', {'folder_id': '8'}),
        ('/toggle_ignore_status/8', {}),
        ('/delete_all_unmatched_folders', {}),
    ]

    responses = [
        _request(app, path, cookie=cookies['member'], method='POST', form=form)
        for path, form in requests
    ]

    assert all(response.status_code == 302 for response in responses)
    assert all(response.headers['location'] == '/login' for response in responses)
    assert data.calls == []


def test_name_alias_soft_amend_and_batch_clear_cap_dedupe(runtime):
    app, flask_app, data, _users, cookies = runtime
    flask_app.config['WTF_CSRF_ENABLED'] = False
    named = _request(app, '/api/unmatched_folders/8/name', cookie=cookies['librarian'],
                     method='PATCH', json={'name': 'Friendly name'})
    empty = _request(app, '/api/unmatched_folders/8/name', cookie=cookies['librarian'],
                     method='POST', json={})
    cleared = _request(app, '/api/unmatched_folders/batch/clear', cookie=cookies['librarian'],
                       method='POST', json={'items': [{'id': 1}, {'id': 1}, {'id': 'missing'}]})
    too_many = _request(
        app, '/api/unmatched_folders/batch/clear', cookie=cookies['librarian'], method='POST',
        json={'ids': [str(i) for i in range(101)]},
    )

    assert named.status_code == 200 and named.json()['disk_rename'] is False
    assert named.json()['search_name'] == 'Friendly name'
    assert empty.status_code == 400 and empty.json()['disk_rename'] is False
    assert [call[1] for call in data.calls if call[0] == 'clear'] == ['1', 'missing']
    assert cleared.json()['cleared'] == 1 and cleared.json()['failed'] == 1
    assert cleared.json()['disk_io'] is False
    assert too_many.status_code == 400 and too_many.json()['requested'] == 101


def test_legacy_unmatched_forms_keep_redirects_ajax_shapes_and_hidden_csrf(runtime):
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token

    app, flask_app, data, _users, _cookies = runtime
    flask_app.config['WTF_CSRF_ENABLED'] = True
    session = {'_user_id': '1:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'unmatched-mutation-secret')
    cookie = dump_session_cookie(session, 'unmatched-mutation-secret')

    clear_all = _request(
        app, '/delete_all_unmatched_folders', cookie=cookie, method='POST',
        form={'csrf_token': csrf},
    )
    assert clear_all.status_code == 303
    assert clear_all.headers['location'] == '/scan_management?active_tab=unmatched'
    assert ('clear_all_compat',) in data.calls

    toggled_ajax = _request(
        app, '/toggle_ignore_status/8', cookie=cookie, method='POST',
        json={}, headers={'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
    )
    assert toggled_ajax.status_code == 200
    assert toggled_ajax.json()['status'] == 'success'
    assert toggled_ajax.json()['new_status'] == 'Ignore'

    cleared_ajax = _request(
        app, '/clear_unmatched_entry/8', cookie=cookie, method='POST',
        json={}, headers={'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
    )
    assert cleared_ajax.status_code == 200
    assert cleared_ajax.json()['message'] == 'Entry cleared successfully'

    cleared_form = _request(
        app, '/clear_unmatched_entry/8', cookie=cookie, method='POST',
        form={'csrf_token': csrf},
    )
    assert cleared_form.status_code == 303
    assert cleared_form.headers['location'] == '/scan_management?active_tab=unmatched'

    update = _request(
        app, '/update_unmatched_folder_status', cookie=cookie, method='POST',
        form={'csrf_token': csrf, 'folder_id': '8'},
    )
    assert update.status_code == 303
    assert 'set-cookie' in update.headers


def test_batch_mark_kind_validation_alias_and_partial_results(runtime):
    app, _flask_app, data, _users, cookies = runtime
    valid = _request(
        app, '/api/unmatched_folders/batch/mark_kind', cookie=cookies['librarian'], method='POST',
        json={'ids': ['1', 'missing'], 'kind': 'emu', 'name': 'Emulator', 'summary': 'Local'},
    )
    invalid = _request(
        app, '/api/unmatched_folders/batch/mark_kind', cookie=cookies['librarian'], method='POST',
        json={'ids': ['1'], 'item_kind': 'nonsense'},
    )

    assert valid.status_code == 200
    assert valid.json()['item_kind'] == 'emulator'
    assert valid.json()['marked'] == 1 and valid.json()['failed'] == 1
    assert valid.json()['disk_io'] is False
    assert ('mark_kind_one', '1', 'emulator', 'Emulator', 'Local') in data.calls
    assert invalid.status_code == 400 and 'item_kinds' in invalid.json()


def test_batch_fix_audits_and_single_fix_response(runtime):
    app, _flask_app, data, _users, cookies = runtime
    batch = _request(
        app, '/api/unmatched_folders/batch/fix', cookie=cookies['librarian'], method='POST',
        json={'ids': ['1', 'missing'], 'action': 'merge', 'notes': 'review'},
    )
    single = _request(
        app, '/api/unmatched_folders/1/fix', cookie=cookies['admin'], method='POST',
        json={'action': 'keep', 'matched_game_uuid': 'requested-game'},
    )
    invalid = _request(
        app, '/api/unmatched_folders/1/fix', cookie=cookies['admin'], method='POST',
        json={'action': 'remove'},
    )

    assert batch.json()['fixed'] == 1 and batch.json()['failed'] == 1
    assert batch.json()['disk_io'] is False
    assert ('audit_batch_fix', 'merge', 'Librarian', 1, 2, 2) in data.calls
    assert single.json()['matched_game_uuid'] == 'requested-game'
    assert single.json()['fix_log_id'] == 42
    assert any(call[0] == 'audit_single_fix' for call in data.calls)
    assert invalid.status_code == 400


def test_batch_amend_item_form_and_shared_fields(runtime):
    app, _flask_app, _data, _users, cookies = runtime
    per_item = _request(
        app, '/api/unmatched_folders/batch/amend', cookie=cookies['librarian'], method='POST',
        json={'items': [{'id': '1', 'search_name': 'One'}, {'id': '2'}, 5, {'display_name': 'No id'}]},
    )
    shared = _request(
        app, '/api/unmatched_folders/batch/amend', cookie=cookies['librarian'], method='POST',
        json={'ids': ['1', 'missing'], 'display_name': 'Friendly'},
    )
    capped = _request(
        app, '/api/unmatched_folders/batch/amend', cookie=cookies['librarian'], method='POST',
        json={'items': [{'id': str(i), 'name': 'x'} for i in range(101)]},
    )

    assert per_item.json()['amended'] == 1 and per_item.json()['failed'] == 3
    assert per_item.json()['disk_rename'] is False and per_item.json()['disk_io'] is False
    assert shared.json()['amended'] == 1 and shared.json()['failed'] == 1
    assert capped.status_code == 400 and capped.json()['requested'] == 101


def test_mark_kind_retry_and_placement_are_adapter_backed(runtime):
    app, _flask_app, data, _users, cookies = runtime
    marked = _request(
        app, '/api/unmatched_folders/5/mark_kind', cookie=cookies['admin'], method='POST',
        json={'content_kind': 'software', 'steam_app_id': '123', 'name': 'Tool'},
    )
    bad_steam = _request(
        app, '/api/unmatched_folders/5/mark_kind', cookie=cookies['admin'], method='POST',
        json={'item_kind': 'game', 'steam_app_id': 'bad'},
    )
    retry = _request(
        app, '/api/unmatched_folders/9/retry_match', cookie=cookies['librarian'], method='POST',
    )
    unsafe_retry = _request(
        app, '/api/unmatched_folders/unsafe/retry_match', cookie=cookies['librarian'], method='POST',
    )
    placed = _request(
        app, '/api/unmatched_folders/10/place_update', cookie=cookies['librarian'], method='POST',
        json={'game_root_name': 'Game'},
    )
    conflict = _request(
        app, '/api/unmatched_folders/conflict/place_update', cookie=cookies['librarian'], method='POST',
        json={'game_root_name': 'Game'},
    )
    invalid_schema = _request(
        app, '/api/unmatched_folders/10/place_update', cookie=cookies['librarian'], method='POST',
        json={'unexpected': True},
    )

    assert marked.json()['item_kind'] == 'tool' and marked.json()['steam_app_id'] == 123
    assert bad_steam.status_code == 400
    assert retry.json()['matched'] is True
    assert unsafe_retry.status_code == 400 and 'outside' in unsafe_retry.json()['error']
    assert placed.json()['placed'] is True
    assert conflict.status_code == 409
    assert invalid_schema.status_code == 422
    assert ('place_update', '10', 'Game') in data.calls
    assert not any(call[0] == 'filesystem' for call in data.calls)
