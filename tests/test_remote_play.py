"""Tests for GOW-1/GOW-2 remote play (Sunshine/Wolf BYO host)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from oneirodex.models import GlobalSettings, User


def _login(client, db_session, *, role='admin'):
    user = User(
        user_id=str(uuid4()),
        name=f'rp_{uuid4().hex[:8]}',
        email=f'rp_{uuid4().hex[:8]}@test.local',
        role=role,
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    return user


def test_global_settings_has_remote_play_columns():
    assert hasattr(GlobalSettings, 'enable_remote_play')
    assert hasattr(GlobalSettings, 'remote_play_settings')


def test_save_validates_lan_url(app, db_session, global_settings, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    # An UPDATE on the existing singleton, not a second INSERT — the value is
    # what this test needs, a fresh row is not.
    global_settings.enable_remote_play = True
    db_session.commit()
    with app.app_context():
        from oneirodex.utils.remote_play import save_remote_play_config

        with pytest.raises(ValueError, match='ALLOW_PRIVATE_LAN_URLS'):
            save_remote_play_config({
                'enabled': True,
                'sunshine_base_url': 'http://192.168.1.10:47989',
            })


def test_build_copy_hint():
    from oneirodex.utils.remote_play import build_copy_hint

    hint = build_copy_hint({
        'configured': True,
        'moonlight_host': '192.168.1.2',
        'moonlight_port': 47989,
        'host_label': 'Lab',
        'app_hint': 'RetroArch',
        'pin_hint': '1234',
    })
    assert '192.168.1.2' in hint
    assert 'Lab' in hint
    assert 'RetroArch' in hint
