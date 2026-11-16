"""Tests for ops follow-ons: AI apply, arr→hardlink, OIDC local-optional."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from flask import Flask
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.arr_hardlink_pipeline import apply_proposals, propose_hardlinks


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'ops_{uid[:8]}',
        email=f'ops_{uid[:8]}@example.com',
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


def test_ai_apply_requires_flag(client, app, admin, db_session, tmp_path):
    _login(client, app, admin)
    app.config['ENABLE_AI_ASSIST'] = True
    app.config['ENABLE_AI_AUTO_APPLY'] = False
    lib = Library(name=f'L_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name='Old Name',
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g'),
    )
    db_session.add(game)
    db_session.commit()
    resp = client.post('/api/ai/apply-triage', json={
        'game_uuid': game.uuid,
        'title': 'New Name',
    })
    assert resp.status_code == 403


def test_ai_apply_renames_when_enabled(client, app, admin, db_session, tmp_path):
    _login(client, app, admin)
    app.config['ENABLE_AI_ASSIST'] = True
    app.config['ENABLE_AI_AUTO_APPLY'] = True
    lib = Library(name=f'L_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name='Old Name',
        library_uuid=lib.uuid,
        full_disk_path=str(tmp_path / 'g'),
    )
    db_session.add(game)
    db_session.commit()
    resp = client.post('/api/ai/apply-triage', json={
        'game_uuid': game.uuid,
        'title': 'Celeste',
    })
    assert resp.status_code == 201
    assert resp.get_json()['name'] == 'Celeste'
    db_session.refresh(game)
    assert game.name == 'Celeste'


def test_arr_hardlink_pipeline_flag_off(client, app, admin):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = True
    app.config['ENABLE_ARR_HARDLINK_PIPELINE'] = False
    resp = client.post('/api/arr/hardlink/preview', json={'library_dest_dir': 'C:\\tmp'})
    assert resp.status_code == 403


def test_propose_hardlinks_from_file(app, tmp_path, monkeypatch):
    app.config['ENABLE_ARR_HARDLINK_PIPELINE'] = True
    app.config['ENABLE_HARDLINK_HELPERS'] = True
    src_dir = tmp_path / 'dl'
    dest_dir = tmp_path / 'lib'
    src_dir.mkdir()
    dest_dir.mkdir()
    src = src_dir / 'game.bin'
    src.write_bytes(b'abc')

    monkeypatch.setattr(
        'oneirodex.utils.arr_hardlink_pipeline.get_allowed_base_directories',
        lambda _app: [str(tmp_path)],
    )
    monkeypatch.setattr(
        'oneirodex.utils.arr_hardlink_pipeline.list_completed_torrents',
        lambda limit=50: [{
            'hash': 'abc',
            'name': 'game',
            'content_path': str(src),
        }],
    )
    with app.app_context():
        result = propose_hardlinks(str(dest_dir), torrents=[{
            'hash': 'abc',
            'name': 'game',
            'content_path': str(src),
        }])
    assert result['count'] == 1
    assert result['proposals'][0]['preview']['would_succeed'] is True

    app.config['ALLOW_HARDLINK_APPLY'] = True
    with app.app_context():
        applied = apply_proposals(result['proposals'])
    assert applied['applied_count'] == 1
    assert os.path.isfile(result['proposals'][0]['dest'])


def test_propose_hardlinks_rejects_out_of_root_before_walking(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        ENABLE_ARR_HARDLINK_PIPELINE=True,
        ENABLE_HARDLINK_HELPERS=True,
        ALLOW_HARDLINK_APPLY=False,
    )
    allowed_root = tmp_path / 'library'
    outside_root = tmp_path / 'outside'
    allowed_root.mkdir()
    outside_root.mkdir()

    monkeypatch.setattr(
        'oneirodex.utils.arr_hardlink_pipeline.get_allowed_base_directories',
        lambda _app: [str(allowed_root)],
    )
    monkeypatch.setattr(
        'oneirodex.utils.arr_hardlink_pipeline._pick_source_file',
        lambda _path: pytest.fail('out-of-root source must be rejected before walking'),
    )

    with app.app_context():
        result = propose_hardlinks(
            str(allowed_root),
            torrents=[{'name': 'Outside', 'content_path': str(outside_root)}],
        )

    proposal = result['proposals'][0]
    assert proposal['dest'] is None
    assert proposal['preview']['would_succeed'] is False
    assert proposal['preview']['reasons'] == [
        'Access denied - path outside allowed directories'
    ]


def test_oidc_status_local_optional(client, app, admin):
    _login(client, app, admin)
    app.config['OIDC_ENABLED'] = False
    # readiness uses env; ensure endpoint works for operators
    resp = client.get('/api/oidc/status')
    assert resp.status_code == 200
    body = resp.get_json()
    assert 'ready' in body
    assert body['ready'] is False


def test_vr_sw_route(client, app, configured_install):
    app.config['ENABLE_VR_BROWSE'] = True
    resp = client.get('/vr/sw.js')
    assert resp.status_code == 200
    assert 'serviceWorker' in resp.get_data(as_text=True) or 'CACHE' in resp.get_data(as_text=True)
