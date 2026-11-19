"""Cross-surface regressions discovered while building the household workstation."""
import hashlib
from pathlib import Path

from oneirodex.utils.archive_range import archive_identity, resolve_range
from oneirodex.utils.duplicate_check import edition_conflict
from oneirodex.utils.play_readiness import browser_readiness


def test_resume_keeps_identity_and_handles_a_changed_archive(tmp_path):
    file = tmp_path / 'game.zip'
    payload = b'PK' + bytes(range(100))
    file.write_bytes(payload)
    with file.open('rb') as stream:
        etag, size = archive_identity(stream)
        assert etag == '"sha256-' + hashlib.sha256(payload).hexdigest() + '"'
        assert stream.tell() == 0
        assert resolve_range(size, 'bytes=12-', etag, etag) == (206, 12, size - 12)
        assert resolve_range(size, 'bytes=12-', '"old"', etag) == (200, 0, size)
        assert resolve_range(size, 'bytes=999-', etag, etag) == (416, 0, 0)


def test_distinct_media_are_kept_separate():
    assert edition_conflict('Orbit (Disc 1)', 'Orbit (Disc 2)') == 'disc'
    assert edition_conflict('Orbit (Rev A)', 'Orbit (Rev B)') == 'revision'
    assert edition_conflict('Orbit Remastered', 'Orbit') == 'presentation'
    assert edition_conflict('Orbit Remaster', 'Orbit Remastered') is None


def test_readiness_distinguishes_a_launch_route_and_missing_firmware():
    ready = {'can_play_in_browser': True, 'play_url': '/player', 'emulator_core': 'mgba'}
    assert browser_readiness(ready)['available']
    assert browser_readiness({**ready, 'firmware_missing': True})['reason'] == 'missing_firmware'
    assert browser_readiness({'play_blocker': 'missing_game_file'})['available'] is False


def test_all_portraits_have_small_square_assets():
    from PIL import Image
    from oneirodex.utils.avatar import STOCK_AVATARS
    for pick in [p for p in STOCK_AVATARS if p['path'].endswith('.webp')]:
        asset = Path(__file__).resolve().parents[1] / 'oneirodex/static' / pick['path']
        with Image.open(asset) as image:
            assert image.size == (384, 384)
        assert asset.stat().st_size < 65000


def test_composition_is_reproducible_and_changes_the_image():
    from oneirodex.utils.cover_art_studio import render_cover_art
    def draw(direction):
        return render_cover_art(180, 240, title='Cascade7', composition=direction).tobytes()
    assert draw('workbench') == draw('workbench')
    assert draw('workbench') != draw('marquee')


def test_match_review_survives_reimport_and_keeps_other_libraries_separate(client, db_session, tmp_path):
    from uuid import uuid4
    from oneirodex.models import Game, Library, UnmatchedFolder, User
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.scanning import log_unmatched_folder
    actor = User(user_id=str(uuid4()), name='Review-'+uuid4().hex[:8], email=uuid4().hex+'@test.invalid', role='admin', is_email_verified=True)
    actor.set_password('fixture-only-test-password')
    a, b = [Library(name=uuid4().hex, platform=LibraryPlatform.PCWIN) for _ in range(2)]
    db_session.add_all([actor, a, b])
    db_session.flush()
    path = str(tmp_path / 'Orbit')
    row = UnmatchedFolder(folder_path=path, library_uuid=a.uuid, status='Unmatched')
    local = Game(uuid=str(uuid4()), library_uuid=a.uuid, name='Orbit', full_disk_path=path)
    distant = Game(uuid=str(uuid4()), library_uuid=b.uuid, name='Orbit', full_disk_path=path+'-other')
    db_session.add_all([row, local, distant])
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(actor.id)
        session['_fresh'] = True
    assert client.post(f'/api/unmatched/{row.id}/review', json={'note': 'a' * 66000}).status_code == 413
    def post(row_id, revision, action='accept', candidate=None):
        return client.post(f'/api/unmatched/{row_id}/review', json={'action': action, 'candidate': candidate, 'note': 'Checked source edition', 'revision': revision})
    options = client.get(f'/api/unmatched/{row.id}/candidates?q=Orbit')
    assert options.status_code == 200, options.get_json()
    assert [g['uuid'] for g in options.get_json()['items']] == [local.uuid]
    assert post(row.id, 0, candidate=distant.uuid).status_code == 404
    chosen = post(row.id, 0, candidate=local.uuid)
    assert chosen.status_code == 200, chosen.get_json()
    assert chosen.get_json()['current']['candidate'] == local.uuid
    assert post(row.id, 0, 'reject').status_code == 409
    db_session.delete(row)
    db_session.commit()
    log_unmatched_folder(None, path, 'Unmatched', a.uuid)
    log_unmatched_folder(None, path, 'Unmatched', b.uuid)
    from sqlalchemy import select
    def current(lib):
        return db_session.execute(select(UnmatchedFolder).filter_by(library_uuid=lib.uuid, folder_path=path)).scalar_one()
    restored = current(a)
    assert restored.review_decision['current']['candidate'] == local.uuid
    assert not current(b).review_decision
    assert post(restored.id, 1, 'reject').get_json()['revision'] == 2
    assert post(restored.id, 2, 'undo').get_json()['current']['candidate'] == local.uuid
    assert post(restored.id, 3, 'undo').get_json()['current'] is None
    assert db_session.get(Game, local.id).name == 'Orbit'


def test_cached_pack_reuses_recipe_and_checks_completeness(tmp_path, monkeypatch):
    from oneirodex.utils import cover_art_studio as studio
    sizes = list(studio.SIZE_MATRIX)
    files = {studio._filename_for(prefix, w, h, 'webp'): b'demo' for prefix, w, h in sizes}
    calls = []
    def render(*args, **kwargs):
        calls.append(kwargs['composition'])
        return files
    monkeypatch.setattr(studio, 'generate_size_matrix', render)
    first = studio.save_pack('Fixture', package_root=tmp_path, composition='workbench')
    second = studio.save_pack('Fixture', package_root=tmp_path, composition='workbench')
    assert first == second and calls == ['workbench']
    other = studio.save_pack('Fixture', package_root=tmp_path, composition='crt')
    assert first['pack_id'] != other['pack_id']
    directory = studio.safe_pack_dir(first['pack_id'], tmp_path)
    (directory / first['files'][0]).unlink()
    import pytest
    with pytest.raises(ValueError, match='incomplete'):
        studio.save_pack('Fixture', package_root=tmp_path, composition='workbench')


def test_catalog_search_folds_accents_and_treats_wildcards_as_text(db_session):
    from uuid import uuid4
    from sqlalchemy import select
    from oneirodex.models import Game, Library
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.browse_filters import apply_name_filter
    library = Library(name=uuid4().hex, platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    titles = ['Café Orbit', 'Orbit Café 2', '100% Orbit', '100X Orbit', 'Orbit_A', 'OrbitXA', '夜の軌道']
    for title in titles:
        db_session.add(Game(name=title, library_uuid=library.uuid, full_disk_path='/fixture/' + title))
    db_session.flush()

    def results(query):
        scoped = select(Game.name).where(Game.library_uuid == library.uuid)
        return set(db_session.scalars(apply_name_filter(scoped, {'q': query})))

    assert results('orbit cafe') == {'Café Orbit', 'Orbit Café 2'}
    assert results('100%') == {'100% Orbit'}
    assert results('_') == {'Orbit_A'}
    assert results('夜の軌道') == {'夜の軌道'}


def test_firmware_choices_keep_legacy_identifiers(tmp_path):
    from oneirodex.utils.bios_install import _resolve_choice, firmware_digest
    file = tmp_path / 'bios.bin'
    file.write_bytes(b'firmware fixture')
    modern = hashlib.sha256(file.read_bytes()).hexdigest()
    legacy = hashlib.sha1(file.read_bytes(), usedforsecurity=False).hexdigest()
    assert firmware_digest(str(file), str(tmp_path)) == modern
    for value in [modern, legacy]:
        assert _resolve_choice([str(file)], str(tmp_path), value) == str(file)


def test_imported_mod_order_and_dependencies_follow_local_identifiers(tmp_path):
    import base64
    import json
    import pytest
    from oneirodex.utils.game_mods import mod_config_scope, save_mods
    from oneirodex.utils.game_mod_profiles import ProfileConflict, activate_profile, export_profile, import_profile
    from uuid import uuid4

    game = str(uuid4())
    recipe = {'v': 1, 'name': 'Co-op', 'mods': [
        {'id': 'old-main', 'name': 'Game', 'source_url': 'https://example.org/game', 'load_order': 90, 'requires': ['old-lib']},
        {'id': 'old-lib', 'name': 'Lib', 'source_url': 'https://example.org/lib', 'load_order': 5, 'requires': []},
    ]}
    code = 'od-mod:' + base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode()
    rows = [
        {'id': 'main', 'name': 'Game', 'source_url': 'https://example.org/game', 'load_order': 0, 'requires': ['lib']},
        {'id': 'lib', 'name': 'Lib', 'source_url': 'https://example.org/lib', 'load_order': 1},
    ]
    with mod_config_scope({'GAME_MODS_PATH': str(tmp_path)}):
        save_mods(game, rows)
        profile = import_profile(game, code)['profile']
        assert profile['import_order'] == ['lib', 'main']
        with pytest.raises(ProfileConflict, match='load order'):
            activate_profile(game, profile['id'])
        rows[0]['load_order'] = 3
        save_mods(game, rows)
        assert activate_profile(game, profile['id'])['active_profile'] == profile['id']
        assert export_profile(game, profile['id']).startswith('od-mod:')
        rows[0]['requires'] = []
        save_mods(game, rows)
        with pytest.raises(ProfileConflict, match='dependencies'):
            export_profile(game, profile['id'])
