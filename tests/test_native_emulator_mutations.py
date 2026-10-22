from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.emulator_mutations import create_emulator_mutations_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.models import PcCheat


class FakeData:
    def __init__(self):
        self.game_row = SimpleNamespace(uuid='game-1')
        self.surface = 'retroarch'
        self.allowed = True
        self.fail_pc_cheat_delete = False
        self.calls = []
        self.saves = []

    def game(self, game_uuid):
        self.calls.append(('game', game_uuid))
        return self.game_row if game_uuid == 'game-1' else None

    def can_access(self, user, game):
        self.calls.append(('access', user.id, game.uuid))
        return self.allowed

    def cheat_surface(self, game):
        return self.surface

    def list_cheats(self, game_uuid):
        self.calls.append(('list_cheats', game_uuid))
        return [{'name': 'codes.cht', 'size': 3, 'url': f'/api/games/{game_uuid}/cheats/codes.cht'}]

    def read_cheat(self, game_uuid, filename):
        self.calls.append(('read_cheat', game_uuid, filename))
        return b'cheat'

    def store_cheat(self, game_uuid, filename, payload):
        self.calls.append(('store_cheat', game_uuid, filename, payload))
        return {'name': filename, 'size': len(payload), 'url': f'/api/games/{game_uuid}/cheats/{filename}'}

    def create_cheat(self, game_uuid, *, name, codes, dialect=None):
        self.calls.append(('create_cheat', game_uuid, name, codes, dialect))
        return {'name': 'created.cht', 'size': 5, 'created': True}

    def delete_cheat(self, game_uuid, filename):
        self.calls.append(('delete_cheat', game_uuid, filename))

    def save_sync_enabled(self):
        return True

    def list_saves(self, user_id, game_uuid):
        self.calls.append(('list_saves', user_id, game_uuid))
        return list(self.saves)

    def is_state_slot(self, row):
        return row.slot_name != 'cloud-sram'

    def store_save(self, user_id, game_uuid, slot_name, filename, payload):
        self.calls.append(('store_save', user_id, game_uuid, slot_name, filename, payload))
        row = FakeSave(slot_name, filename or 'state.srm', payload)
        self.saves.append(row)
        return row

    def read_save(self, row):
        return row.payload

    def delete_save(self, user_id, game_uuid, slot_name):
        self.calls.append(('delete_save', user_id, game_uuid, slot_name))
        return False

    def pc_cheats(self, game_uuid):
        self.calls.append(('pc_cheats', game_uuid))
        return []

    def create_pc_cheat(self, **values):
        self.calls.append(('create_pc_cheat', values))
        return SimpleNamespace(to_dict=lambda: {'id': 42, **values})

    def delete_pc_cheat(self, game_uuid, cheat_id):
        self.calls.append(('delete_pc_cheat', game_uuid, cheat_id))
        if self.fail_pc_cheat_delete:
            raise RuntimeError('injected delete failure')
        return cheat_id == 42

    def bios_overview(self, flask_app):
        self.calls.append(('bios_overview', flask_app.config.get('BIOS_IMPORT_SOURCE')))
        return {'files': [], 'cores': {}, 'platforms': {}, 'import_source': '', 'missing_markdown': ''}

    def firmware_source_isdir(self, source):
        return source == '/allowed/firmware'

    def firmware_source_allowed(self, source, flask_app):
        return source == '/allowed/firmware'

    def scan_firmware(self, source):
        self.calls.append(('scan_firmware', source))
        return {'files': [{'name': 'bios.bin'}]}

    def install_firmware(self, source, *, selections, skipped, overwrite):
        self.calls.append(('install_firmware', source, selections, skipped, overwrite))
        return {'installed': 1, 'skipped': skipped}

    def upload_bios(self, filename, payload):
        self.calls.append(('upload_bios', filename, payload))
        return {'filename': filename}


class FakeSave:
    def __init__(self, slot_name, filename, payload):
        self.slot_name = slot_name
        self.filename = filename
        self.payload = payload
        self.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def to_dict(self):
        return {'slot_name': self.slot_name, 'filename': self.filename, 'size_bytes': len(self.payload)}


@pytest.fixture
def native():
    app = Flask(__name__)
    app.config.update(SECRET_KEY='native-emulator-secret', TESTING=True)
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    manager = LoginManager(app)
    user = SimpleNamespace(id=7, role='user', is_active=True, is_authenticated=True,
                           session_fingerprint=lambda: 'fp')
    manager.user_loader(lambda identity: user if identity == '7:fp' else None)
    data = FakeData()
    app._user = user
    api = FastAPI()
    api.include_router(create_emulator_mutations_router(
        app, find_user=lambda _user_id: user, find_token=lambda _token: None,
        commit_token_touch=lambda _token: None, load_user_id=manager._user_callback,
        login_manager=manager, data_access=data,
    ))
    return app, api, data, user


def _cookie(app, *, csrf=False):
    session = {'_user_id': '7:fp', '_fresh': True}
    token = generate_csrf_token(session, app.secret_key) if csrf else None
    return dump_session_cookie(session, app.secret_key), token


def _request(app, method, path, *, cookie=None, csrf=None, **kwargs):
    async def perform():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            if cookie:
                client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if csrf else {}
            headers.update(kwargs.pop('extra_headers', {}))
            return await client.request(method, path, headers=headers, follow_redirects=False, **kwargs)
    return asyncio.run(perform())


def test_cheat_list_download_and_create_keep_legacy_shapes(native):
    app, api, data, _ = native
    cookie, csrf = _cookie(app, csrf=True)

    listed = _request(api, 'GET', '/api/games/game-1/cheats', cookie=cookie)
    head = _request(api, 'HEAD', '/api/games/game-1/cheats/codes.cht', cookie=cookie)
    downloaded = _request(api, 'GET', '/api/games/game-1/cheats/codes.cht', cookie=cookie)
    created = _request(api, 'POST', '/api/games/game-1/cheats', cookie=cookie, csrf=csrf,
                       json={'name': 'new', 'codes': [{'code': 'AA'}]})

    assert listed.json() == {'game_uuid': 'game-1', 'cheat_surface': 'retroarch', 'cheats': [
        {'name': 'codes.cht', 'size': 3, 'url': '/api/games/game-1/cheats/codes.cht'}]}
    assert downloaded.content == b'cheat'
    assert head.status_code == 200 and head.content == b''
    assert downloaded.headers['content-disposition'].endswith('filename="codes.cht"')
    assert created.status_code == 201 and created.json()['name'] == 'created.cht'
    assert ('create_cheat', 'game-1', 'new', [{'code': 'AA'}], None) in data.calls


def test_pc_cheats_options_matches_legacy_allow_header(native):
    _app, api, _data, _user = native

    response = _request(api, 'OPTIONS', '/api/games/game-1/pc_cheats')

    assert response.status_code == 200
    assert response.headers['allow'] == 'OPTIONS, GET, HEAD, POST'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.content == b''


def test_pc_cheat_created_at_keeps_legacy_naive_utc_format():
    row = PcCheat(
        id=1,
        game_uuid='game-1',
        method='note',
        label='Example',
        created_at=datetime(2026, 10, 22, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert row.to_dict()['created_at'] == '2026-10-22T12:34:56'


def test_writes_reject_missing_csrf_before_authentication(native):
    _app, api, data, _ = native
    response = _request(api, 'POST', '/api/games/game-1/cheats', json={'name': 'new', 'codes': []})

    assert response.status_code == 400
    assert 'CSRF token is missing' in response.json()['error']
    assert data.calls == []
    assert _request(api, 'POST', '/api/games/game-1/cheats', json={'name': 'new', 'codes': []}).status_code == 400


@pytest.mark.parametrize(('path', 'payload'), [
    ('/api/emulator-bios', {}),
    ('/api/emulator-bios/scan', {'source': '/allowed/firmware'}),
    ('/api/emulator-bios/install', {'source': '/allowed/firmware'}),
])
def test_anonymous_firmware_posts_redirect_before_csrf(native, path, payload):
    app, api, data, _ = native
    app.login_manager.login_view = 'login.login'

    response = _request(api, 'POST', path, json=payload)

    assert response.status_code == 302
    assert response.headers['location'] == f'/login?next={path.replace('/', '%2F')}'
    assert data.calls == []


def test_authenticated_non_admin_firmware_post_still_checks_csrf_before_role(native):
    app, api, data, _ = native
    cookie, _ = _cookie(app)

    response = _request(api, 'POST', '/api/emulator-bios/scan', cookie=cookie,
                        json={'source': '/allowed/firmware'})

    assert response.status_code == 400
    assert 'CSRF token is missing' in response.json()['error']
    assert data.calls == []


def test_save_upload_list_download_and_delete_keep_user_scoping(native):
    app, api, data, _ = native
    cookie, csrf = _cookie(app, csrf=True)
    upload = _request(api, 'POST', '/api/games/game-1/saves?slot=qs-one', cookie=cookie, csrf=csrf,
                      files={'file': ('save.state', b'bytes')})
    listing = _request(api, 'GET', '/api/games/game-1/saves', cookie=cookie)
    download = _request(api, 'GET', '/api/games/game-1/saves/qs-one', cookie=cookie)
    deleted = _request(api, 'DELETE', '/api/games/game-1/saves/absent', cookie=cookie, csrf=csrf)

    assert upload.status_code == 201 and upload.json()['slot_name'] == 'qs-one'
    assert listing.json()['game_uuid'] == 'game-1'
    assert listing.json()['saves'][0]['is_state'] is True
    assert listing.json()['csrf_token']
    assert download.content == b'bytes'
    assert deleted.status_code == 404
    assert ('store_save', 7, 'game-1', 'qs-one', 'save.state', b'bytes') in data.calls


def test_game_acl_and_platform_rules_are_enforced(native):
    app, api, data, user = native
    cookie, csrf = _cookie(app, csrf=True)
    data.allowed = False
    denied = _request(api, 'GET', '/api/games/game-1/cheats', cookie=cookie)
    assert denied.status_code == 403
    assert denied.json()['error'] == 'You do not have access to that game'

    data.allowed = True
    data.surface = 'none'
    listing = _request(api, 'GET', '/api/games/game-1/cheats', cookie=cookie)
    refused = _request(api, 'POST', '/api/games/game-1/cheats', cookie=cookie, csrf=csrf,
                       json={'name': 'new', 'codes': []})
    assert listing.json()['cheats'] == []
    assert refused.status_code == 403 and refused.json()['cheat_surface'] == 'none'
    assert not any(call[0] in {'list_cheats', 'create_cheat'} for call in data.calls)


def test_child_cannot_write_cheats_and_pc_cheat_librarian_rules(native):
    app, api, data, user = native
    cookie, csrf = _cookie(app, csrf=True)
    user.role = 'child'
    denied = _request(api, 'POST', '/api/games/game-1/cheats', cookie=cookie, csrf=csrf,
                      json={'name': 'new', 'codes': []})
    assert denied.status_code == 403

    user.role = 'librarian'
    data.surface = 'pc_wand'
    created = _request(api, 'POST', '/api/games/game-1/pc_cheats', cookie=cookie, csrf=csrf,
                       json={'label': '  helpful note  ', 'method': 'note', 'notes': ' details '})
    assert created.status_code == 201
    saved = next(call[1] for call in data.calls if call[0] == 'create_pc_cheat')
    assert saved['label'] == 'helpful note' and saved['notes'] == 'details'


def test_pc_cheat_delete_keeps_legacy_denial_and_database_error_messages(native):
    app, api, data, user = native
    cookie, csrf = _cookie(app, csrf=True)
    data.surface = 'pc_wand'

    denied = _request(api, 'DELETE', '/api/games/game-1/pc_cheats/42', cookie=cookie, csrf=csrf)
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Librarian or admin required'

    user.role = 'admin'
    data.fail_pc_cheat_delete = True
    failed = _request(api, 'DELETE', '/api/games/game-1/pc_cheats/42', cookie=cookie, csrf=csrf)
    assert failed.status_code == 500
    assert failed.json()['error'] == 'Something went wrong on our end. The error has been logged.'


def test_bios_admin_reads_scan_install_and_upload_use_fake_storage(native):
    app, api, data, user = native
    user.role = 'admin'
    cookie, csrf = _cookie(app, csrf=True)

    overview = _request(api, 'GET', '/api/emulator-bios', cookie=cookie)
    overview_head = _request(api, 'HEAD', '/api/emulator-bios', cookie=cookie)
    scan = _request(api, 'POST', '/api/emulator-bios/scan', cookie=cookie, csrf=csrf,
                    json={'source': '/allowed/firmware'})
    install = _request(api, 'POST', '/api/emulator-bios/install', cookie=cookie, csrf=csrf,
                       json={'source': '/allowed/firmware', 'selections': {'bios.bin': 'Sega'},
                             'skipped': ['other.bin'], 'overwrite': True})
    upload = _request(api, 'POST', '/api/emulator-bios', cookie=cookie, csrf=csrf,
                      files={'file': ('bios.bin', b'fixture')})

    assert overview.status_code == 200 and overview.json()['files'] == []
    assert overview_head.status_code == 200 and overview_head.content == b''
    assert overview_head.headers['content-type'] == overview.headers['content-type']
    assert scan.json()['files'] == [{'name': 'bios.bin'}]
    assert install.json()['installed'] == 1
    assert upload.status_code == 201 and upload.json()['filename'] == 'bios.bin'
    assert ('upload_bios', 'bios.bin', b'fixture') in data.calls


def test_multipart_upload_rejects_declared_and_streamed_oversize_before_form_parse(native):
    from starlette.requests import Request
    from oneirodex.runtime_native.emulator_mutations import _bounded_form

    app, api, data, _ = native
    app.config['MAX_CONTENT_LENGTH'] = 64
    cookie, csrf = _cookie(app, csrf=True)
    declared = _request(
        api, 'POST', '/api/games/game-1/cheats', cookie=cookie, csrf=csrf,
        content=b'', extra_headers={'Content-Type': 'multipart/form-data; boundary=test', 'Content-Length': '65'},
    )
    assert declared.status_code == 413
    assert declared.json()['error_code'] == 'payload_too_large'
    assert not any(call[0] == 'store_cheat' for call in data.calls)

    chunks = [b'abcd', b'efgh']

    async def receive():
        if chunks:
            return {'type': 'http.request', 'body': chunks.pop(0), 'more_body': bool(chunks)}
        return {'type': 'http.disconnect'}

    request = Request({'type': 'http', 'method': 'POST', 'path': '/upload', 'headers': []}, receive)
    form, error = asyncio.run(_bounded_form(request, {'MAX_CONTENT_LENGTH': 6, 'MAX_UPLOAD_MB': 1}))
    assert form is None and error.status_code == 413
