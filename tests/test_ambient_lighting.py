"""Ambient lighting bridge (LIGHT-1/LIGHT-2)."""

from __future__ import annotations

import ipaddress
from unittest.mock import MagicMock, patch

import pytest

from oneirodex.utils.ambient_lighting import (
    HyperionClient,
    HomeAssistantClient,
    ambient_lighting_status,
    get_ambient_config,
    notify_play_session_started,
    notify_play_session_stopped,
    save_ambient_config,
)


@pytest.fixture
def resolvable(monkeypatch):
    """``hyperion`` and ``ha`` are compose service names that only resolve on a
    real host. ``safe_request`` dials the address it resolved and refuses a name
    it cannot, so the unit tests resolve them (to a public address, which every
    validator accepts) instead of reaching for DNS."""
    from oneirodex.utils import security

    monkeypatch.setattr(security, '_resolve_host', lambda host: [ipaddress.ip_address('93.184.216.34')])


def _disable_ambient(app, db_session, monkeypatch):
    from sqlalchemy.orm.attributes import flag_modified

    from oneirodex.models import GlobalSettings

    monkeypatch.setitem(app.config, 'ENABLE_AMBIENT_LIGHTING', False)
    monkeypatch.setitem(app.config, 'LIGHTING_PROVIDER', 'off')
    row = db_session.query(GlobalSettings).order_by(GlobalSettings.id).first()
    if row is None:
        return
    cfg = dict(row.arr_settings) if isinstance(row.arr_settings, dict) else {}
    cfg['ambient_lighting_enabled'] = False
    # Clear provider so env LIGHTING_PROVIDER can apply in later tests
    cfg.pop('lighting_provider', None)
    row.arr_settings = cfg
    flag_modified(row, 'arr_settings')
    db_session.commit()


def test_hyperion_client_set_color_and_clear(resolvable):
    session = MagicMock()
    session.request.return_value = MagicMock(
        status_code=200,
        is_redirect=False,
        content=b'{"success":true}',
        json=lambda: {'success': True},
    )
    client = HyperionClient('http://hyperion:8090', priority=50, session=session)
    client.set_color((255, 128, 32))
    client.clear_priority()
    # Requests go through safe_request, which drives session.request one hop at
    # a time (redirects are revalidated, never followed blindly) and dials the
    # address it validated, keeping the name on Host.
    assert session.request.call_count == 2
    first = session.request.call_args_list[0]
    assert first[0][:2] == ('POST', 'http://93.184.216.34:8090/json-rpc')
    assert first[1]['headers']['Host'] == 'hyperion:8090'
    assert first[1]['json']['command'] == 'color'
    assert first[1]['json']['color'] == [255, 128, 32]
    assert first[1]['json']['priority'] == 50
    assert first[1]['allow_redirects'] is False
    second = session.request.call_args_list[1]
    assert second[1]['json']['command'] == 'clear'


def test_ha_client_turn_on_lights_and_scene(resolvable):
    session = MagicMock()
    session.request.return_value = MagicMock(status_code=200, is_redirect=False)
    client = HomeAssistantClient('http://ha:8123', 'token-secret', session=session)
    client.turn_on_lights(['light.living'], (10, 20, 30))
    client.turn_on_scene('scene.now_playing')
    assert session.request.call_count == 2
    light_call = session.request.call_args_list[0]
    assert light_call[0][:2] == ('POST', 'http://93.184.216.34:8123/api/services/light/turn_on')
    assert light_call[1]['headers']['Host'] == 'ha:8123'
    assert light_call[1]['json']['entity_id'] == ['light.living']
    assert light_call[1]['headers']['Authorization'] == 'Bearer token-secret'
    scene_call = session.request.call_args_list[1]
    assert scene_call[0][:2] == ('POST', 'http://93.184.216.34:8123/api/services/scene/turn_on')


def test_save_ambient_config_validates_urls(app, db_session, global_settings, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        saved = save_ambient_config({
            'enabled': True,
            'provider': 'hyperion',
            'hyperion_url': 'http://192.168.1.20:8090',
            'ambient_accent_color': '#ff8000',
        })
        assert saved['db_enabled'] is True
        assert saved['provider'] == 'hyperion'
        assert saved['hyperion_url'] == 'http://192.168.1.20:8090'

        with pytest.raises(ValueError, match='not allowed'):
            save_ambient_config({'ha_url': 'http://169.254.169.254/'})


def test_notify_play_session_skips_child(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ENABLE_AMBIENT_LIGHTING', True)
    monkeypatch.setitem(app.config, 'LIGHTING_PROVIDER', 'hyperion')
    monkeypatch.setitem(app.config, 'HYPERION_URL', 'http://192.168.1.20:8090')
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)

    from uuid import uuid4

    from oneirodex.models import User

    uid = uuid4().hex[:8]
    child = User(
        name=f'lightchild_{uid}',
        email=f'lightchild_{uid}@test.local',
        role='child',
        is_email_verified=True,
    )
    child.set_password('testpass123')
    db_session.add(child)
    db_session.commit()

    with app.app_context():
        with patch('oneirodex.utils.ambient_lighting._run_async') as mock_async:
            notify_play_session_started(child, None)
            notify_play_session_stopped(user=child)
    mock_async.assert_not_called()


def test_notify_play_session_start_async_hyperion(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ENABLE_AMBIENT_LIGHTING', True)
    monkeypatch.setitem(app.config, 'LIGHTING_PROVIDER', 'hyperion')
    monkeypatch.setitem(app.config, 'HYPERION_URL', 'http://192.168.1.20:8090')
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)

    from uuid import uuid4

    from oneirodex.models import User

    uid = uuid4().hex[:8]
    user = User(
        name=f'lightuser_{uid}',
        email=f'lightuser_{uid}@test.local',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()

    with app.app_context():
        with patch('oneirodex.utils.ambient_lighting._run_async') as mock_async:
            notify_play_session_started(user, None)
    mock_async.assert_called_once()


def test_ambient_lighting_status_api(client, app, db_session, monkeypatch):
    _disable_ambient(app, db_session, monkeypatch)
    from uuid import uuid4

    from oneirodex.models import User

    admin = User(
        user_id=str(uuid4()),
        name=f'aladmin_{uuid4().hex[:8]}',
        email=f'aladmin_{uuid4().hex[:8]}@test.local',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True
    resp = client.get('/api/admin/ambient-lighting/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['enabled'] is False
    assert data['provider'] == 'off'


def test_ambient_lighting_test_probe_mocked(app, db_session, monkeypatch):
    from sqlalchemy.orm.attributes import flag_modified

    from oneirodex.models import GlobalSettings

    monkeypatch.setitem(app.config, 'ENABLE_AMBIENT_LIGHTING', True)
    monkeypatch.setitem(app.config, 'LIGHTING_PROVIDER', 'hyperion')
    monkeypatch.setitem(app.config, 'HYPERION_URL', 'http://192.168.1.20:8090')
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    row = db_session.query(GlobalSettings).order_by(GlobalSettings.id).first()
    if row is not None:
        cfg = dict(row.arr_settings) if isinstance(row.arr_settings, dict) else {}
        cfg.pop('lighting_provider', None)
        row.arr_settings = cfg
        flag_modified(row, 'arr_settings')
        db_session.commit()

    with app.app_context():
        with patch('oneirodex.utils.ambient_lighting.HyperionClient') as mock_cls:
            inst = MagicMock()
            mock_cls.return_value = inst
            status = ambient_lighting_status(probe=True)
    assert status['provider'] == 'hyperion'
    assert status['probe_ok'] is True
    inst.set_color.assert_called_once()
    inst.clear_priority.assert_called_once()


def test_provider_off_no_network_when_disabled(app, db_session, monkeypatch):
    _disable_ambient(app, db_session, monkeypatch)
    with app.app_context():
        cfg = get_ambient_config()
        assert cfg['enabled'] is False
        assert cfg['provider'] == 'off'
