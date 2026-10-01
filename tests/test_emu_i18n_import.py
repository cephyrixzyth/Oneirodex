"""Tests for ROM archives, emulator saves, i18n locale, Playnite import."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User, UserOwnedTitle
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.i18n import normalize_locale
from oneirodex.utils.playnite_import import import_playnite_json
from oneirodex.utils.rom_archive import ArchiveRomError, resolve_playable_rom_path


@pytest.fixture
def member(db_session):
    uid = str(uuid4())
    row = User(
        name=f'mem_{uid[:8]}',
        email=f'mem_{uid[:8]}@example.com',
        role='user',
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


def test_normalize_locale():
    assert normalize_locale('es') == 'es'
    assert normalize_locale('es-MX') == 'es'
    assert normalize_locale('fr') == 'en'


def test_resolve_zip_rom(tmp_path):
    zip_path = tmp_path / 'game.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('nested/Adventure.nes', b'NESROMDATA')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(zip_path), cache_dir=str(cache))
    assert name == 'Adventure.nes'
    assert Path(path).is_file()
    assert Path(path).read_bytes() == b'NESROMDATA'


def test_resolve_rejects_7z(tmp_path):
    seven = tmp_path / 'game.7z'
    seven.write_bytes(b'not-a-real-archive')
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(seven), cache_dir=str(tmp_path / 'c'))
    # Corrupt archives → 400; missing py7zr → 415
    assert exc.value.status_code in (400, 415)


def test_resolve_rejects_rar(tmp_path):
    rar = tmp_path / 'game.rar'
    rar.write_bytes(b'not-a-real-archive')
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(rar), cache_dir=str(tmp_path / 'c'))
    # Missing rarfile/unrar tool or invalid archive → 415
    assert exc.value.status_code == 415


def test_emulator_save_roundtrip(client, app, db_session, member, tmp_path, monkeypatch):
    lib = Library(name=f'SaveLib_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'SaveGame_{uuid4().hex[:6]}',
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g.nes'),
    )
    db_session.add(game)
    db_session.commit()

    monkeypatch.setitem(app.config, 'EMULATOR_SAVES_PATH', str(tmp_path / 'saves'))
    monkeypatch.setitem(app.config, 'ENABLE_EMULATOR_SAVE_SYNC', True)
    _login(client, app, member)

    data = {
        'slot': 'slot1',
        'file': (io.BytesIO(b'SAVEDATA'), 'slot1.state'),
    }
    resp = client.post(
        f'/api/games/{game.uuid}/saves',
        data=data,
        content_type='multipart/form-data',
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body['slot_name'] == 'slot1'
    assert body['size_bytes'] == 8

    listed = client.get(f'/api/games/{game.uuid}/saves')
    assert listed.status_code == 200
    assert len(listed.get_json()['saves']) == 1

    downloaded = client.get(f'/api/games/{game.uuid}/saves/slot1')
    assert downloaded.status_code == 200
    assert downloaded.data == b'SAVEDATA'

    deleted = client.delete(f'/api/games/{game.uuid}/saves/slot1')
    assert deleted.status_code == 200


def test_locale_api(client, app, db_session, member):
    _login(client, app, member)
    resp = client.post('/api/locale', json={'locale': 'es'})
    assert resp.status_code == 200
    assert resp.get_json()['locale'] == 'es'
    get_resp = client.get('/api/locale')
    assert get_resp.get_json()['locale'] == 'es'


def test_playnite_import_matches(app, db_session, member):
    unique = f'Celeste Import Target {uuid4().hex[:8]}'
    lib = Library(name=f'PLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=unique,
        library_uuid=lib.uuid,
        full_disk_path='',
    )
    db_session.add(game)
    db_session.commit()

    with app.app_context():
        result = import_playnite_json(
            member.id,
            [{'Name': unique, 'Id': f'abc-{uuid4().hex[:8]}'}],
        )
        assert result.imported == 1
        assert result.matched == 0
        row = db_session.query(UserOwnedTitle).filter_by(
            user_id=member.id,
            store='playnite',
            name=unique,
        ).first()
        assert row is not None
        assert row.matched_game_uuid is None
