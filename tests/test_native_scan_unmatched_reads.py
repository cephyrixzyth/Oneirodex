from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.scan_unmatched_reads import (
    ScanUnmatchedReadsData,
    create_scan_unmatched_reads_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


def test_search_filter_includes_linked_game_title_and_disk_path():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from oneirodex.models import Library, UnmatchedFolder

    query = select(UnmatchedFolder, Library.name).join(Library)
    filtered = ScanUnmatchedReadsData._apply_filters(query, {'q': 'Linked Match'})
    sql = str(filtered.compile(dialect=postgresql.dialect())).lower()

    assert 'exists (select 1' in sql
    assert 'from games' in sql
    assert 'games.name ilike' in sql
    assert 'games.full_disk_path ilike' in sql
    assert 'cast(libraries.platform as varchar)' in sql
    assert 'cast(unmatched_folders.status as varchar)' in sql
    assert UnmatchedFolder.matched_game_uuid.key in sql


class FakeUnmatchedData:
    def __init__(self):
        self.rows = [
            ({'id': 1, 'folder_path': '/roms/Game (USA)', 'rom_region': 'USA',
              'matched_game': {'name': 'Existing', 'path': '/games/existing'}, 'status': 'Unmatched'},
             'Main', SimpleNamespace(name='NES', value='nes')),
            ({'id': 2, 'folder_path': '/roms/Game (Europe)', 'rom_region': 'EUR',
              'matched_game': None, 'status': 'Duplicate'},
             'Archive', SimpleNamespace(name='SNES', value='snes')),
        ]
        self.logs = [{'id': 11, 'action': 'merge', 'folder_path': '/roms/Game', 'created_at': 'now'}]
        self.calls = []

    def query_unmatched(self, filters, *, paginate=None):
        self.calls.append(('query', dict(filters), paginate))
        return list(self.rows)

    def count_unmatched(self, filters):
        self.calls.append(('count', dict(filters)))
        return 19

    def list_payloads(self, _app, rows, include_transforms):
        self.calls.append(('project_list', include_transforms))
        return [{**folder, 'library_name': name, 'platform_name': platform.name,
                 'transforms': ['strip-region'] if include_transforms else []}
                for folder, name, platform in rows]

    def duplicate_payloads(self, _app):
        self.calls.append(('duplicates',))
        return [{'id': 2, 'clone_of': None, 'matched_game': None,
                 'titles': [{'role': 'unmatched_folder', 'name': 'Game'}], 'candidates': []}]

    def fix_log_payloads(self, limit):
        self.calls.append(('fix_logs', limit))
        return self.logs[:limit]


@pytest.fixture
def runtime():
    flask_app = Flask('unmatched-reads-test')
    flask_app.config.update(
        SECRET_KEY='unmatched-reads-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True,
    )
    users = {
        'admin': SimpleNamespace(id=1, role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=2, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeUnmatchedData()
    tokens = {}
    app = FastAPI()
    app.include_router(create_scan_unmatched_reads_router(
        flask_app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda prefix: tokens.get(prefix), commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=data,
    ))
    cookies = {
        name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                  'unmatched-reads-secret')
        for name, user in users.items()
    }
    return app, flask_app, data, users, tokens, cookies


def _request(app, path, *, cookie=None, method='GET'):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, follow_redirects=False)

    return asyncio.run(perform())


def test_login_admin_gate_and_head_semantics(runtime):
    app, _flask_app, _data, _users, _tokens, cookies = runtime
    anonymous = _request(app, '/api/unmatched_folders')
    member = _request(app, '/api/unmatched_folders', cookie=cookies['member'])
    head = _request(app, '/api/unmatched_folders', cookie=cookies['admin'], method='HEAD')

    assert anonymous.status_code == 302
    assert anonymous.headers['location'] == '/login?next=%2Fapi%2Funmatched_folders'
    assert member.status_code == 302
    assert member.headers['location'] == '/login'
    assert head.status_code == 200
    assert head.content == b''


def test_list_query_aliases_first_value_transforms_and_region_pagination(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    response = _request(
        app,
        '/api/unmatched_folders?status=all&status=Duplicate&name= Zelda &q=&reason=title&why=&system=NES&platform=&region=USA&rom_region=&limit=700&offset=-8&paginate=true&include=minimal&transforms=yes',
        cookie=cookies['admin'],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 1
    assert payload['limit'] == 500 and payload['offset'] == 0 and payload['count'] == 1
    assert payload['items'][0]['id'] == 1
    assert payload['items'][0]['transforms'] == ['strip-region']
    query = next(call for call in data.calls if call[0] == 'query')
    filters = query[1]
    assert filters['status'] == 'all'
    assert filters['q'] == 'Zelda'
    assert filters['why'] == 'title'
    assert filters['platform'] == 'NES'
    assert filters['rom_region'] == 'USA'
    assert filters['limit'] == 500 and filters['offset'] == 0
    assert filters['include_transforms'] is True
    assert filters['paginate'] is False
    assert query[2] is None


def test_unpaged_list_defaults_and_validation(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    response = _request(app, '/api/unmatched_folders?limit=oops&offset=oops&include=columns', cookie=cookies['admin'])
    bad = _request(app, '/api/unmatched_folders?status=INVALID', cookie=cookies['admin'])

    assert response.status_code == 200
    assert isinstance(response.json(), list) and len(response.json()) == 2
    query = next(call for call in data.calls if call[0] == 'query')
    assert query[1]['limit'] == 150 and query[1]['offset'] == 0
    assert query[1]['include_transforms'] is False
    assert bad.status_code == 400
    assert bad.json()['error_code'] == 'bad_request'


def test_duplicates_projection_fix_log_limit_and_head(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    duplicates = _request(app, '/api/unmatched_folders/duplicates', cookie=cookies['admin'])
    logs = _request(app, '/api/unmatched_folders/fix_logs?limit=0', cookie=cookies['admin'])
    head = _request(app, '/api/unmatched_folders/duplicates', cookie=cookies['admin'], method='HEAD')

    assert duplicates.json()['count'] == 1
    assert duplicates.json()['duplicates'][0]['titles'][0]['role'] == 'unmatched_folder'
    assert logs.json()['count'] == 1
    assert ('fix_logs', 100) in data.calls
    assert head.content == b''


def test_json_and_csv_exports_keep_headers_shapes_region_and_no_pagination(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    json_export = _request(
        app, '/api/unmatched_folders/export?format=json&region=USA&paginate=true&limit=1&offset=1',
        cookie=cookies['admin'],
    )
    csv_export = _request(
        app, '/api/unmatched_folders/export?format=csv&status=Duplicate', cookie=cookies['admin'],
    )
    invalid = _request(app, '/api/unmatched_folders/export?format=xml', cookie=cookies['admin'])

    assert json_export.status_code == 200
    assert json_export.headers['content-disposition'] == 'attachment; filename="unmatched_folders_all.json"'
    assert [row['id'] for row in json_export.json()] == [1]
    assert ('query', {'status': 'all', 'q': '', 'why': '', 'suggested_kind': '',
                      'library_uuid': '', 'platform': '', 'rom_region': 'USA',
                      'limit': 1, 'offset': 1, 'include_transforms': True, 'paginate': False}, False) in data.calls
    assert csv_export.headers['content-disposition'] == 'attachment; filename="unmatched_folders_Duplicate.csv"'
    assert csv_export.headers['content-type'].startswith('text/csv')
    assert 'matched_game_name' in csv_export.text.splitlines()[0]
    assert 'Existing' in csv_export.text
    assert invalid.status_code == 400 and invalid.json()['error_code'] == 'bad_request'


def test_admin_bearer_requires_explicit_admin_scope(runtime):
    app, _flask_app, _data, _users, tokens, _cookies = runtime
    token = SimpleNamespace(
        user_id=1, token_hash=hashlib.sha256(b'secret').hexdigest(), revoked_at=None,
        scopes=['read:library'], last_used_at=None,
        has_scope=lambda scope: scope == 'read:library',
    )
    tokens['prefix'] = token
    response = _request(
        app, '/api/unmatched_folders',
    )
    async def bearer_request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            return await client.get('/api/unmatched_folders', headers={'Authorization': 'Bearer gt_prefix_secret'})
    response = asyncio.run(bearer_request())
    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
