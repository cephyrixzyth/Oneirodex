"""Tests for layouts, AI assist, hardlinks, and VR browse."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import Game, Library, PlayerPerspective, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.detail_layouts import DEFAULT_SECTIONS, merge_with_defaults, validate_layout_payload
from oneirodex.utils.hardlinks import apply_hardlink, preview_hardlink
from oneirodex.utils.secondary_scrapers import VR_PERSPECTIVE_NAME


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


def test_merge_appends_missing_sections():
    merged = merge_with_defaults({'sections': [{'id': 'summary', 'visible': False}]})
    ids = [s['id'] for s in merged['sections']]
    assert ids[0] == 'summary'
    assert set(ids) == set(DEFAULT_SECTIONS)
    assert next(s for s in merged['sections'] if s['id'] == 'summary')['visible'] is False


def test_validate_rejects_unknown_section():
    with pytest.raises(ValueError):
        validate_layout_payload({'sections': [{'id': 'not-a-section', 'visible': True}]})


def test_layout_api_roundtrip(client, app, admin):
    _login(client, app, admin)
    resp = client.get('/api/layouts/detail')
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body['sections']) == len(DEFAULT_SECTIONS)
    payload = {'sections': [{'id': 'summary', 'visible': False}]}
    put = client.put('/api/layouts/detail', json=payload)
    assert put.status_code == 200
    saved = put.get_json()
    assert saved['sections'][0]['id'] == 'summary'
    assert saved['sections'][0]['visible'] is False


def test_triage_parses_suggestions(app, monkeypatch):
    def fake_post(method, url, validator=None, json=None, timeout=None):
        class R:
            status_code = 200
            text = 'ok'
            content = b'{"message":{"content":"1. Celeste"}}'

            def json(self):
                return {'message': {'content': '1. Celeste\n2. Celeste (2018)'}}
        return R()

    monkeypatch.setattr('oneirodex.utils.ai_assist.safe_request', fake_post)
    monkeypatch.setitem(app.config, 'ENABLE_AI_ASSIST', True)
    monkeypatch.setitem(app.config, 'OLLAMA_BASE_URL', 'http://ollama.test')
    with app.app_context():
        from oneirodex.utils.ai_assist import triage_folder
        out = triage_folder('Celeste-FitGirl', 'PCWIN')
    assert out['suggestions'][0]['title'] == 'Celeste'


def test_ai_triage_disabled(client, app, admin):
    _login(client, app, admin)
    app.config['ENABLE_AI_ASSIST'] = False
    # `ai_enabled()` ORs the config flag with GlobalSettings.enable_ai_assist,
    # so config alone does not disable it once any test has left a row behind —
    # the check has to establish both halves to be deterministic.
    from oneirodex import db
    from oneirodex.models import GlobalSettings

    settings = db.session.execute(
        db.select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if settings is not None:
        settings.enable_ai_assist = False
        db.session.commit()

    resp = client.post('/api/ai/triage', json={'name': 'Foo'})
    assert resp.status_code == 403


def test_preview_missing_source(tmp_path):
    result = preview_hardlink(str(tmp_path / 'nope'), str(tmp_path / 'out'))
    assert result['would_succeed'] is False
    assert any('source' in x.lower() for x in result['reasons'])


def test_hardlink_apply_same_volume(tmp_path):
    src = tmp_path / 'a.bin'
    src.write_bytes(b'1234')
    dest = tmp_path / 'b.bin'
    preview = preview_hardlink(str(src), str(dest))
    assert preview['would_succeed'] is True
    applied = apply_hardlink(str(src), str(dest))
    assert applied['applied'] is True
    assert dest.is_file()
    assert dest.read_bytes() == b'1234'


def test_hardlink_apply_api_requires_flags(client, app, admin, tmp_path, monkeypatch):
    _login(client, app, admin)
    src = tmp_path / 'a.bin'
    src.write_bytes(b'1234')
    dest = tmp_path / 'b.bin'
    monkeypatch.setitem(app.config, 'ENABLE_HARDLINK_HELPERS', True)
    monkeypatch.setitem(app.config, 'ALLOW_HARDLINK_APPLY', False)
    # Bypass path sandbox for unit test by pointing allowed bases via monkeypatch
    monkeypatch.setattr(
        'oneirodex.routes_apis.storage.get_allowed_base_directories',
        lambda _app: [str(tmp_path)],
    )
    resp = client.post(
        '/api/storage/hardlink/apply',
        json={'source': str(src), 'dest': str(dest)},
    )
    assert resp.status_code == 403


def test_vr_catalog_flag_off(client, app, admin):
    _login(client, app, admin)
    app.config['ENABLE_VR_BROWSE'] = False
    assert client.get('/api/vr/catalog').status_code == 403


def test_vr_catalog_flag_on(client, app, admin, db_session, tmp_path):
    _login(client, app, admin)
    app.config['ENABLE_VR_BROWSE'] = True
    unique = f'VR Game {uuid4().hex[:8]}'
    plain = f'Flat Game {uuid4().hex[:8]}'
    lib = Library(name=f'VRLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    vr_perspective = db_session.execute(
        select(PlayerPerspective).filter_by(name=VR_PERSPECTIVE_NAME).limit(1),
    ).scalars().first()
    if vr_perspective is None:
        vr_perspective = PlayerPerspective(name=VR_PERSPECTIVE_NAME)
        db_session.add(vr_perspective)
        db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=unique,
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g'),
    )
    other = Game(
        uuid=str(uuid4()),
        name=plain,
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'h'),
    )
    game.player_perspectives.append(vr_perspective)
    db_session.add_all([game, other])
    db_session.commit()
    detail = client.get(f'/api/vr/games/{game.uuid}')
    assert detail.status_code == 200
    assert detail.get_json()['name'] == unique
    assert client.get(f'/api/vr/games/{other.uuid}').status_code == 404
    resp = client.get('/api/vr/catalog?per_page=100')
    assert resp.status_code == 200
    body = resp.get_json()
    uuids = {g['uuid'] for g in body['games']}
    assert game.uuid in uuids
    assert other.uuid not in uuids
