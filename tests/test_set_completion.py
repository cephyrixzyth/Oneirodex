"""ROM set completeness — DAT parse, normalize, APIs."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from flask_login import login_user
from werkzeug.datastructures import FileStorage

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.set_completion import (
    compute_set_completion,
    normalize_set_title,
    parse_dat_bytes,
    upsert_reference_set,
)


def _tiny_dat(tag: str) -> bytes:
    """Synthetic DAT with unique titles so shared test DBs do not collide."""
    return f"""<?xml version="1.0"?>
<datafile>
  <header>
    <name>Nintendo - Nintendo Entertainment System (USA) {tag}</name>
    <description>Test NES USA {tag}</description>
  </header>
  <game name="Adventure Island {tag} (USA)">
    <description>Adventure Island {tag} (USA)</description>
    <rom name="Adventure Island {tag} (USA).nes" size="65536" crc="ABCDEF01" md5="d41d8cd98f00b204e9800998ecf8427e" sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709"/>
  </game>
  <game name="Balloon Fight {tag} (USA)">
    <description>Balloon Fight {tag} (USA)</description>
    <rom name="Balloon Fight {tag} (USA).nes" size="24576" crc="11111111"/>
  </game>
  <game name="Castlevania {tag} (USA) (Rev A)">
    <description>Castlevania {tag} (USA) (Rev A)</description>
    <rom name="Castlevania {tag} (USA) (Rev A).nes" size="131072" crc="22222222"/>
  </game>
</datafile>
""".encode('utf-8')


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    user = User(
        name=f'set_admin_{uid[:8]}',
        email=f'set_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member(db_session):
    uid = str(uuid4())
    user = User(
        name=f'set_user_{uid[:8]}',
        email=f'set_user_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def nes_lib(db_session):
    library = Library(name=f'NES_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add(library)
    db_session.commit()
    return library


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_normalize_strips_region_and_rev():
    assert normalize_set_title('Adventure Island (USA)') == 'adventure island'
    assert normalize_set_title('Castlevania (USA) (Rev A)') == 'castlevania'
    assert normalize_set_title('Balloon Fight (USA) [!].nes') == 'balloon fight'


def test_parse_tiny_xml_dat():
    tag = uuid4().hex[:8]
    header, entries = parse_dat_bytes(_tiny_dat(tag))
    assert 'Nintendo Entertainment System' in header
    assert len(entries) == 3
    names = {e['normalized_name'] for e in entries}
    assert names == {
        f'adventure island {tag}',
        f'balloon fight {tag}',
        f'castlevania {tag}',
    }
    adv = next(e for e in entries if e['normalized_name'] == f'adventure island {tag}')
    assert adv['crc'] == 'abcdef01'


def test_parse_clrmame_dat():
    text = """
clrmamepro (
	name "Test Set"
	description "Test"
)
game (
	name "Foo (USA)"
	description "Foo (USA)"
	rom ( name "Foo (USA).nes" size 123 crc AABBCCDD )
)
game (
	name "Bar (Europe)"
	rom ( name "Bar (Europe).nes" size 456 crc 01020304 )
)
"""
    header, entries = parse_dat_bytes(text)
    assert header == 'Test Set'
    assert len(entries) == 2
    assert {e['normalized_name'] for e in entries} == {'foo', 'bar'}


def test_owned_missing_diff(app, db_session, admin, nes_lib, member):
    tag = uuid4().hex[:8]
    with app.app_context():
        upsert_reference_set(
            library_platform='NES',
            region='USA',
            source='nointro',
            dat_bytes=_tiny_dat(tag),
            uploader_id=admin.id,
        )
        db_session.add(
            Game(
                uuid=str(uuid4()),
                name=f'Adventure Island {tag}',
                library_uuid=nes_lib.uuid,
                full_disk_path=rf'C:\roms\Adventure Island {tag} (USA).nes',
            )
        )
        db_session.add(
            Game(
                uuid=str(uuid4()),
                name='Unrelated Title',
                library_uuid=nes_lib.uuid,
            )
        )
        db_session.commit()

        report = compute_set_completion(
            library_platform='NES',
            region='USA',
            user=member,
            include_matched=True,
        )
        assert report is not None
        assert report['total'] == 3
        assert report['owned'] == 1
        assert report['missing_count'] == 2
        missing_names = {m['normalized_name'] for m in report['missing']}
        assert f'balloon fight {tag}' in missing_names
        assert f'castlevania {tag}' in missing_names
        assert report['matched'][0]['normalized_name'] == f'adventure island {tag}'


def test_api_upload_and_completion(app, client, db_session, admin, nes_lib, member):
    tag = uuid4().hex[:8]
    with client:
        _login(client, app, admin)
        upload = FileStorage(
            stream=BytesIO(_tiny_dat(tag)),
            filename='nes-usa.dat',
            content_type='application/xml',
        )
        res = client.post(
            '/api/reference-sets',
            data={
                'library_platform': 'NES',
                'region': 'USA',
                'source': 'nointro',
                'file': upload,
            },
            content_type='multipart/form-data',
        )
        assert res.status_code == 201, res.get_data(as_text=True)
        body = res.get_json()
        assert body['library_platform'] == 'NES'
        assert body['region'] == 'USA'
        assert body['entry_count'] == 3

    db_session.add(
        Game(
            uuid=str(uuid4()),
            name=f'Balloon Fight {tag} (USA)',
            library_uuid=nes_lib.uuid,
        )
    )
    db_session.commit()

    with client:
        _login(client, app, member)
        report = client.get('/api/set-completion?library_platform=NES&region=USA')
        assert report.status_code == 200
        data = report.get_json()
        assert data['owned'] == 1
        assert data['total'] == 3

        plats = client.get('/api/library_platforms?include_completion=1')
        assert plats.status_code == 200
        rows = plats.get_json()
        nes = next(r for r in rows if r['id'] == 'NES')
        assert 'set_completion' in nes
        assert nes['set_completion']['total'] == 3
        assert nes['set_completion']['owned'] == 1
        assert nes['set_completion']['region'] == 'USA'
        assert 'regions' not in nes['set_completion']
        assert 'set_completion_regions' in nes
        assert nes['set_completion_regions'][0]['region'] == 'USA'


def test_multi_region_heatmap_payload(app, client, db_session, admin, nes_lib, member):
    tag = uuid4().hex[:8]
    with app.app_context():
        upsert_reference_set(
            library_platform='NES',
            region='USA',
            source='nointro',
            dat_bytes=_tiny_dat(tag + 'u'),
            uploader_id=admin.id,
        )
        upsert_reference_set(
            library_platform='NES',
            region='EUR',
            source='nointro',
            dat_bytes=_tiny_dat(tag + 'e'),
            uploader_id=admin.id,
        )
        db_session.add(
            Game(
                uuid=str(uuid4()),
                name=f'Adventure Island {tag}u',
                library_uuid=nes_lib.uuid,
                full_disk_path=rf'C:\roms\Adventure Island {tag}u (USA).nes',
            )
        )
        db_session.commit()

    with client:
        _login(client, app, member)
        plats = client.get('/api/library_platforms?include_completion=1')
        assert plats.status_code == 200
        nes = next(r for r in plats.get_json() if r['id'] == 'NES')
        regions = nes['set_completion_regions']
        assert [r['region'] for r in regions] == ['USA', 'EUR']
        assert nes['set_completion']['region'] == 'USA'
        assert regions[0]['owned'] == 1
        assert regions[1]['owned'] == 0

    tag = uuid4().hex[:8]
    with app.app_context():
        ref = upsert_reference_set(
            library_platform='NES',
            region='EUR',
            source='nointro',
            dat_bytes=_tiny_dat(tag),
            uploader_id=admin.id,
        )
        set_id = ref.id

    with client:
        _login(client, app, admin)
        deleted = client.delete(f'/api/reference-sets/{set_id}')
        assert deleted.status_code == 200
        missing = client.get('/api/set-completion?library_platform=NES&region=EUR')
        assert missing.status_code == 404


def test_crc_match_beats_title(app, db_session, admin, nes_lib, member, tmp_path):
    """Owned file with DAT CRC matches even when the library title differs."""
    tag = uuid4().hex[:8]
    rom = tmp_path / f'weird-name-{tag}.nes'
    rom.write_bytes(b'NES\x1a' + b'\0' * 100)
    from oneirodex.utils.rom_hash import hash_rom_file

    hashes = hash_rom_file(rom)
    assert hashes is not None
    # Build DAT where Castlevania entry uses this file's CRC but we own a differently named game.
    dat = f"""<?xml version="1.0"?>
<datafile>
  <header><name>NES {tag}</name></header>
  <game name="Castlevania {tag} (USA)">
    <rom name="Castlevania {tag} (USA).nes" size="{rom.stat().st_size}" crc="{hashes['crc']}"/>
  </game>
  <game name="Other Missing {tag} (USA)">
    <rom name="Other Missing {tag} (USA).nes" size="10" crc="deadbeef"/>
  </game>
</datafile>
""".encode('utf-8')

    with app.app_context():
        upsert_reference_set(
            library_platform='NES',
            region='USA',
            source='nointro',
            dat_bytes=dat,
            uploader_id=admin.id,
        )
        game = Game(
            uuid=str(uuid4()),
            name=f'Totally Different Label {tag}',
            library_uuid=nes_lib.uuid,
            full_disk_path=str(rom),
            file_crc=hashes['crc'],
            file_md5=hashes['md5'],
            file_sha1=hashes['sha1'],
        )
        db_session.add(game)
        db_session.commit()

        report = compute_set_completion(
            library_platform='NES',
            region='USA',
            user=member,
            include_matched=True,
        )
        assert report['owned'] == 1
        assert report['missing_count'] == 1
        assert report['matched'][0]['match_method'] == 'crc'
        assert report['match_methods']['crc'] == 1


def test_hash_rom_file_and_rehash_api(app, client, db_session, admin, nes_lib, tmp_path):
    from oneirodex.utils.rom_hash import hash_rom_file

    rom = tmp_path / 'solo.nes'
    rom.write_bytes(b'abc123')
    assert hash_rom_file(rom)['crc']

    game = Game(
        uuid=str(uuid4()),
        name='Solo ROM',
        library_uuid=nes_lib.uuid,
        full_disk_path=str(rom),
    )
    db_session.add(game)
    db_session.commit()

    with client:
        _login(client, app, admin)
        res = client.post(
            '/api/reference-sets/rehash',
            json={'library_platform': 'NES'},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body['hashed'] >= 1

    db_session.refresh(game)
    assert game.file_crc
    assert game.file_md5
    assert game.file_sha1


def test_rehash_api_counts_permission_denied_rom_as_skipped(
    app, client, db_session, admin, nes_lib, tmp_path, monkeypatch,
):
    from pathlib import Path

    rom = tmp_path / 'unreadable.nes'
    rom.write_bytes(b'not readable by the rehash worker')
    game = Game(
        uuid=str(uuid4()),
        name='Unreadable ROM',
        library_uuid=nes_lib.uuid,
        full_disk_path=str(rom),
    )
    db_session.add(game)
    db_session.commit()

    original_open = Path.open

    def deny_rom_open(path, *args, **kwargs):
        if path == rom:
            raise PermissionError('synthetic unreadable ROM')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', deny_rom_open)
    with client:
        _login(client, app, admin)
        response = client.post(
            '/api/reference-sets/rehash', json={'library_platform': 'NES'},
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json() == {
        'platform': 'NES', 'considered': 1, 'hashed': 0, 'skipped': 1,
    }
    db_session.refresh(game)
    assert game.file_crc is None
    assert game.file_md5 is None
    assert game.file_sha1 is None
