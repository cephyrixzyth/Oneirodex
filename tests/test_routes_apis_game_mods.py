"""Tests for per-game mod registry API (MOD-1/2)."""

from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def librarian_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'lib_{uid[:8]}',
        email=f'lib_{uid[:8]}@test.com',
        role='librarian',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def child_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'child_{uid[:8]}',
        email=f'child_{uid[:8]}@test.com',
        role='child',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'admin_{uid[:8]}',
        email=f'admin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def regular_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'user_{uid[:8]}',
        email=f'user_{uid[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_game(db_session):
    library = Library(name=f'ModLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    game = Game(
        name='Mod Test Game',
        library_uuid=library.uuid,
        full_disk_path=f'/tmp/{uuid4().hex}',
    )
    db_session.add(game)
    db_session.commit()
    return game


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestGameModsApi:
    def test_get_mods_requires_login(self, client, sample_game):
        response = client.get(f'/api/games/{sample_game.uuid}/mods')
        assert response.status_code in (302, 401)

    def test_create_and_crud_mod(self, client, librarian_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        create = client.post(
            f'/api/games/{sample_game.uuid}/mods',
            json={
                'name': 'HD Texture Pack',
                'version': '1.2',
                'source_url': 'https://example.com/mod.zip',
                'enabled': True,
                'load_order': 0,
            },
        )
        assert create.status_code == 201
        mod_id = create.get_json()['mod']['id']

        listing = client.get(f'/api/games/{sample_game.uuid}/mods')
        assert listing.status_code == 200
        body = listing.get_json()
        assert body['enabled'] is True
        assert len(body['mods']) == 1
        assert body['mods'][0]['source_url'] == 'https://example.com/mod.zip'
        assert body['mods'][0]['load_order'] == 0

        patch = client.put(
            f'/api/games/{sample_game.uuid}/mods/{mod_id}',
            json={'enabled': False, 'load_order': 3},
        )
        assert patch.status_code == 200
        assert patch.get_json()['mod']['enabled'] is False

        delete = client.delete(f'/api/games/{sample_game.uuid}/mods/{mod_id}')
        assert delete.status_code == 200
        assert client.get(f'/api/games/{sample_game.uuid}/mods').get_json()['mods'] == []

    def test_child_cannot_create_mod(self, client, child_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, child_user)
        response = client.post(
            f'/api/games/{sample_game.uuid}/mods',
            json={'name': 'Blocked'},
        )
        assert response.status_code == 403

    def test_regular_user_cannot_create_mod(self, client, regular_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, regular_user)
        response = client.post(
            f'/api/games/{sample_game.uuid}/mods',
            json={'name': 'Blocked'},
        )
        assert response.status_code == 403

    def test_mods_disabled_returns_403_on_write(self, client, admin_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        app.config['ENABLE_MOD_TRACKING'] = False
        _login(client, admin_user)
        response = client.post(
            f'/api/games/{sample_game.uuid}/mods',
            json={'name': 'Off'},
        )
        assert response.status_code == 403

    def test_mods_summary_lists_accessible_games(
        self, client, librarian_user, sample_game, app, tmp_path
    ):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        client.post(
            f'/api/games/{sample_game.uuid}/mods',
            json={'name': 'Summary Mod', 'enabled': True},
        )
        response = client.get('/api/mods/summary')
        assert response.status_code == 200
        body = response.get_json()
        assert body['enabled'] is True
        assert any(row['game_uuid'] == sample_game.uuid for row in body['games'])


class TestModLoader:
    """INSP-36 / H2a: the loader a mod needs, on the row and as a pack default."""

    def test_loader_normalises_and_pack_default_survives_row_writes(self, client, librarian_user, sample_game, app, tmp_path):
        from oneirodex.utils.game_mods import LOADERS, normalize_loader

        assert normalize_loader('BepInEx 5') == 'bepinex-5'
        assert normalize_loader('  SMAPI ') == 'smapi'
        assert normalize_loader(None) == ''
        assert 'bepinex' in LOADERS and 'none' in LOADERS

        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'

        listing = client.get(base).get_json()
        assert listing['default_loader'] == '' and listing['loaders'] == list(LOADERS)

        pack = client.patch(f'{base}/pack', json={'default_loader': 'BepInEx'})
        assert pack.status_code == 200, pack.get_json()
        assert pack.get_json()['default_loader'] == 'bepinex'

        create = client.post(base, json={'name': 'Configuration Manager', 'loader': 'BepInEx', 'source_url': 'https://example.com/cm.zip'})
        assert create.status_code == 201
        mod = create.get_json()['mod']
        assert mod['loader'] == 'bepinex'
        mod_id = mod['id']

        # A row write never clears the pack default; a partial update keeps the loader
        patched = client.patch(f'{base}/{mod_id}', json={'enabled': False})
        assert patched.get_json()['mod']['loader'] == 'bepinex'
        listing = client.get(base).get_json()
        assert listing['default_loader'] == 'bepinex'

        # Bulk replace keeps the default when omitted, sets it when given
        bulk = client.put(base, json={'mods': [{'id': 'x', 'name': 'X', 'loader': 'MelonLoader'}]})
        assert bulk.status_code == 200
        assert bulk.get_json()['default_loader'] == 'bepinex'
        assert bulk.get_json()['mods'][0]['loader'] == 'melonloader'
        bulk = client.put(base, json={'mods': [], 'default_loader': 'none'})
        assert bulk.get_json()['default_loader'] == 'none'

    def test_unknown_fields_are_refused(self, client, librarian_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'
        assert client.post(base, json={'name': 'X', 'install': True}).status_code == 422
        assert client.patch(f'{base}/pack', json={'mods': []}).status_code == 422
        assert client.put(base, json={'mods': 'nope'}).status_code == 422


class TestModProfiles:
    """INSP-37 / H2d: named mod sets, one-click activate, od-mod: export / import."""

    def _seed(self, client, base):
        ids = []
        for name, url in (('A', 'https://x/a.zip'), ('B', 'https://x/b.zip'), ('C', 'https://x/c.zip')):
            r = client.post(base, json={'name': name, 'source_url': url, 'loader': 'bepinex'})
            assert r.status_code == 201
            ids.append(r.get_json()['mod']['id'])
        return ids

    def test_profiles_round_trip_and_activate_flips_enabled(self, client, librarian_user, sample_game, app, tmp_path):
        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'
        a, b, c = self._seed(client, base)

        # From the enabled set (all three), then an explicit subset
        r = client.post(f'{base}/profiles', json={'name': 'Everything'})
        assert r.status_code == 201 and r.get_json()['profile']['mod_ids'] == [a, b, c]
        r = client.post(f'{base}/profiles', json={'name': 'Vanilla+', 'mod_ids': [a, 'not-a-mod']})
        assert r.status_code == 201
        vanilla = r.get_json()['profile']
        assert vanilla['id'] == 'vanilla' and vanilla['mod_ids'] == [a]

        # Activate: only A stays enabled, the pack remembers the profile
        r = client.post(f'{base}/profiles/vanilla/activate', json={})
        assert r.status_code == 200
        pack = r.get_json()
        assert pack['active_profile'] == 'vanilla'
        assert {m['id']: m['enabled'] for m in pack['mods']} == {a: True, b: False, c: False}

        # Row writes and bulk replace keep the profiles; a deleted row drops out of the set
        client.patch(f'{base}/{b}', json={'notes': 'x'})
        client.delete(f'{base}/{c}')
        listing = client.get(f'{base}/profiles').get_json()
        assert listing['active_profile'] == 'vanilla'
        assert next(p for p in listing['profiles'] if p['id'] == 'everything')['mod_ids'] == [a, b]

        assert client.post(f'{base}/profiles/nope/activate', json={}).status_code == 404
        assert client.delete(f'{base}/profiles/vanilla').status_code == 200
        assert client.get(f'{base}/profiles').get_json()['active_profile'] == ''
        assert client.post(f'{base}/profiles', json={'name': 'X', 'extra': 1}).status_code == 422

    def test_export_code_imports_against_another_pack_and_reports_missing(self, client, librarian_user, sample_game, app, tmp_path, db_session):
        from oneirodex.utils.game_mod_profiles import decode_export

        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'
        a, b, _c = self._seed(client, base)
        client.patch(f'{base}/pack', json={'default_loader': 'bepinex'})
        client.post(f'{base}/profiles', json={'name': 'Share me', 'mod_ids': [a, b]})

        r = client.get(f'{base}/profiles/share-me/export')
        assert r.status_code == 200
        code = r.get_json()['code']
        assert code.startswith('od-mod:')
        doc = decode_export(code)
        assert doc['name'] == 'Share me' and doc['default_loader'] == 'bepinex'
        assert [m['source_url'] for m in doc['mods']] == ['https://x/a.zip', 'https://x/b.zip']

        # A second game tracks only A (by URL, different id): B comes back missing
        other = Game(uuid=str(uuid4()), name='Other', library_uuid=sample_game.library_uuid, full_disk_path=str(tmp_path / 'o'))
        db_session.add(other)
        db_session.commit()
        obase = f'/api/games/{other.uuid}/mods'
        client.post(obase, json={'name': 'A again', 'source_url': 'https://x/a.zip', 'loader': 'bepinex'})
        r = client.post(f'{obase}/profiles/import', json={'code': code})
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body['matched'] == 1 and len(body['missing']) == 1
        assert body['missing'][0]['source_url'] == 'https://x/b.zip' and body['missing'][0]['loader'] == 'bepinex'
        assert body['profile']['name'] == 'Share me' and len(body['profile']['mod_ids']) == 1
        assert body['suggested_default_loader'] == 'bepinex'
        assert body['profile']['unresolved'] == ['B']
        blocked = client.post(f"{obase}/profiles/{body['profile']['id']}/activate", json={})
        assert blocked.status_code == 409
        assert client.get(f"{obase}/profiles/{body['profile']['id']}/export").status_code == 409
        assert not client.get(obase).get_json()['active_profile']
        assert client.get(obase).get_json()['mods'].__len__() == 1  # nothing was invented

        assert client.post(f'{obase}/profiles/import', json={'code': 'not-a-code'}).status_code == 400
        assert client.post(f'{obase}/profiles/import', json={'code': 'od-mod:!!!!!!!!'}).status_code == 400

    def test_profiles_are_librarian_only_but_export_is_readable(self, client, regular_user, sample_game, app, tmp_path):
        from oneirodex.utils.game_mod_profiles import create_profile
        from oneirodex.utils.game_mods import create_mod

        app.config['GAME_MODS_PATH'] = str(tmp_path)
        # Seed through the utility layer: the harness keeps one identity per test,
        # so the member below is the only login here.
        with app.app_context():
            create_mod(sample_game.uuid, {'name': 'A', 'source_url': 'https://x/a.zip'})
            create_profile(sample_game.uuid, name='Public')
        base = f'/api/games/{sample_game.uuid}/mods'
        _login(client, regular_user)
        assert client.post(f'{base}/profiles', json={'name': 'Nope'}).status_code == 403
        assert client.post(f'{base}/profiles/public/activate', json={}).status_code == 403
        assert client.get(f'{base}/profiles/public/export').status_code == 200
        assert client.get(f'{base}/profiles').get_json()['profiles'][0]['id'] == 'public'


class TestCompatAndUpdates:
    """INSP-38 / INSP-39 / H2e: requires, the loader compat gate, update discovery."""

    def test_requires_is_kept_pruned_and_conflicts_are_reported(self, client, librarian_user, sample_game, app, tmp_path):
        from oneirodex.utils.game_mods import loader_conflicts

        app.config['GAME_MODS_PATH'] = str(tmp_path)
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'
        lib = client.post(base, json={'name': 'Lib', 'loader': 'bepinex'}).get_json()['mod']['id']
        dep = client.post(base, json={'name': 'Dependent', 'loader': 'bepinex', 'requires': [lib, 'ghost']}).get_json()['mod']
        assert dep['requires'] == [lib]  # unknown ids pruned
        odd = client.post(base, json={'name': 'Odd one', 'loader': 'melonloader'}).get_json()['mod']['id']

        client.patch(f'{base}/pack', json={'default_loader': 'bepinex'})
        listing = client.get(base).get_json()
        assert [c['id'] for c in listing['loader_conflicts']] == [odd]
        assert listing['loader_conflicts'][0]['default_loader'] == 'bepinex'
        assert loader_conflicts({'default_loader': 'none', 'mods': listing['mods']}) == []

        # Disabling the odd row clears the conflict; deleting Lib prunes the dependency
        client.patch(f'{base}/{odd}', json={'enabled': False})
        assert client.get(base).get_json()['loader_conflicts'] == []
        client.delete(f'{base}/{lib}')
        rows = {m['id']: m for m in client.get(base).get_json()['mods']}
        assert rows[dep['id']]['requires'] == []

    def test_catalog_marks_tracked_rows_and_newer_versions(self, client, librarian_user, sample_game, app, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import patch

        from oneirodex.utils.mod_catalog import modrinth

        app.config['GAME_MODS_PATH'] = str(tmp_path)
        monkeypatch.setenv('MOD_CATALOG_IN_TESTS', '1')
        sample_game.name = 'Minecraft'
        _login(client, librarian_user)
        base = f'/api/games/{sample_game.uuid}/mods'
        row = client.post(base, json={'name': 'Sodium', 'version': '1.20', 'source_url': 'https://modrinth.com/mod/sodium'}).get_json()['mod']
        payload = {'hits': [
            {'slug': 'sodium', 'title': 'Sodium', 'latest_version': '1.21.1', 'categories': ['fabric']},
            {'slug': 'lithium', 'title': 'Lithium', 'latest_version': '0.12', 'categories': ['fabric']},
        ]}
        with patch.object(modrinth, 'safe_request', return_value=SimpleNamespace(status_code=200, json=lambda: payload)):
            resp = client.get(f'{base}/catalog?source=modrinth')
        hits = {h['name']: h for h in resp.get_json()['hits']}
        assert hits['Sodium']['tracked_id'] == row['id'] and hits['Sodium']['update_available'] == '1.21.1'
        assert 'tracked_id' not in hits['Lithium']
        # Noting the update is an ordinary row write
        patched = client.patch(f'{base}/{row["id"]}', json={'version': '1.21.1', 'latest_seen_version': '1.21.1'}).get_json()['mod']
        assert patched['version'] == '1.21.1' and patched['latest_seen_version'] == '1.21.1'
