"""422 contracts for wanted, hardlink, game-server create, and malware-scan JSON."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User


@pytest.fixture
def member_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'pyd_ops_member_{uid[:8]}',
        email=f'pyd_ops_member_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'pyd_ops_admin_{uid[:8]}',
        email=f'pyd_ops_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.id)
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def _assert_unprocessable(response, field: str) -> None:
    assert response.status_code == 422, response.get_data(as_text=True)
    body = response.get_json()
    assert body['ok'] is False
    assert body['error'] == 'Invalid request.'
    assert body['error_code'] == 'unprocessable'
    assert field in body['detail']


def test_wanted_add_requires_game_uuid(client, app, member_user):
    _login(client, app, member_user)
    response = client.post('/api/updates/wanted', json={})
    _assert_unprocessable(response, 'game_uuid')


def test_wanted_fulfill_requires_game_uuid(client, app, member_user):
    _login(client, app, member_user)
    response = client.post('/api/updates/wanted/fulfill', json={})
    _assert_unprocessable(response, 'game_uuid')


def test_hardlink_preview_requires_source_and_dest(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/storage/hardlink/preview', json={})
    _assert_unprocessable(response, 'source')
    assert 'dest' in response.get_json()['detail']


def test_hardlink_apply_requires_source_and_dest(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/storage/hardlink/apply', json={})
    _assert_unprocessable(response, 'source')
    assert 'dest' in response.get_json()['detail']


def test_game_server_create_requires_name_and_connect(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/game-servers', json={})
    _assert_unprocessable(response, 'display_name')
    assert 'connect_string' in response.get_json()['detail']


def test_malware_scan_requires_path(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/admin/malware-scan', json={})
    _assert_unprocessable(response, 'path')


def test_malware_scan_rejects_path_when_safety_check_returns_false_tuple(
    client, app, admin_user, monkeypatch
):
    from oneirodex.routes_apis import malware_scan

    _login(client, app, admin_user)
    monkeypatch.setattr(malware_scan, 'is_safe_path', lambda *_args: (False, 'outside'))
    monkeypatch.setattr(
        malware_scan, 'scan_path',
        lambda *_args: pytest.fail('scanner must not receive an unsafe path'),
    )

    response = client.post('/api/admin/malware-scan', json={'path': '/etc/passwd'})

    assert response.status_code == 403
    assert response.get_json()['error_code'] == 'forbidden'


def test_admin_images_page_renders_react_shell(client, app, admin_user):
    _login(client, app, admin_user)

    response = client.get('/admin/images')

    assert response.status_code == 200
    assert b'Oneirodex Admin' in response.data
