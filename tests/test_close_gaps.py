"""Tests for competitive gap wave: arr, calendar, quality, 7z, crypto, providers."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GlobalSettings, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.quality_profiles import score_release_title
from oneirodex.utils.rom_archive import ArchiveRomError, resolve_playable_rom_path
from oneirodex.utils.stats_share import build_playtime_share_svg, format_duration


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'adm_{uid[:8]}',
        email=f'adm_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_format_duration_and_svg():
    assert format_duration(3661) == '1h 1m'
    svg = build_playtime_share_svg(
        username='Ada',
        game_name='Celeste',
        total_seconds=7200,
        session_count=3,
    )
    assert 'Celeste' in svg
    assert '2h 0m' in svg


def test_quality_score_blocks_group(app, db_session):
    from sqlalchemy.orm.attributes import flag_modified
    from oneirodex.utils.quality_profiles import save_quality_profile

    # Ordered by id, like the product's own `_settings_row()`. A bare `limit(1)`
    # has no defined order in Postgres, so once the suite has left more than one
    # GlobalSettings row around, the test can configure one row while
    # quality_profiles reads another — which surfaced as a profile id that was
    # active but absent from the store it was looked up in.
    settings = db_session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()
    if not settings:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.quality_profiles = {
        'preferred_groups': ['FITGIRL'],
        'blocked_groups': ['DODI'],
        'prefer_repack': True,
        'min_size_mb': None,
        'max_size_mb': None,
    }
    flag_modified(settings, 'quality_profiles')
    db_session.commit()
    db_session.expire_all()
    with app.app_context():
        save_quality_profile({
            'preferred_groups': ['FITGIRL'],
            'blocked_groups': ['DODI'],
            'prefer_repack': True,
            'min_size_mb': None,
            'max_size_mb': None,
        })
        good = score_release_title('Game-FITGIRL')
        bad = score_release_title('Game-DODI')
    assert good['score'] >= 10
    assert bad['allowed'] is False


def test_arr_status_disabled(client, app, admin, db_session):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = False
    # Ordered by id, like the product's own `_settings_row()`. A bare `limit(1)`
    # has no defined order in Postgres, so once the suite has left more than one
    # GlobalSettings row around, the test can configure one row while
    # quality_profiles reads another — which surfaced as a profile id that was
    # active but absent from the store it was looked up in.
    settings = db_session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()
    if settings:
        settings.enable_arr_module = False
        db_session.commit()
    resp = client.get('/api/arr/status')
    assert resp.status_code == 200
    assert resp.get_json()['enabled'] is False


def test_arr_status_enabled(client, app, admin):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = True
    resp = client.get('/api/arr/status')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['enabled'] is True
    assert 'connectors' in body
    assert isinstance(body['hardlink_pipeline_enabled'], bool)
    assert isinstance(body['hardlink_helpers_enabled'], bool)
    assert isinstance(body['hardlink_apply_allowed'], bool)


def test_providers_list_includes_giantbomb(client, app, admin):
    _login(client, app, admin)
    resp = client.get('/api/providers')
    assert resp.status_code == 200
    ids = {p['id'] for p in resp.get_json()['providers']}
    assert 'giantbomb' in ids
    assert 'pcgamingwiki' in ids


def test_calendar_endpoint_without_igdb(client, app, admin, monkeypatch):
    _login(client, app, admin)

    def fake_fetch(**kwargs):
        return [{
            'igdb_id': 1,
            'name': 'Fake Upcoming',
            'slug': 'fake',
            'first_release_date': '2026-08-01',
            'cover_url': None,
            'rating': None,
            'window': 'upcoming',
        }]

    monkeypatch.setattr(
        'oneirodex.routes_apis.calendar.fetch_release_calendar',
        fake_fetch,
    )
    resp = client.get('/api/calendar')
    assert resp.status_code == 200
    assert resp.get_json()['count'] == 1


def test_playtime_share_svg(client, app, admin, db_session, tmp_path):
    lib = Library(name=f'ShareLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name='Share Game',
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g'),
    )
    db_session.add(game)
    db_session.commit()
    _login(client, app, admin)
    resp = client.get(f'/api/playtime/share/{game.uuid}.svg')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/svg+xml'
    assert b'Share Game' in resp.data


def test_resolve_7z_without_py7zr(tmp_path, monkeypatch):
    seven = tmp_path / 'game.7z'
    seven.write_bytes(b'not-real')

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'py7zr':
            raise ImportError('no py7zr')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive.find_archive_extractors',
        lambda: {},
    )
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(seven), cache_dir=str(tmp_path / 'c'))
    assert exc.value.status_code == 415
    assert exc.value.code == 'missing_extractor'
    assert '7z' in (exc.value.hint or '').lower() or 'p7zip' in (exc.value.hint or '').lower()


def test_encrypted_save_roundtrip(client, app, db_session, admin, tmp_path, monkeypatch):
    lib = Library(name=f'EncLib_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'EncGame_{uuid4().hex[:6]}',
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g.nes'),
    )
    db_session.add(game)
    db_session.commit()

    monkeypatch.setitem(app.config, 'EMULATOR_SAVES_PATH', str(tmp_path / 'saves'))
    monkeypatch.setitem(app.config, 'ENABLE_EMULATOR_SAVE_SYNC', True)
    monkeypatch.setitem(app.config, 'ENCRYPT_EMULATOR_SAVES', True)
    _login(client, app, admin)

    resp = client.post(
        f'/api/games/{game.uuid}/saves',
        data={'slot': 'slot1', 'file': (BytesIO(b'SECRETSAVE'), 's.state')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body.get('encrypted') is True

    downloaded = client.get(f'/api/games/{game.uuid}/saves/slot1')
    assert downloaded.status_code == 200
    assert downloaded.data == b'SECRETSAVE'
