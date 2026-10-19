from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.library_tools_mutations import (
    LibraryToolsMutationData,
    create_library_tools_mutations_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


def test_native_library_data_methods_use_scoped_session_without_app_context(monkeypatch):
    import oneirodex
    from oneirodex.models import Game, Library

    game = SimpleNamespace(uuid='g1', name='Original', full_disk_path='/safe/Original')
    library = SimpleNamespace(uuid='l1')
    rows = {('Library', 'l1'): library}

    def execute(query):
        model = query.column_descriptions[0]['entity']
        filters = query.whereclause
        if model is Game and str(filters.right.value) == game.uuid:
            row = game
        else:
            row = None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))

    fake_session = SimpleNamespace(
        get=lambda model, key: rows.get((model.__name__, key)),
        execute=execute,
        commit=lambda: None,
        rollback=lambda: None,
    )
    fake_db = SimpleNamespace(session=fake_session)
    monkeypatch.setattr(oneirodex, 'db', fake_db)
    app = Flask('native-library-lookups')
    app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    data = LibraryToolsMutationData()

    assert data.game(app, 'g1') is game
    assert data.library(app, 'l1') is library

    monkeypatch.setattr(
        'oneirodex.utils.disk_rename.apply_rename_plan', lambda plan, _bases: [],
    )
    assert data.apply_rename(app, 'g1', [], ['/safe']) == ([], '/safe/Original', False)

    monkeypatch.setattr('oneirodex.utils.library_doctor.doctor_apply_renames', lambda *args, **kwargs: [])
    assert data.doctor_apply_renames(app, [], ['/safe'], '{title}') == ([], 0, False)

    events = []
    monkeypatch.setattr('oneirodex.utils.rom_language.apply_rom_language_fields', lambda *_: None)
    monkeypatch.setattr('oneirodex.utils.event_logging.log_system_event',
                        lambda *args, **kwargs: events.append(kwargs))
    game.full_disk_path = '/safe/Original'
    linked, error = data.link_existing_game(app, 'g1', '/safe/Original', 'Admin', 42)
    assert error is None and linked['game_uuid'] == 'g1'
    assert events[-1]['audit_user'] == 42

    freshness_calls = []
    monkeypatch.setattr(
        'oneirodex.utils.freshness.service.check_library_freshness',
        lambda *args, **kwargs: freshness_calls.append((args, kwargs)) or {'checked': 1},
    )
    assert data.check_freshness(app, 'l1', limit=7, only_missing=False) == {'checked': 1}
    assert freshness_calls == [(('l1',), {'limit': 7, 'only_missing': False, 'app': app})]


def test_link_existing_game_database_failure_rolls_back_and_logs_sanitized_event(monkeypatch):
    import oneirodex
    from sqlalchemy.exc import SQLAlchemyError
    from oneirodex.models import Game

    game = SimpleNamespace(uuid='g1', name='Original', full_disk_path='/safe/Original')
    rolled_back = []
    events = []

    def execute(query):
        model = query.column_descriptions[0]['entity']
        row = game if model is Game else None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))

    def fail_commit():
        raise SQLAlchemyError('postgresql://user:private@db/library')

    fake_session = SimpleNamespace(
        execute=execute, commit=fail_commit,
        rollback=lambda: rolled_back.append(True), delete=lambda _row: None,
    )
    monkeypatch.setattr(oneirodex, 'db', SimpleNamespace(session=fake_session))
    monkeypatch.setattr('oneirodex.utils.rom_language.apply_rom_language_fields', lambda *_: None)
    monkeypatch.setattr(
        'oneirodex.utils.event_logging.log_system_event',
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    linked, error = LibraryToolsMutationData().link_existing_game(
        Flask('link-existing-game-db-failure'), 'g1', '/safe/NewFolder', 'Admin', 42,
    )

    assert linked is None and error == 'internal'
    assert rolled_back == [True]
    assert len(events) == 1
    assert events[0][0] == (
        "Database error linking existing game 'g1' to folder by admin Admin",
    )
    assert events[0][1] == {
        'event_type': 'error', 'event_level': 'error', 'audit_user': 42,
    }
    assert 'private' not in events[0][0][0]


def test_native_steam_backfill_uses_scoped_session_without_app_context(monkeypatch):
    import oneirodex

    game = SimpleNamespace(uuid='g2', name='Game Two', steam_app_id=22, summary='', genres=[])
    commits = []
    fake_session = SimpleNamespace(
        execute=lambda _query: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [game])),
        commit=lambda: commits.append('commit'),
    )
    monkeypatch.setattr(oneirodex, 'db', SimpleNamespace(session=fake_session))
    monkeypatch.setattr('oneirodex.utils.steam_metadata.hydrate_game_from_steam',
                        lambda row: {'summary': 'Filled summary'})
    app = Flask('native-steam-backfill')
    app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))

    result = LibraryToolsMutationData().backfill_steam_metadata(
        app, library_uuid=None, limit=3, only_incomplete=False, cascade=False,
    )

    assert result['updated'] == 1
    assert result['games'][0]['filled'] == {'summary': 'Filled summary'}
    assert commits == ['commit']


class FakeData:
    def __init__(self):
        self.calls = []
        self.game_row = SimpleNamespace(uuid='g1', name='Original', full_disk_path='/safe/Original')
        self.link_error_code = None

    def safe_path(self, _app, path):
        return str(path).startswith('/safe'), 'outside allowed roots'

    def game(self, _app, uid):
        return self.game_row if uid == 'g1' else None

    def build_rename_preview(self, root, **kwargs):
        self.calls.append(('preview', root, kwargs))
        return [{'kind': 'root_folder', 'from_path': root, 'to_path': '/safe/Renamed'}]

    def remove_proposal(self, path):
        self.calls.append(('remove_proposal', path))

    def write_proposals(self, rows):
        self.calls.append(('write_proposals', rows))
        return [{'path': row['path'], 'ok': True} for row in rows]

    def directory_readable(self, path):
        self.calls.append(('directory_readable', path))
        return path == '/safe/NewFolder'

    def log_unsafe_existing_game_path(self, path, reason, actor_name, actor_id):
        self.calls.append(('unsafe_link_path', path, reason, actor_name, actor_id))

    def link_existing_game(self, _app, game_uuid, path, actor, _actor_id):
        self.calls.append(('link_existing_game', game_uuid, path, actor))
        if self.link_error_code:
            return None, self.link_error_code
        return {'game_uuid': game_uuid, 'game_name': 'Original',
                'full_disk_path': path, 'removed_from_unmatched': True}, None

    def validate_rename_plan(self, plan, root):
        self.calls.append(('validate_rename_plan', plan, root))
        return [] if plan == [{'kind': 'root_folder', 'from_path': root,
                              'to_path': '/safe/Renamed'}] else ['Bad plan']

    def apply_rename(self, _app, game_uuid, plan, bases):
        self.calls.append(('apply_rename', game_uuid, plan, tuple(bases)))
        return [{'kind': 'root_folder', 'ok': True}], '/safe/Renamed', False

    def allowed_bases(self, _app):
        return ['/safe']

    def doctor_apply_renames(self, _app, rows, bases, template):
        self.calls.append(('doctor_apply', rows, tuple(bases), template))
        return [{'path': rows[0]['path'], 'ok': True, 'results': []}] if rows else [], 1, False

    def backfill_steam_metadata(self, _app, **kwargs):
        self.calls.append(('backfill', kwargs))
        return {'scanned': 2, 'updated': 1, 'skipped': 1, 'errors': [],
                'games': [{'uuid': 'g1', 'name': 'Original', 'filled': {'summary': True}}]}

    def library(self, _app, library_uuid):
        self.calls.append(('library', library_uuid))
        return SimpleNamespace(uuid=library_uuid) if library_uuid == 'lib1' else None

    def check_freshness(self, _app, library_uuid, *, limit, only_missing):
        self.calls.append(('freshness', library_uuid, limit, only_missing))
        return {'library_uuid': library_uuid, 'checked': 1}


@pytest.fixture
def runtime():
    flask_app = Flask('library-tools-mutations-test')
    flask_app.config.update(SECRET_KEY='mutation-secret', SESSION_PROTECTION='none',
                            SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False)
    users = {
        'admin': SimpleNamespace(id=7, name='admin', role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=8, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeData()
    app = FastAPI()
    app.state.flask_app = flask_app
    app.include_router(create_library_tools_mutations_router(
        flask_app, find_user=lambda uid: next((u for u in users.values() if u.id == uid), None),
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity), login_manager=manager,
        data_access=data))
    cookies = {name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                         'mutation-secret') for name, user in users.items()}
    return app, data, cookies


def request(app, path, *, cookie=None, json=None, headers=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://testserver') as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.post(path, json=json, headers=headers or {}, follow_redirects=False)
    return asyncio.run(run())


def test_rename_preview_is_admin_only_read_only_and_preserves_shape(runtime):
    app, data, cookies = runtime
    response = request(app, '/api/library_tools/rename/preview', cookie=cookies['admin'],
                       json={'game_uuid': 'g1', 'title': 'Renamed'})
    assert response.status_code == 200
    assert response.json()['plan'][0]['to_path'] == '/safe/Renamed'
    assert response.json()['game_uuid'] == 'g1'
    assert data.calls[0][0] == 'preview'
    denied = request(app, '/api/library_tools/rename/preview', cookie=cookies['member'],
                     json={'game_uuid': 'g1'})
    assert denied.status_code == 302


def test_proposal_approval_rejects_unsafe_and_delegates_deletion(runtime):
    app, data, cookies = runtime
    unsafe = request(app, '/api/library_tools/proposals/approve', cookie=cookies['admin'],
                     json={'path': '/outside/game', 'igdb_id': 22})
    assert unsafe.status_code == 403
    assert not data.calls
    ok = request(app, '/api/library_tools/proposals/approve', cookie=cookies['admin'],
                 json={'path': '/safe/game', 'igdb_id': 22})
    assert ok.status_code == 200
    assert ok.json()['identify_hint'] == '/add_game_manual?full_disk_path=/safe/game&igdb_id=22'
    assert data.calls == [('remove_proposal', '/safe/game')]


def test_doctor_write_filters_untrusted_paths_before_adapter(runtime):
    app, data, cookies = runtime
    response = request(app, '/api/library_tools/doctor/write_proposals', cookie=cookies['admin'],
                       json={'rows': [{'path': '/safe/Game'}, {'path': '/outside/Escape'}, 'bad']})
    assert response.status_code == 200
    assert response.json()['results'] == [{'path': '/safe/Game', 'ok': True}]
    assert data.calls == [('write_proposals', [{'path': '/safe/Game'}])]


def test_mutations_reject_invalid_body_before_adapter_work(runtime):
    app, data, cookies = runtime
    # A malformed JSON shape is rejected without touching an injected adapter.
    response = request(app, '/api/library_tools/doctor/write_proposals', cookie=cookies['admin'],
                       json={'rows': 'nope'})
    assert response.status_code == 400
    assert not data.calls


def test_mutations_reject_missing_csrf_before_adapter_work(runtime):
    app, data, cookies = runtime
    app.state.flask_app.config['WTF_CSRF_ENABLED'] = True
    response = request(app, '/api/library_tools/doctor/write_proposals',
                       cookie=cookies['admin'], json={'rows': []})
    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert not data.calls


def test_link_existing_game_checks_path_and_preserves_response(runtime):
    app, data, cookies = runtime
    denied = request(app, '/api/library_tools/link_existing_game', cookie=cookies['admin'],
                     json={'game_uuid': 'g1', 'full_disk_path': '/outside/New'})
    assert denied.status_code == 403
    ok = request(app, '/api/library_tools/link_existing_game', cookie=cookies['admin'],
                 json={'game_uuid': 'g1', 'full_disk_path': '/safe/NewFolder',
                       'library_uuid': 'lib1', 'from_unmatched': True})
    assert ok.status_code == 200
    assert ok.json()['removed_from_unmatched'] is True
    assert ok.json()['library_uuid'] == 'lib1'
    assert ('link_existing_game', 'g1', '/safe/NewFolder', 'admin') in data.calls


def test_legacy_link_existing_game_form_checks_hidden_csrf_and_redirects(runtime):
    from starlette.testclient import TestClient

    app, data, _cookies = runtime
    app.state.flask_app.config['WTF_CSRF_ENABLED'] = True
    session = {'_user_id': '7:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'mutation-secret')
    cookie = dump_session_cookie(session, 'mutation-secret')
    with TestClient(app) as client:
        client.cookies.set('session', cookie)
        rejected = client.post('/link_existing_game', data={
            'game_uuid': 'g1', 'full_disk_path': '/safe/NewFolder',
            'from_unmatched': 'true',
        })
        accepted = client.post('/link_existing_game', data={
            'game_uuid': 'g1', 'full_disk_path': '/safe/NewFolder',
            'library_uuid': 'lib1', 'from_unmatched': 'true', 'csrf_token': csrf,
        }, follow_redirects=False)
        accepted_from_identify = client.post('/link_existing_game', data={
            'game_uuid': 'g1', 'full_disk_path': '/safe/NewFolder',
            'library_uuid': 'lib1', 'from_unmatched': 'false', 'csrf_token': csrf,
        }, follow_redirects=False)
        rejected_path = client.post('/link_existing_game', data={
            'game_uuid': 'g1', 'full_disk_path': '/outside/New Folder',
            'from_unmatched': 'true', 'csrf_token': csrf,
        }, follow_redirects=False)

    assert rejected.status_code == 400
    assert rejected.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is missing.</p>' in rejected.content
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/scan_management?active_tab=unmatched'
    assert accepted_from_identify.status_code == 302
    assert accepted_from_identify.headers['location'] == '/scan_management?active_tab=unmatched'
    assert rejected_path.status_code == 302
    assert rejected_path.headers['location'] == (
        '/add_game_manual?full_disk_path=/outside/New+Folder&from_unmatched=true'
    )
    assert ('link_existing_game', 'g1', '/safe/NewFolder', 'admin') in data.calls
    assert ('unsafe_link_path', '/outside/New Folder', 'outside allowed roots', 'admin', 7) in data.calls


def test_legacy_link_existing_game_login_and_admin_redirects(runtime):
    from http.cookies import SimpleCookie
    from starlette.testclient import TestClient
    from oneirodex.runtime_native.session_compat import load_session_cookie

    app, data, cookies = runtime
    with TestClient(app) as client:
        anonymous = client.post('/link_existing_game', data={}, follow_redirects=False)
    with TestClient(app) as client:
        client.cookies.set('session', cookies['member'])
        member = client.post('/link_existing_game', data={}, follow_redirects=False)
        cookie = SimpleCookie()
        cookie.load(next(value for value in member.headers.get_list('set-cookie')
                         if value.startswith('session=')))
        session_cookie = cookie['session'].value

    session = load_session_cookie(session_cookie, 'mutation-secret', max_age=31_536_000)
    assert anonymous.status_code == member.status_code == 302
    assert anonymous.headers['location'] == '/login?next=%2Flink_existing_game'
    assert member.headers['location'] == '/login'
    assert ('danger', 'You must be an admin to access this page.') in session['_flashes']
    assert not data.calls


def test_legacy_link_existing_game_empty_form_matches_flask_redirect(runtime):
    from starlette.testclient import TestClient

    app, _data, _cookies = runtime
    app.state.flask_app.config['WTF_CSRF_ENABLED'] = True
    session = {'_user_id': '7:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'mutation-secret')
    cookie = dump_session_cookie(session, 'mutation-secret')

    with TestClient(app) as client:
        client.cookies.set('session', cookie)
        response = client.post('/link_existing_game', data={},
                               headers={'X-CSRFToken': csrf}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/add_game_manual?from_unmatched=false'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<a href="/add_game_manual?from_unmatched=false">' in response.content


def test_legacy_link_existing_game_database_failure_uses_legacy_flash(runtime):
    from http.cookies import SimpleCookie
    from starlette.testclient import TestClient
    from oneirodex.runtime_native.session_compat import load_session_cookie

    app, data, cookies = runtime
    data.link_error_code = 'internal'
    with TestClient(app) as client:
        client.cookies.set('session', cookies['admin'])
        response = client.post('/link_existing_game', data={
            'game_uuid': 'g1', 'full_disk_path': '/safe/NewFolder',
        }, follow_redirects=False)
        cookie = SimpleCookie()
        cookie.load(next(value for value in response.headers.get_list('set-cookie')
                         if value.startswith('session=')))
        session_cookie = cookie['session'].value

    session = load_session_cookie(session_cookie, 'mutation-secret', max_age=31_536_000)
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/add_game_manual?full_disk_path=/safe/NewFolder&from_unmatched=false'
    )
    assert (
        'error', 'An error occurred while linking the game. Please try again.'
    ) in session['_flashes']


def test_rename_apply_validates_plan_before_adapter_mutation(runtime):
    app, data, cookies = runtime
    bad = request(app, '/api/library_tools/rename/apply', cookie=cookies['admin'],
                  json={'game_uuid': 'g1', 'plan': [{'bad': True}]})
    assert bad.status_code == 400
    assert not any(call[0] == 'apply_rename' for call in data.calls)
    plan = [{'kind': 'root_folder', 'from_path': '/safe/Original',
             'to_path': '/safe/Renamed'}]
    ok = request(app, '/api/library_tools/rename/apply', cookie=cookies['admin'],
                 json={'game_uuid': 'g1', 'plan': plan})
    assert ok.status_code == 200
    assert ok.json()['full_disk_path'] == '/safe/Renamed'
    assert data.calls[-1][0] == 'apply_rename'


def test_doctor_apply_renames_filters_paths_and_keeps_result_shape(runtime):
    app, data, cookies = runtime
    response = request(app, '/api/library_tools/doctor/apply_renames', cookie=cookies['admin'],
                       json={'rows': [{'path': '/safe/Game'}, {'path': '/outside/Escape'}]})
    assert response.status_code == 200
    assert response.json()['results'] == [{'path': '/safe/Game', 'ok': True, 'results': []}]
    assert response.json()['records_updated'] == 1
    assert data.calls[-1] == ('doctor_apply', [{'path': '/safe/Game'}], ('/safe',), '{title}')


def test_backfill_and_freshness_delegate_operations_and_preserve_contracts(runtime):
    app, data, cookies = runtime
    backfill = request(app, '/api/library_tools/backfill_steam_metadata', cookie=cookies['admin'],
                       json={'limit': 0, 'library_uuid': 'lib1', 'cascade': False})
    freshness = request(app, '/api/library_tools/check_freshness', cookie=cookies['admin'],
                        json={'library_uuid': 'lib1', 'limit': 0, 'only_missing': False})
    missing = request(app, '/api/library_tools/check_freshness', cookie=cookies['admin'],
                      json={'library_uuid': 'missing'})
    assert backfill.status_code == freshness.status_code == 200
    assert backfill.json()['scanned'] == 2
    assert freshness.json()['checked'] == 1
    assert missing.status_code == 404
    assert ('backfill', {'library_uuid': 'lib1', 'limit': 100,
                         'only_incomplete': True, 'cascade': False}) in data.calls
    assert ('freshness', 'lib1', 50, False) in data.calls

