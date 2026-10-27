"""INSP-6 / H4d: the BYO notification bus (Apprise API / ntfy). Mocked transport only."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User
from oneirodex.utils import notification_bus as bus


def _resp(code=200):
    return SimpleNamespace(status_code=code)


def test_unconfigured_bus_is_silent_and_never_calls_out(monkeypatch):
    monkeypatch.delenv('NOTIFY_APPRISE_URLS', raising=False)
    monkeypatch.delenv('NOTIFY_NTFY_URL', raising=False)
    assert bus.configured() is False
    with patch.object(bus, 'safe_request') as req:
        assert bus.emit(kind='scan_done', title='Scan finished') == {'apprise': 0, 'ntfy': 0}
        req.assert_not_called()


def test_emit_posts_to_every_endpoint_with_the_right_shape(monkeypatch):
    monkeypatch.setenv('NOTIFY_APPRISE_URLS', 'http://apprise:8000/notify/oneirodex, http://apprise2:8000/notify/x')
    monkeypatch.setenv('NOTIFY_NTFY_URL', 'https://ntfy.example/household')
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return _resp(200)

    with patch.object(bus, 'safe_request', side_effect=fake):
        sent = bus.emit(kind='scan_failed', title='Scan failed: PC', body='3 folders errored', link='https://od/admin/scan')
    assert sent == {'apprise': 2, 'ntfy': 1}
    apprise = [c for c in calls if '/notify/' in c[1]]
    assert len(apprise) == 2 and apprise[0][2]['json'] == {'title': 'Scan failed: PC', 'body': '3 folders errored', 'type': 'error', 'format': 'text'}
    ntfy = [c for c in calls if 'ntfy.example' in c[1]][0]
    assert ntfy[2]['data'] == b'3 folders errored'
    assert ntfy[2]['headers']['Title'] == 'Scan failed: PC' and ntfy[2]['headers']['Priority'] == 'high'
    assert ntfy[2]['headers']['Click'] == 'https://od/admin/scan'
    for _, _, kw in calls:
        assert kw['timeout'] == bus.TIMEOUT_SECONDS and kw['validator'] is bus.validate_user_outbound_http_url


def test_a_dead_endpoint_is_counted_zero_and_never_raises(monkeypatch):
    monkeypatch.setenv('NOTIFY_APPRISE_URLS', 'http://apprise:8000/notify/oneirodex')
    monkeypatch.setenv('NOTIFY_NTFY_URL', 'https://ntfy.example/household')

    def fake(method, url, **kw):
        if 'apprise' in url:
            raise OSError('connection refused')
        return _resp(503)

    with patch.object(bus, 'safe_request', side_effect=fake):
        assert bus.emit(kind='info', title='x') == {'apprise': 0, 'ntfy': 0}


def test_apprise_failure_log_omits_endpoint_userinfo_and_path(monkeypatch, caplog):
    secret = 'notify-secret-should-not-log'
    endpoint = f'https://operator:{secret}@apprise.example/notify/private-topic'
    monkeypatch.setenv('NOTIFY_APPRISE_URLS', endpoint)
    with patch.object(bus, 'safe_request', side_effect=OSError('connection refused')):
        bus.emit(kind='info', title='x')
    assert secret not in caplog.text
    assert 'private-topic' not in caplog.text
    assert 'https://apprise.example' in caplog.text


def test_social_kinds_need_the_operator_opt_in(monkeypatch):
    monkeypatch.setenv('NOTIFY_NTFY_URL', 'https://ntfy.example/household')
    monkeypatch.delenv('NOTIFY_SOCIAL_TO_BUS', raising=False)
    with patch.object(bus, 'safe_request', return_value=_resp()) as req:
        assert bus.publish_user_event(kind='friend_request', title='A wants to be friends') == {'apprise': 0, 'ntfy': 0}
        # A non-social member kind is not the bus's business either (admin alerts go through publish_admin_event)
        assert bus.publish_user_event(kind='library_added', title='x') == {'apprise': 0, 'ntfy': 0}
        req.assert_not_called()
    monkeypatch.setenv('NOTIFY_SOCIAL_TO_BUS', 'true')
    with patch.object(bus, 'safe_request', return_value=_resp()) as req:
        assert bus.publish_user_event(kind='friend_request', title='A wants to be friends')['ntfy'] == 1
        assert req.call_args.kwargs['headers']['Priority'] == 'default'


def test_notify_admins_publishes_one_bus_event_not_one_per_admin(db_session, monkeypatch):
    from oneirodex.utils.notifications import notify_admins

    for i in range(2):
        uid = str(uuid4())
        row = User(name=f'adm_{uid[:6]}', email=f'adm_{uid[:6]}@example.com', role='admin', user_id=uid, state=True)
        row.set_password('password123')
        db_session.add(row)
    db_session.commit()
    monkeypatch.setenv('NOTIFY_NTFY_URL', 'https://ntfy.example/household')
    monkeypatch.delenv('NOTIFY_APPRISE_URLS', raising=False)
    with patch.object(bus, 'safe_request', return_value=_resp()) as req:
        delivered = notify_admins(kind='scan_done', title='Scan finished', body='PC: 12 added', link='/admin/scan')
    assert delivered >= 2
    assert req.call_count == 1
    assert req.call_args.kwargs['headers']['Click'].endswith('/admin/scan')


def test_admin_test_route(client, app, db_session, monkeypatch):
    uid = str(uuid4())
    admin = User(name=f'adm_{uid[:6]}', email=f'adm_{uid[:6]}@example.com', role='admin', user_id=uid, state=True)
    admin.set_password('password123')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(admin)

    monkeypatch.delenv('NOTIFY_APPRISE_URLS', raising=False)
    monkeypatch.delenv('NOTIFY_NTFY_URL', raising=False)
    resp = client.post('/api/admin/notify-bus/test')
    assert resp.status_code == 400 and resp.get_json()['configured'] is False

    monkeypatch.setenv('NOTIFY_NTFY_URL', 'https://ntfy.example/household')
    with patch.object(bus, 'safe_request', return_value=_resp()):
        resp = client.post('/api/admin/notify-bus/test')
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['ok'] is True and body['sent'] == {'apprise': 0, 'ntfy': 1} and body['ntfy'] is True
