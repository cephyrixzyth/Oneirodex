from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.game_mods import create_game_mods_router
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.utils.game_mods import mod_config_scope, mods_enabled, mods_root


def test_mod_settings_scope_works_without_a_flask_app_context(tmp_path):
    settings = {
        'ENABLE_MOD_TRACKING': 'false',
        'GAME_MODS_PATH': str(tmp_path),
    }
    with mod_config_scope(settings):
        assert mods_enabled() is False
        assert mods_root() == str(tmp_path)


class FakeModsData:
    def __init__(self):
        self.is_enabled = True
        self.games = {
            'game-1': SimpleNamespace(uuid='game-1', name='Test Game', library_uuid='lib-1'),
            'hidden-game': SimpleNamespace(uuid='hidden-game', name='Hidden', library_uuid='lib-2'),
        }
        self.access = {'game-1': True, 'hidden-game': False}
        self.packs = {
            'game-1': {
                'game_uuid': 'game-1', 'default_loader': 'bepinex', 'loaders': ['bepinex'],
                'mods': [{'id': 'mod-1', 'name': 'Mod One', 'enabled': True}],
                'profiles': [{'id': 'default', 'name': 'Default', 'mod_ids': ['mod-1']}],
                'active_profile': 'default',
            },
        }
        self.calls = []

    def enabled(self, _app):
        return self.is_enabled

    def game(self, _app, uid):
        self.calls.append(('game', uid))
        return self.games.get(uid)

    def accessible_games(self, _app, _user):
        return [game for game in self.games.values() if self.access.get(game.uuid)]

    def can_access_game(self, _app, _user, game):
        return self.access.get(game.uuid, False)

    def load_mods(self, _app, uid):
        self.calls.append(('load', uid))
        if uid == 'io-error':
            raise OSError('C:/private/library/mods/secret')
        return self.packs.get(uid, {
            'game_uuid': uid, 'default_loader': '', 'loaders': [], 'mods': [],
            'profiles': [], 'active_profile': '',
        })

    def mods_summary(self, _app, uuids):
        self.calls.append(('summary', tuple(uuids)))
        return [{'game_uuid': uid, 'mod_count': len(self.packs.get(uid, {}).get('mods', [])),
                 'enabled_count': 1} for uid in uuids if self.packs.get(uid, {}).get('mods')]

    def loader_conflicts(self, _app, pack):
        return [{'id': 'mod-1', 'name': 'Mod One', 'loader': 'other', 'default_loader': 'bepinex'}]

    def catalog_sources(self):
        return ['modrinth', 'thunderstore']

    def catalog_search(self, _app, source, game_name, query, limit, tracked):
        self.calls.append(('catalog', source, game_name, query, limit, tuple(m['id'] for m in tracked)))
        return {'status': 'ok', 'hits': [{'id': 'catalog-1', 'name': 'Sample'}]}

    def create_mod(self, _app, uid, body):
        self.calls.append(('create_mod', uid, body))
        if body.get('id') == 'mod-1':
            raise ValueError('Mod id already exists')
        row = {'id': body.get('id') or 'created', 'name': body.get('name') or 'created'}
        self.packs[uid]['mods'].append(row)
        return row

    def update_mod(self, _app, uid, mod_id, body):
        self.calls.append(('update_mod', uid, mod_id, body))
        if mod_id != 'mod-1':
            raise LookupError
        return {'id': mod_id, **body}

    def delete_mod(self, _app, uid, mod_id):
        self.calls.append(('delete_mod', uid, mod_id))
        return mod_id == 'mod-1'

    def save_mods(self, _app, uid, mods, default_loader):
        self.calls.append(('save_mods', uid, mods, default_loader))
        return {'game_uuid': uid, 'mods': mods, 'default_loader': default_loader or 'bepinex'}

    def set_default_loader(self, _app, uid, loader):
        self.calls.append(('default_loader', uid, loader))
        return {'game_uuid': uid, 'default_loader': loader or ''}

    def list_profiles(self, _app, uid):
        pack = self.packs.get(uid, {})
        return {'profiles': list(pack.get('profiles', [])),
                'active_profile': pack.get('active_profile', '')}

    def create_profile(self, _app, uid, name, mod_ids):
        self.calls.append(('create_profile', uid, name, mod_ids))
        profile = {'id': 'imported', 'name': name, 'mod_ids': mod_ids or ['mod-1']}
        self.packs[uid]['profiles'].append(profile)
        return profile

    def delete_profile(self, _app, uid, profile_id):
        self.calls.append(('delete_profile', uid, profile_id))
        return profile_id == 'default'

    def activate_profile(self, _app, uid, profile_id):
        self.calls.append(('activate_profile', uid, profile_id))
        if profile_id != 'default':
            raise LookupError
        return {'game_uuid': uid, 'active_profile': profile_id, 'mods': self.packs[uid]['mods']}

    def export_profile(self, _app, uid, profile_id):
        self.calls.append(('export_profile', uid, profile_id))
        if profile_id != 'default':
            raise LookupError
        return 'od-mod:fake-code'

    def import_profile(self, _app, uid, code, name):
        self.calls.append(('import_profile', uid, code, name))
        if not code.startswith('od-mod:'):
            raise ValueError('Not an Oneirodex mod profile code')
        return {'profile': {'id': 'imported', 'name': name or 'Imported'}, 'matched': 1, 'missing': []}


@pytest.fixture
def runtime():
    flask_app = Flask('game-mods-test')
    flask_app.config.update(
        SECRET_KEY='game-mods-test-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
        ENABLE_MOD_TRACKING='true',
    )
    users = {
        'admin': SimpleNamespace(id=7, role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'librarian': SimpleNamespace(id=8, role='librarian', state=True, is_active=True,
                                     is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=9, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'child': SimpleNamespace(id=10, role='child', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    fake = FakeModsData()
    tokens = {}
    app = FastAPI()
    app.include_router(create_game_mods_router(
        flask_app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda prefix: tokens.get(prefix), commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=fake,
    ))
    cookies = {
        name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                  'game-mods-test-secret')
        for name, user in users.items()
    }
    return app, flask_app, fake, users, tokens, cookies


def _request(app, path, *, cookie=None, method='GET', json=None, headers=None):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, json=json, headers=headers or {}, follow_redirects=False)

    return asyncio.run(perform())


def test_anonymous_redirect_and_child_filtered_summary(runtime):
    app, _flask_app, _data, _users, _tokens, cookies = runtime
    anon = _request(app, '/api/mods/summary')
    child = _request(app, '/api/mods/summary', cookie=cookies['child'])

    assert anon.status_code == 302
    assert anon.headers['location'] == '/login?next=%2Fapi%2Fmods%2Fsummary'
    assert child.json() == {
        'enabled': True,
        'games': [{'game_uuid': 'game-1', 'mod_count': 1, 'enabled_count': 1,
                   'game_name': 'Test Game'}],
    }


def test_member_reads_pack_and_catalog_requires_librarian(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    read = _request(app, '/api/games/game-1/mods', cookie=cookies['member'])
    denied = _request(app, '/api/games/game-1/mods/catalog?source=modrinth', cookie=cookies['member'])
    hidden = _request(app, '/api/games/hidden-game/mods', cookie=cookies['member'])

    assert read.status_code == 200
    assert read.json()['mods'][0]['id'] == 'mod-1'
    assert read.json()['loader_conflicts'][0]['loader'] == 'other'
    assert denied.status_code == 403
    assert hidden.status_code == 403
    assert not any(call[0] == 'catalog' for call in data.calls)


def test_librarian_catalog_and_mod_crud_validation(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    catalog = _request(
        app, '/api/games/game-1/mods/catalog?source=modrinth&q=hello&limit=4',
        cookie=cookies['librarian'],
    )
    created = _request(
        app, '/api/games/game-1/mods', cookie=cookies['librarian'], method='POST',
        json={'id': 'mod-2', 'name': 'Added'},
    )
    invalid = _request(
        app, '/api/games/game-1/mods', cookie=cookies['librarian'], method='POST', json={'extra': True},
    )
    updated = _request(
        app, '/api/games/game-1/mods/mod-1', cookie=cookies['librarian'], method='PATCH',
        json={'version': '2'},
    )
    deleted = _request(
        app, '/api/games/game-1/mods/mod-1', cookie=cookies['librarian'], method='DELETE',
    )

    assert catalog.status_code == 200 and catalog.json()['hits'][0]['id'] == 'catalog-1'
    assert ('catalog', 'modrinth', 'Test Game', 'hello', 4, ('mod-1',)) in data.calls
    assert created.status_code == 201 and created.json()['mod']['id'] == 'mod-2'
    assert invalid.status_code == 422
    assert updated.json()['mod']['version'] == '2'
    assert deleted.json()['id'] == 'mod-1'


def test_bulk_pack_profiles_import_export_activate_and_delete(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    bulk = _request(
        app, '/api/games/game-1/mods', cookie=cookies['admin'], method='PUT',
        json={'mods': [{'id': 'mod-1', 'enabled': False}], 'default_loader': 'manual'},
    )
    pack = _request(
        app, '/api/games/game-1/mods/pack', cookie=cookies['admin'], method='PATCH',
        json={'default_loader': 'forge'},
    )
    profiles = _request(app, '/api/games/game-1/mods/profiles', cookie=cookies['member'])
    created_profile = _request(
        app, '/api/games/game-1/mods/profiles', cookie=cookies['librarian'], method='POST',
        json={'name': ' Co-op '},
    )
    exported = _request(
        app, '/api/games/game-1/mods/profiles/default/export', cookie=cookies['member'],
    )
    imported = _request(
        app, '/api/games/game-1/mods/profiles/import', cookie=cookies['librarian'], method='POST',
        json={'code': 'od-mod:valid-code'},
    )
    activated = _request(
        app, '/api/games/game-1/mods/profiles/default/activate',
        cookie=cookies['librarian'], method='POST',
    )
    deleted = _request(
        app, '/api/games/game-1/mods/profiles/default',
        cookie=cookies['librarian'], method='DELETE',
    )

    assert bulk.json()['mods'][0]['enabled'] is False
    assert pack.json()['default_loader'] == 'forge'
    assert profiles.json()['profiles'][0]['id'] == 'default'
    assert created_profile.status_code == 201
    assert exported.json()['code'] == 'od-mod:fake-code'
    assert imported.status_code == 201 and imported.json()['matched'] == 1
    assert activated.json()['active_profile'] == 'default'
    assert deleted.json()['id'] == 'default'
    assert ('activate_profile', 'game-1', 'default') in data.calls


def test_feature_gates_and_csrf_precedes_auth(runtime):
    app, flask_app, data, _users, _tokens, _cookies = runtime
    data.is_enabled = False
    assert _request(app, '/api/mods/summary').status_code == 302
    disabled_summary = _request(app, '/api/mods/summary', cookie=_cookies['member'])
    disabled_detail = _request(app, '/api/games/game-1/mods', cookie=_cookies['member'])
    assert disabled_summary.json() == {'enabled': False, 'games': []}
    assert disabled_detail.json() == {'enabled': False, 'mods': []}
    assert _request(app, '/api/games/game-1/mods/profiles', cookie=_cookies['member']).status_code == 403

    data.is_enabled = True
    flask_app.config['WTF_CSRF_ENABLED'] = True
    response = _request(
        app, '/api/games/game-1/mods', method='POST', json={'name': 'x'},
    )
    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'


def test_bearer_librarian_requires_admin_scope_and_errors_hide_paths(runtime):
    app, _flask_app, data, _users, tokens, _cookies = runtime
    token = SimpleNamespace(
        user_id=8, token_hash=hashlib.sha256(b'secret').hexdigest(), revoked_at=None,
        scopes=['read:library'], last_used_at=None,
        has_scope=lambda scope: scope in ['read:library'],
    )
    tokens['prefix'] = token
    denied = _request(
        app, '/api/games/game-1/mods', method='POST', json={'name': 'x'},
        headers={'Authorization': 'Bearer gt_prefix_secret'},
    )
    assert denied.status_code == 403
    assert not any(call[0] == 'create_mod' for call in data.calls)

    data.games['io-error'] = SimpleNamespace(
        uuid='io-error', name='Broken', library_uuid='lib-1',
    )
    data.access['io-error'] = True
    broken = _request(app, '/api/games/io-error/mods', cookie=_cookies['member'])
    assert broken.status_code == 500
    assert 'C:/private' not in broken.text
