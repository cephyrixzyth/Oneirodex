from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.library_tools import create_library_tools_router
from oneirodex.runtime_native.library_tools_mutations import create_library_tools_mutations_router
from oneirodex.runtime_native.library_tools import LibraryToolsData
from oneirodex.runtime_native.library_tools_manual_identify import ManualIdentifyListData
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.routes_apis import apis_bp
import oneirodex.routes_apis.library_tools  # register the legacy route on apis_bp
from asgi import _install_native_api_error_handlers


class FakeToolsData:
    def __init__(self):
        self.library_row = SimpleNamespace(uuid='lib-1', name='Library', scan_depth=2)
        self.games = [SimpleNamespace(uuid='game-1', name='Game', full_disk_path='/safe/Game')]
        self.calls = []

    def allowed_bases(self, _app):
        return ['/safe']

    def library(self, _app, uid):
        return self.library_row if uid == 'lib-1' else None

    def allowed_extensions(self, _app):
        return ['.iso']

    def resolve_scan_path(self, _app, folder, root):
        self.calls.append(('resolve', folder, root))
        return '/safe/scan', None

    def safe_path(self, _app, path):
        return (str(path).startswith('/safe'), 'outside allowed roots')

    def readable_directory(self, path):
        return path.startswith('/safe')

    def scan_mode(self, _app, path, requested):
        return 'folders' if requested == 'folders' else 'files'

    def games_in_folder(self, _app, path, library):
        self.calls.append(('folders', path, library.uuid))
        return [{'name': 'Game', 'full_path': '/safe/Game'}]

    def games_in_files(self, _app, path, extensions):
        self.calls.append(('files', path, tuple(extensions)))
        return [{'name': 'Disc', 'full_path': '/safe/disc.iso'}]

    def propose_leaf_libraries(self, root):
        self.calls.append(('propose', root))
        return [{'path': '/safe/Console/Game', 'suggested_name': 'Game'}]

    def import_preview(self, payload, *, csv_format, allowed_bases):
        self.calls.append(('import', payload, csv_format, tuple(allowed_bases)))
        return {'status': 'success', 'auto_create': False, 'candidates': [], 'errors': [],
                'count': 0, 'error_count': 0, 'create_hint': 'manual'}

    def libraries_and_games(self, _app):
        return [(self.library_row, self.games)]

    def proposal_path(self, path):
        return path + '/oneirodex.proposal.json' if path == '/safe/Game' else None

    def read_proposal(self, path):
        self.calls.append(('read_proposal', path))
        return {'igdb_id': 44}

    def iter_game_folders(self, root):
        self.calls.append(('walk', root))
        return ['/safe/Game', '/outside/escape']

    def doctor_dry_run(self, roots, *, template, limit):
        self.calls.append(('doctor', roots, template, limit))
        return [{'path': '/safe/Game', 'proposed_name': 'Game'}]


@pytest.fixture
def runtime():
    flask_app = Flask('library-tools-test')
    flask_app.config.update(
        SECRET_KEY='library-tools-test-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
    )
    users = {
        'admin': SimpleNamespace(id=7, role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=8, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule('/api/options-mixed', endpoint='options_mixed',
                           view_func=lambda: 'ok', methods=['GET', 'POST'])
    flask_app.register_blueprint(apis_bp, url_prefix='/api')
    fake = FakeToolsData()
    app = FastAPI()
    app.include_router(create_library_tools_router(
        flask_app, find_user=lambda uid: next((u for u in users.values() if u.id == uid), None),
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=fake,
    ))
    app.include_router(create_library_tools_mutations_router(
        flask_app, find_user=lambda uid: next((u for u in users.values() if u.id == uid), None),
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=fake,
    ))
    app.state.legacy_flask_app = flask_app
    app.add_api_route('/api/options-mixed', lambda: 'ok', methods=['GET', 'POST'])
    app.state.legacy_options_allow = flask_app.test_client().options(
        '/api/options-mixed'
    ).headers['Allow']
    _install_native_api_error_handlers(app, flask_app, flask_app.logger, routing_app=flask_app)
    cookies = {name: dump_session_cookie(
        {'_user_id': f'{user.id}:fp', '_fresh': True}, 'library-tools-test-secret'
    ) for name, user in users.items()}
    return app, fake, cookies


def _request(app, path, *, cookie=None, method='GET', json=None, headers=None, content=None):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, json=json, content=content,
                                        headers=headers or {}, follow_redirects=False)
    return asyncio.run(perform())


def test_admin_read_routes_preserve_contracts_and_safe_paths(runtime):
    app, data, cookies = runtime
    preview = _request(app, '/api/library_tools/manual_identify/preview?library_uuid=lib-1&scan_mode=folders',
                       cookie=cookies['admin'])
    propose = _request(app, '/api/library_tools/propose_leaf_libraries?root=%2Fsafe',
                       cookie=cookies['admin'])
    proposals = _request(app, '/api/library_tools/proposals', cookie=cookies['admin'])
    scan = _request(app, '/api/library_tools/proposals/scan_roots', cookie=cookies['admin'],
                    method='POST', json={'roots': ['/safe']})
    scan_options = _request(app, '/api/library_tools/proposals/scan_roots', method='OPTIONS')
    doctor = _request(app, '/api/library_tools/doctor/dry_run', cookie=cookies['admin'],
                      method='POST', json={'roots': ['/safe'], 'limit': 8})

    assert preview.status_code == propose.status_code == proposals.status_code == 200
    assert preview.json()['read_only'] is True
    assert preview.json()['games'][0]['name'] == 'Game'
    assert propose.json()['auto_create'] is False
    assert proposals.json()['proposals'][0]['proposal']['igdb_id'] == 44
    assert scan.json()['proposals'] == [{'path': '/safe/Game', 'proposal': {'igdb_id': 44}}]
    assert scan_options.status_code == 200
    assert scan_options.headers['content-type'] == 'text/html; charset=utf-8'
    assert scan_options.headers['allow'] == 'OPTIONS, POST'
    assert scan_options.headers['content-length'] == '0'
    assert scan_options.content == b''
    assert doctor.json()['count'] == 1
    assert ('walk', '/safe') in data.calls
    assert ('doctor', ['/safe'], '{title}', 8) in data.calls


def test_automatic_options_preserves_flask_method_order(runtime):
    app, _data, _cookies = runtime
    response = _request(app, '/api/options-mixed', method='OPTIONS')

    assert response.status_code == 200
    assert response.headers['allow'] == app.state.legacy_options_allow
    assert response.content == b''


def test_admin_required_and_out_of_root_path_rejected_before_adapter_work(runtime):
    app, data, cookies = runtime
    denied = _request(app, '/api/library_tools/propose_leaf_libraries?root=%2Fsafe',
                      cookie=cookies['member'])
    unsafe = _request(app, '/api/library_tools/proposals/scan_roots', cookie=cookies['admin'],
                      method='POST', json={'roots': ['/outside']})

    assert denied.status_code == 302
    assert unsafe.status_code == 200
    assert unsafe.json()['proposals'] == []
    assert not any(call[0] == 'walk' for call in data.calls)
    assert not any(call[0] == 'propose' for call in data.calls)


@pytest.mark.parametrize('identity', [None, 'member'])
@pytest.mark.parametrize('path', [
    '/api/library_tools/doctor/dry_run',
    '/api/library_tools/doctor/write_proposals',
    '/api/library_tools/doctor/apply_renames',
])
def test_library_doctor_auth_matches_legacy_flask(runtime, identity, path):
    app, _data, cookies = runtime
    legacy_client = app.state.legacy_flask_app.test_client()
    cookie = cookies[identity] if identity else None
    if identity:
        with legacy_client.session_transaction() as session:
            session['_user_id'] = '8:fp'
            session['_fresh'] = True

    legacy = legacy_client.post(
        path, json={'roots': ['/safe'], 'rows': []},
    )
    native = _request(
        app, path, cookie=cookie, method='POST',
        json={'roots': ['/safe'], 'rows': []},
    )

    assert native.status_code == legacy.status_code
    assert native.headers.get('location') == legacy.headers.get('Location')
    assert native.headers.get('content-type') == legacy.headers.get('Content-Type')
    assert native.content == legacy.data


def test_import_preview_json_and_multipart_use_injected_parser(runtime):
    app, data, cookies = runtime
    json_result = _request(app, '/api/library_tools/import_leaf_libraries/preview',
                           cookie=cookies['admin'], method='POST', json={'items': []})
    multipart = _request(
        app, '/api/library_tools/import_leaf_libraries/preview', cookie=cookies['admin'],
        method='POST', content=b'--x\r\nContent-Disposition: form-data; name="file"; filename="items.csv"\r\n'
        b'Content-Type: text/csv\r\n\r\npath,name\r\n/safe,Library\r\n--x--\r\n',
        headers={'Content-Type': 'multipart/form-data; boundary=x'},
    )

    assert json_result.status_code == multipart.status_code == 200
    assert json_result.json()['auto_create'] is False
    assert multipart.json()['auto_create'] is False
    assert ('import', {'items': []}, False, ('/safe',)) in data.calls
    assert ('import', 'path,name\r\n/safe,Library', True, ('/safe',)) in data.calls


def test_native_library_helpers_use_explicit_config_without_app_context(tmp_path, monkeypatch):
    from oneirodex.utils import functions, gamenames

    flask_app = Flask('native-library-config-only')
    flask_app.config.update(
        DATA_FOLDER_GAMES=str(tmp_path),
        BASE_FOLDER_POSIX=str(tmp_path),
        BASE_FOLDER_WINDOWS=str(tmp_path),
        LIBRARY_ROOTS=[],
    )
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    (tmp_path / 'archive.iso').write_bytes(b'rom')

    for data in (LibraryToolsData(), ManualIdentifyListData()):
        folder, error = data.resolve_scan_path(flask_app, 'archive.iso', 'games')
        assert error is None
        assert folder == str(tmp_path / 'archive.iso')
        assert data.scan_mode(flask_app, str(tmp_path), 'folders') == 'folders'
        monkeypatch.setattr(functions, 'load_scanning_filter_patterns', lambda: ([], []))
        monkeypatch.setattr(functions, 'load_skip_dir_patterns', lambda: [])
        monkeypatch.setattr(functions, 'load_skip_dir_regex_patterns', lambda: [])
        monkeypatch.setattr(gamenames, 'get_game_names_from_files', lambda *args: ['Disc'])
        monkeypatch.setattr(gamenames, 'get_game_names_from_folder', lambda *args, **kwargs: ['Folder'])
        assert data.games_in_files(flask_app, str(tmp_path), ['.iso']) == ['Disc']
        assert data.games_in_folder(flask_app, str(tmp_path), SimpleNamespace(scan_depth=1)) == ['Folder']

