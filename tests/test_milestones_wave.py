"""Tests for emulator profiles, arr scaffold, and OIDC readiness."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import GlobalSettings, User
from oneirodex.utils.emulator_profiles import (
    get_emulator_profiles,
    resolve_emulators_for_platform,
    set_emulator_profiles,
)
from oneirodex.utils.oidc import oidc_readiness_report


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    row = User(
        name=f'eadmin_{uid[:8]}',
        email=f'eadmin_{uid[:8]}@example.com',
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


def _ensure_settings(db_session, **kwargs):
    row = db_session.query(GlobalSettings).order_by(GlobalSettings.id).first()
    if not row:
        row = GlobalSettings()
        db_session.add(row)
        db_session.flush()
    for key, value in kwargs.items():
        setattr(row, key, value)
    db_session.commit()
    return row


def test_set_and_resolve_emulator_profile(app, db_session):
    with app.app_context():
        _ensure_settings(db_session, emulator_profiles=None)
        saved = set_emulator_profiles({'NES': 'nestopia'})
        assert saved['NES'] == 'nestopia'
        assert get_emulator_profiles()['NES'] == 'nestopia'
        resolved = resolve_emulators_for_platform('NES')
        assert resolved['preferred'] == 'nestopia'
        assert resolved['emulators'][0] == 'nestopia'


def test_emulator_profiles_api(client, app, db_session, admin_user):
    _login(client, app, admin_user)
    _ensure_settings(db_session, emulator_profiles={})
    resp = client.put('/api/emulator-profiles', json={'profiles': {'SNES': 'snes9x'}})
    assert resp.status_code == 200
    assert resp.get_json()['profiles']['SNES'] == 'snes9x'
    get_resp = client.get('/api/emulators/SNES')
    assert get_resp.status_code == 200
    body = get_resp.get_json()
    assert body['preferred'] == 'snes9x'
    assert body['emulators'][0] == 'snes9x'


def test_arr_status_disabled_by_default(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.delenv('ENABLE_ARR_MODULE', raising=False)
    _ensure_settings(db_session, enable_arr_module=False)
    _login(client, app, admin_user)
    with app.app_context():
        app.config['ENABLE_ARR_MODULE'] = False
    resp = client.get('/api/arr/status')
    assert resp.status_code == 200
    assert resp.get_json()['enabled'] is False


def test_oidc_readiness_reports_missing(app, db_session, monkeypatch):
    monkeypatch.setenv('OIDC_ENABLED', 'false')
    _ensure_settings(db_session, oidc_enabled=False)
    with app.app_context():
        report = oidc_readiness_report()
        assert report['ready'] is False
        assert report['live_verified'] is False
        assert 'OIDC_ENABLED env' in report['missing']


def test_oidc_status_api(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('OIDC_ENABLED', 'false')
    _login(client, app, admin_user)
    resp = client.get('/api/oidc/status')
    assert resp.status_code == 200
    assert 'missing' in resp.get_json()
