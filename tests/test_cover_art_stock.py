"""Tests for Art Studio stock / platform image packs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from oneirodex.utils.cover_art_stock import (
    ERA_STOCK_PACKS,
    MAJOR_PLATFORM_PACKS,
    STOCK_MOTIFS,
    apply_pack_to_library,
    generate_stock_packs,
    list_stock_catalog,
    save_stock_pack,
)


def test_stock_catalog_non_empty_and_has_platforms(tmp_path):
    stock = tmp_path / 'stock'
    stock.mkdir()
    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            items = list_stock_catalog(package_root=tmp_path)

    assert len(items) >= 20
    kinds = {i['kind'] for i in items}
    assert 'platform' in kinds
    assert 'stock' in kinds
    platform_ids = {i['id'] for i in items if i['kind'] == 'platform'}
    assert 'platform-nes' in platform_ids
    assert 'platform-snes' in platform_ids
    assert 'platform-psx' in platform_ids
    assert 'platform-pcwin' in platform_ids
    stock_ids = {i['id'] for i in items if i['kind'] == 'stock'}
    assert 'stock-controller' in stock_ids
    assert 'stock-crt-grid' in stock_ids
    era_ids = {i['id'] for i in items if i['kind'] == 'era'}
    assert 'era-80s-den' in era_ids
    assert 'era-90s-bedroom' in era_ids
    assert len(era_ids) >= 6
    assert len(STOCK_MOTIFS) >= 8
    assert len(MAJOR_PLATFORM_PACKS) >= 8
    assert len(ERA_STOCK_PACKS) >= 6
    for item in items:
        assert item['pack_id']
        assert item['label']
        assert 'tile' in item['urls']
        assert 'wide' in item['urls']
        assert item['path'].startswith('library/stock/')
        assert '/static/library/stock/' in item['urls']['tile']


def test_generate_stock_pack_writes_files(tmp_path):
    stock = tmp_path / 'stock'
    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            manifest = save_stock_pack('stock-controller', package_root=tmp_path)
            assert manifest['pack_id'] == 'stock-controller'
            pack_dir = stock / 'stock-controller'
            assert (pack_dir / 'tile_400x600.webp').is_file()
            assert (pack_dir / 'wide_960x540.webp').is_file()
            assert (pack_dir / 'hero_1280x720.webp').is_file()
            assert (pack_dir / 'manifest.json').is_file()

            again = save_stock_pack('platform-nes', package_root=tmp_path)
            assert again['kind'] == 'platform'
            assert (stock / 'platform-nes' / 'tile_200x300.webp').is_file()

            era = save_stock_pack('era-80s-den', package_root=tmp_path)
            assert era['kind'] == 'era'
            assert era['era'] == 'wood_den_80s'
            assert (stock / 'era-80s-den' / 'tile_400x600.webp').is_file()


def test_generate_stock_packs_batch(tmp_path):
    stock = tmp_path / 'stock'
    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            result = generate_stock_packs(
                ['stock-disc-ring', 'platform-gba'],
                package_root=tmp_path,
            )
    assert result['count'] == 2
    assert (stock / 'stock-disc-ring' / 'tile_400x600.webp').is_file()
    assert (stock / 'platform-gba' / 'wide_1920x1080.webp').is_file()


def test_apply_pack_updates_library_image_url(tmp_path):
    stock = tmp_path / 'stock'
    lib_uuid = str(uuid4())
    library = MagicMock()
    library.uuid = lib_uuid
    library.image_url = None

    execute_result = MagicMock()
    execute_result.scalars.return_value.first.return_value = library

    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            save_stock_pack('platform-nes', package_root=tmp_path)
            with patch('oneirodex.utils.cover_art_stock.db') as mock_db:
                mock_db.session.execute.return_value = execute_result
                with patch(
                    'oneirodex.utils.cover_art_stock.static_asset_url',
                    side_effect=lambda path: f'/static/{path}',
                ):
                    result = apply_pack_to_library(
                        'platform-nes', lib_uuid, package_root=tmp_path,
                    )

    assert result['library_uuid'] == lib_uuid
    assert result['pack_id'] == 'platform-nes'
    assert '/static/library/stock/platform-nes/' in result['image_url']
    assert library.image_url == result['image_url']
    mock_db.session.commit.assert_called_once()


@pytest.fixture
def admin_user(db_session):
    from oneirodex.models import User

    uid = str(uuid4())
    suffix = uid[:8]
    user = User(
        user_id=uid,
        name=f'StockAdmin_{suffix}',
        email=f'stockadmin_{suffix}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_art_studio_stock_api_catalog_and_generate(client, db_session, admin_user, tmp_path):
    stock = tmp_path / 'stock'
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            catalog = client.get('/admin/api/art-studio/stock')
            assert catalog.status_code == 200
            body = catalog.get_json()
            assert body['count'] >= 20
            assert any(i['id'] == 'platform-nes' for i in body['items'])
            assert any(i['kind'] == 'stock' for i in body['items'])

            gen = client.post(
                '/admin/api/art-studio/stock/generate',
                json={'ids': ['stock-vault-mark', 'platform-pcwin']},
            )
            assert gen.status_code == 201
            data = gen.get_json()
            assert data['count'] == 2
            assert (stock / 'stock-vault-mark' / 'tile_400x600.webp').is_file()
            assert (stock / 'platform-pcwin' / 'hero_1280x720.webp').is_file()


def test_art_studio_apply_library_mode(client, db_session, admin_user, tmp_path):
    from oneirodex.models import Library, LibraryPlatform

    stock = tmp_path / 'stock'
    library = Library(name=f'ApplyLib_{uuid4().hex[:6]}', platform=LibraryPlatform.SNES)
    db_session.add(library)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch('oneirodex.utils.cover_art_stock.stock_root', return_value=stock):
        with patch('oneirodex.utils.cover_art_studio.stock_root', return_value=stock):
            save_stock_pack('stock-neon-court', package_root=tmp_path)
            resp = client.post(
                '/admin/api/art-studio/apply',
                json={
                    'pack_id': 'stock-neon-court',
                    'mode': 'library',
                    'library_uuid': library.uuid,
                },
            )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['mode'] == 'library'
    assert 'stock-neon-court' in data['image_url']
    db_session.refresh(library)
    assert library.image_url == data['image_url']
