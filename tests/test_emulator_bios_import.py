"""Admin firmware collection scan/install (operator-supplied dumps only)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask import Flask
from flask_login import login_user

from oneirodex.models import User
from oneirodex.utils.bios_install import (
    apply_firmware_import,
    firmware_import_allowed_bases,
    plan_firmware_import,
    volume_missing_markdown,
)
from oneirodex.utils.security import is_safe_path


@pytest.fixture()
def bios_app(tmp_path):
    application = Flask(__name__)
    dest = tmp_path / 'volume'
    dest.mkdir()
    application.config['EMULATOR_BIOS_PATH'] = str(dest)
    application.config['BIOS_IMPORT_SOURCE'] = str(tmp_path / 'pack')
    application.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    application.config['BASE_FOLDER_WINDOWS'] = str(tmp_path)
    application.config['BASE_FOLDER_POSIX'] = str(tmp_path)
    application.config['ONEIRODEX_LIBRARY_ROOTS'] = ''
    return application


def _login_admin(client, app, db_session):
    uid = str(uuid4())
    admin = User(
        name=f'bios_{uid[:8]}',
        email=f'bios_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    admin.set_password('password123')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(admin)
    return admin


def test_plan_finds_nested_dumps_and_reports_missing(bios_app, tmp_path):
    pack = tmp_path / 'pack' / 'saturn'
    pack.mkdir(parents=True)
    (pack / 'saturn_bios.bin').write_bytes(b'saturn-dump')

    with bios_app.app_context():
        plan = plan_firmware_import(str(tmp_path / 'pack'))

    names = {row['name'] for row in plan['matches']}
    assert 'saturn_bios.bin' in names
    assert plan['conflict_count'] == 0
    assert 'Firmware still needed' in plan['missing_markdown']
    assert 'saturn_bios.bin' not in plan['missing_markdown']
    assert any(row['name'] == 'scph5501.bin' for row in plan['missing']) or 'PlayStation' in plan['missing_markdown']


def test_plan_lists_version_conflicts_instead_of_picking_silently(bios_app, tmp_path):
    pack = tmp_path / 'pack'
    (pack / 'a').mkdir(parents=True)
    (pack / 'b').mkdir(parents=True)
    (pack / 'a' / 'saturn_bios.bin').write_bytes(b'version-one')
    (pack / 'b' / 'saturn_bios.bin').write_bytes(b'version-two-different')

    with bios_app.app_context():
        plan = plan_firmware_import(str(pack))

    match = next(row for row in plan['matches'] if row['name'] == 'saturn_bios.bin')
    assert len(match['versions']) == 2
    assert plan['conflict_count'] == 1
    assert 'Version conflicts' in plan['missing_markdown']
    assert '`saturn_bios.bin`' in plan['missing_markdown']


def test_apply_installs_the_selected_dump(bios_app, tmp_path):
    pack = tmp_path / 'pack'
    dest = tmp_path / 'volume'
    (pack / 'a').mkdir(parents=True)
    (pack / 'b').mkdir(parents=True)
    (pack / 'a' / 'saturn_bios.bin').write_bytes(b'AAA')
    (pack / 'b' / 'saturn_bios.bin').write_bytes(b'BBBBBB')

    with bios_app.app_context():
        plan = plan_firmware_import(str(pack), str(dest))
        match = next(row for row in plan['matches'] if row['name'] == 'saturn_bios.bin')
        minority = next(row for row in match['versions'] if row['paths'][0].startswith('b/'))
        result = apply_firmware_import(
            str(pack),
            str(dest),
            selections={'saturn_bios.bin': minority['digest']},
        )

    assert result['copied'] == ['saturn_bios.bin']
    assert (dest / 'saturn_bios.bin').read_bytes() == b'BBBBBB'


def test_apply_respects_skipped_and_does_not_overwrite(bios_app, tmp_path):
    pack = tmp_path / 'pack'
    dest = tmp_path / 'volume'
    pack.mkdir()
    dest.mkdir(exist_ok=True)
    (pack / 'saturn_bios.bin').write_bytes(b'from-pack')
    (dest / 'saturn_bios.bin').write_bytes(b'already-there')

    with bios_app.app_context():
        skipped = apply_firmware_import(
            str(pack),
            str(dest),
            skipped=['saturn_bios.bin'],
        )
        kept = apply_firmware_import(str(pack), str(dest), overwrite=False)

    assert 'saturn_bios.bin' in skipped['skipped']
    assert kept['copied'] == []
    assert (dest / 'saturn_bios.bin').read_bytes() == b'already-there'


def test_collection_must_sit_under_an_allowed_base(bios_app, tmp_path):
    allowed = tmp_path / 'ok'
    other = tmp_path / 'no'
    allowed.mkdir()
    other.mkdir()
    bios_app.config['BIOS_IMPORT_SOURCE'] = str(allowed)
    bios_app.config['DATA_FOLDER_GAMES'] = str(allowed)
    bios_app.config['BASE_FOLDER_WINDOWS'] = str(allowed)
    bios_app.config['BASE_FOLDER_POSIX'] = str(allowed)

    with bios_app.app_context():
        ok, _reason = is_safe_path(str(allowed), firmware_import_allowed_bases(bios_app))
        denied, _reason = is_safe_path(str(other), firmware_import_allowed_bases(bios_app))

    assert ok is True
    assert denied is False


def test_volume_markdown_never_offers_a_download(bios_app):
    with bios_app.app_context():
        text = volume_missing_markdown()
    assert 'Firmware still needed' in text
    assert 'never downloads BIOS' in text.lower() or 'never downloads' in text.lower()
    assert 'http' not in text.lower()


def test_scan_and_install_routes(client, app, db_session, configured_install, tmp_path, monkeypatch):
    _login_admin(client, app, db_session)
    pack = tmp_path / 'pack'
    dest = tmp_path / 'volume'
    pack.mkdir()
    dest.mkdir()
    (pack / 'saturn_bios.bin').write_bytes(b'saturn-dump')
    app.config['EMULATOR_BIOS_PATH'] = str(dest)
    app.config['BIOS_IMPORT_SOURCE'] = str(pack)

    monkeypatch.setattr(
        'oneirodex.utils.bios_install.firmware_import_allowed_bases',
        lambda _app: [str(tmp_path)],
    )

    listed = client.get('/api/emulator-bios')
    assert listed.status_code == 200
    body = listed.get_json()
    assert 'missing_markdown' in body
    assert body['import_source'] == str(pack)

    scanned = client.post('/api/emulator-bios/scan', json={'source': str(pack)})
    assert scanned.status_code == 200
    plan = scanned.get_json()
    assert plan['ok'] is True
    assert any(row['name'] == 'saturn_bios.bin' for row in plan['matches'])
    assert 'Firmware still needed' in plan['missing_markdown']

    installed = client.post(
        '/api/emulator-bios/install',
        json={'source': str(pack), 'selections': {}, 'skipped': [], 'overwrite': False},
    )
    assert installed.status_code == 200
    result = installed.get_json()
    assert result['copied_count'] == 1
    assert (dest / 'saturn_bios.bin').read_bytes() == b'saturn-dump'


def test_scan_refuses_a_folder_outside_the_allowlist(
    client, app, db_session, configured_install, tmp_path, monkeypatch,
):
    _login_admin(client, app, db_session)
    pack = tmp_path / 'pack'
    allowed = tmp_path / 'allowed'
    pack.mkdir()
    allowed.mkdir()
    monkeypatch.setattr(
        'oneirodex.utils.bios_install.firmware_import_allowed_bases',
        lambda _app: [str(allowed)],
    )

    response = client.post('/api/emulator-bios/scan', json={'source': str(pack)})
    assert response.status_code == 403
    data = response.get_json()
    assert data['ok'] is False
    assert data['error_code'] == 'forbidden'
    assert 'BIOS_IMPORT_SOURCE' in data['error']
