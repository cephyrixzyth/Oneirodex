"""Tests for cover art studio (ART-1/2) — no database required for render paths."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from PIL import Image

from oneirodex.models import Game, Image as GameImage, Library, LibraryPlatform, User
from oneirodex.utils.cover_art_studio import (
    bake_default_fallbacks,
    build_zip_bytes,
    generate_size_matrix,
    render_cover_art,
    safe_pack_dir,
    safe_pack_file,
    save_pack,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- PIL cover-art rendering matrix.


def test_era_room_scenery_is_distinct():
    """Backup art for a wood den must not look like an arcade floor."""
    den = render_cover_art(200, 300, title='Demo', era='wood_den_80s')
    arcade = render_cover_art(200, 300, title='Demo', era='arcade_cabinet')
    bedroom = render_cover_art(200, 300, title='Demo', era='teen_bedroom_90s')
    assert den.tobytes() != arcade.tobytes()
    assert den.tobytes() != bedroom.tobytes()
    assert arcade.tobytes() != bedroom.tobytes()


def test_render_cover_art_returns_valid_image():
    img = render_cover_art(400, 600, title='Test Game', system='SNES')
    assert img.size == (400, 600)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    assert len(buf.getvalue()) > 500


def test_system_templates_differ_by_platform_pixels():
    """At least three platforms produce distinct palettes / pixels at tile size."""
    from oneirodex.utils.cover_art_studio import resolve_system_template

    nes = resolve_system_template('NES')
    snes = resolve_system_template('SNES')
    ps1 = resolve_system_template('PS1')
    assert nes != snes != ps1
    assert nes[2] != snes[2]  # accents differ

    img_nes = render_cover_art(200, 300, title='Demo', system='NES')
    img_snes = render_cover_art(200, 300, title='Demo', system='SNES')
    img_ps1 = render_cover_art(200, 300, title='Demo', system='PS1')
    assert img_nes.tobytes() != img_snes.tobytes()
    assert img_snes.tobytes() != img_ps1.tobytes()
    assert img_nes.tobytes() != img_ps1.tobytes()


def test_tile_title_readable_min_font_at_200x300():
    """200×300 tiles must use at least 14px title sizing path (no tiny default font)."""
    img = render_cover_art(200, 300, title='Readable Title', system='GBA')
    assert img.size == (200, 300)
    # Non-flat image (gradient + text + glyph) — enough entropy for a real render
    extrema = img.getextrema()
    assert any(lo != hi for lo, hi in extrema)


def test_title_driven_art_differs_from_empty_and_other_titles():
    """Titled artistic covers must not match empty-title or a different title."""
    empty = render_cover_art(400, 600, title='', system='NES', artistic=True)
    titled_a = render_cover_art(400, 600, title='Chrono Trigger', system='NES', artistic=True)
    titled_b = render_cover_art(400, 600, title='Super Metroid', system='NES', artistic=True)
    assert empty.tobytes() != titled_a.tobytes()
    assert titled_a.tobytes() != titled_b.tobytes()
    assert empty.size == titled_a.size == (400, 600)


def test_unicode_title_does_not_crash():
    img = render_cover_art(400, 600, title='ゼルダの伝説 風のタクト', system='NGC', artistic=True)
    assert img.size == (400, 600)
    img2 = render_cover_art(256, 256, title='Игротека — тест', variant='square')
    assert img2.size == (256, 256)


def test_variants_known_sizes_are_designed_not_crash():
    cases = [
        ('tile', 200, 300),
        ('tile', 400, 600),
        ('wide', 960, 540),
        ('square', 256, 256),
        ('hero', 1280, 720),
    ]
    for variant, w, h in cases:
        img = render_cover_art(w, h, title='Variant Probe', system='PS1', variant=variant)
        assert img.size == (w, h)
        extrema = img.getextrema()
        assert any(lo != hi for lo, hi in extrema)


def test_artistic_false_still_renders():
    img = render_cover_art(200, 300, title='Legacy Flat', system='GBA', artistic=False)
    assert img.size == (200, 300)


def test_generate_size_matrix_has_all_outlets():
    files = generate_size_matrix('Demo Title', system='NES')
    assert 'tile_200x300.webp' in files
    assert 'wide_1920x1080.webp' in files
    assert 'square_512.webp' in files
    assert 'hero_1280x720.webp' in files
    assert len(files) == 10


def test_safe_pack_dir_blocks_traversal(tmp_path):
    root = tmp_path / 'generated'
    root.mkdir()
    with patch('oneirodex.utils.cover_art_studio.generated_root', return_value=root):
        assert safe_pack_dir('valid-pack_1') == root / 'valid-pack_1'
        with pytest.raises(ValueError):
            safe_pack_dir('../etc')
        with pytest.raises(ValueError):
            safe_pack_dir('bad/id')


def test_safe_pack_file_only_known_names(tmp_path, app):
    """Needs an app context: these helpers resolve paths from
    `current_app.root_path`, so patching `generated_root` alone is no longer
    enough to keep them off Flask's globals."""
    pack = tmp_path / 'pack1'
    pack.mkdir()
    (pack / 'tile_400x600.webp').write_bytes(b'x')
    with app.app_context():
        with patch('oneirodex.utils.cover_art_studio.generated_root', return_value=tmp_path):
            path = safe_pack_file('pack1', 'tile_400x600.webp')
            assert path.is_file()
            with pytest.raises(ValueError):
                safe_pack_file('pack1', '../../../etc/passwd')


def test_save_pack_and_zip(tmp_path, app):
    with app.app_context(),          patch('oneirodex.utils.cover_art_studio.generated_root', return_value=tmp_path):
        manifest = save_pack('Zip Test', system='GBA', pack_id='testpack01')
        assert manifest['pack_id'] == 'testpack01'
        assert (tmp_path / 'testpack01' / 'manifest.json').is_file()
        payload = build_zip_bytes('testpack01')
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        assert any('tile_600x900.webp' in n for n in names)


def test_bake_default_fallbacks(tmp_path):
    ns = tmp_path / 'newstyle'
    with patch('oneirodex.utils.cover_art_studio.newstyle_root', return_value=ns):
        paths = bake_default_fallbacks()
    assert Path(paths['default_cover']).is_file()
    assert Path(paths['default_library']).is_file()
    assert Path(paths['default_library_large']).is_file()
    cover = Image.open(paths['default_cover'])
    assert cover.size == (600, 900)
    # Branded blank is not a flat single-color box
    extrema = cover.getextrema()
    assert any(lo != hi for lo, hi in extrema)


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    suffix = uid[:8]
    user = User(
        user_id=uid,
        name=f'ArtAdmin_{suffix}',
        email=f'artadmin_{suffix}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_art_studio_api_requires_admin(client, db_session, admin_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    ok = client.post(
        '/admin/api/art-studio/preview',
        json={'title': 'Preview Me'},
    )
    assert ok.status_code == 200
    assert 'preview' in ok.get_json()

    bad = client.post('/admin/api/art-studio/preview', json={'title': ''})
    assert bad.status_code == 422


def test_art_studio_generate_surfaces_permission_error(client, db_session, admin_user):
    """A disk write failure (e.g. read-only IMAGE_SAVE_PATH) must return a JSON
    error instead of a bare 500 HTML page, so the admin UI can show it."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch(
        'oneirodex.routes_admin_ext.art_studio.save_pack',
        side_effect=PermissionError('Permission denied'),
    ):
        response = client.post(
            '/admin/api/art-studio/generate',
            json={'title': 'Broken Perms'},
        )
        assert response.status_code == 500
        data = response.get_json()
        assert 'error' in data
        assert 'Permission denied' in data['error']


def test_art_studio_apply_fallback_surfaces_disk_error(client, db_session, admin_user):
    """apply mode=fallback should surface OSError/PermissionError as JSON, not crash."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch(
        'oneirodex.routes_admin_ext.art_studio.apply_pack_as_fallback',
        side_effect=OSError('Disk full'),
    ):
        response = client.post(
            '/admin/api/art-studio/apply',
            json={'pack_id': 'some-pack', 'mode': 'fallback'},
        )
        assert response.status_code == 500
        data = response.get_json()
        assert 'error' in data
        assert data['error'] == 'Failed to write cover art to disk'


def test_art_studio_download_surfaces_disk_error(client, db_session, admin_user):
    """download should surface OSError as JSON rather than an unhandled 500."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch('oneirodex.routes_admin_ext.art_studio.safe_pack_dir', return_value=Path('/fake')):
        with patch(
            'oneirodex.routes_admin_ext.art_studio.build_zip_bytes',
            side_effect=PermissionError('Permission denied'),
        ):
            response = client.get('/admin/api/art-studio/download/some-pack')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Permission denied' in data['error']


def test_apply_pack_to_game_rolls_back_and_removes_file_on_db_failure(tmp_path, db_session):
    """If the DB commit fails after the cover file is written, the orphaned
    file must be cleaned up and the original exception re-raised."""
    from oneirodex.utils.cover_art_studio import apply_pack_to_game, save_pack

    game_uuid = str(uuid4())
    library = Library(name=f'ArtLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    game = Game(uuid=game_uuid, name='Rollback Target', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()

    gen_root = tmp_path / 'generated'
    img_root = tmp_path / 'images'
    img_root.mkdir()

    with patch('oneirodex.utils.cover_art_studio.generated_root', return_value=gen_root):
        manifest = save_pack('Rollback Test', pack_id='rollbackpack01')

        with patch('oneirodex.utils.cover_art_studio.db.session.commit', side_effect=RuntimeError('db down')):
            with pytest.raises(RuntimeError, match='db down'):
                apply_pack_to_game(
                    manifest['pack_id'], game_uuid, image_save_path=img_root,
                )

    # The written cover file should have been cleaned up after the rollback.
    assert list(img_root.glob(f'{game_uuid}_cover_studio_*')) == []


def test_art_studio_generate_apply_game(client, db_session, admin_user, app, tmp_path):
    game_uuid = str(uuid4())
    library = Library(name=f'ArtLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    game = Game(uuid=game_uuid, name='Art Target', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()

    gen_root = tmp_path / 'generated'
    img_root = tmp_path / 'images'
    img_root.mkdir()
    app.config['IMAGE_SAVE_PATH'] = str(img_root)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch('oneirodex.utils.cover_art_studio.generated_root', return_value=gen_root):
        gen = client.post(
            '/admin/api/art-studio/generate',
            json={'title': 'Apply Test', 'system': 'PS1'},
        )
        assert gen.status_code == 201
        pack_id = gen.get_json()['pack_id']

        apply_resp = client.post(
            '/admin/api/art-studio/apply',
            json={'pack_id': pack_id, 'mode': 'game', 'game_uuid': game_uuid},
        )
        assert apply_resp.status_code == 200
        data = apply_resp.get_json()
        assert data['game_uuid'] == game_uuid
        assert '/static/library/images/' in data['cover_url']

    row = db_session.execute(
        __import__('sqlalchemy').select(GameImage).filter_by(game_uuid=game_uuid, image_type='cover')
    ).scalars().first()
    assert row is not None
    assert row.is_downloaded is True


def test_generated_pack_honours_the_text_overrides(tmp_path, app):
    """Generate must render what the preview showed.

    The renderer has accepted `headline_override` / `subtitle_override` /
    `title_scale` since the artwork wave, and only the *preview* route passed
    them through — so exposing the controls without threading them into
    save_pack would have produced a preview that lied about its own output.
    """
    with app.app_context(), patch(
        'oneirodex.utils.cover_art_studio.generated_root', return_value=tmp_path
    ):
        plain = save_pack('Override Test', system='SNES', pack_id='ovr_plain')
        scaled = save_pack(
            'Override Test', system='SNES', pack_id='ovr_scaled',
            headline_override='CUSTOM',
            title_scale=1.8,
        )

    assert plain['files'] == scaled['files']

    name = plain['files'][0]
    plain_bytes = (tmp_path / 'ovr_plain' / name).read_bytes()
    scaled_bytes = (tmp_path / 'ovr_scaled' / name).read_bytes()
    assert plain_bytes != scaled_bytes, 'overrides did not reach the rendered pack'


def test_generate_route_forwards_the_overrides(client, db_session, admin_user):
    """The route is the half that was missing; pin the forwarding itself so a
    future refactor cannot quietly drop it and leave the UI writing defaults."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch('oneirodex.routes_admin_ext.art_studio.save_pack') as fake:
        fake.return_value = {'pack_id': 'p1', 'files': [], 'title': 'T', 'system': '', 'format': 'webp'}
        client.post(
            '/admin/api/art-studio/generate',
            json={'title': 'T', 'headline': 'BIG', 'subtitle': '', 'title_scale': 1.5},
        )

    kwargs = fake.call_args.kwargs
    assert kwargs['headline_override'] == 'BIG'
    assert kwargs['subtitle_override'] == ''
    assert kwargs['title_scale'] == 1.5
