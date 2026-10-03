"""Virtual-device pass, Layer 3: a stand-in Sunshine/Wolf host.

The server never contacts the Moonlight host, so the stand-in is a base URL.
What matters is what the admin can set and what a member is allowed to see: the
host and hints to paste into Moonlight, never the operator token.
"""
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User

pytestmark = pytest.mark.integration


def _person(db_session, role):
    uid = str(uuid4())
    row = User(name=f'rp_{uid[:8]}', email=f'rp_{uid[:8]}@example.com', role=role, user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, person):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(person.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(person)


@pytest.fixture
def lan_app(app):
    saved = app.config.get('ALLOW_PRIVATE_LAN_URLS')
    app.config['ALLOW_PRIVATE_LAN_URLS'] = True
    yield app
    app.config['ALLOW_PRIVATE_LAN_URLS'] = saved


def test_admin_config_reaches_members_without_the_token(client, lan_app, db_session):
    admin = _person(db_session, 'admin')
    _login(client, lan_app, admin)
    saved = client.put('/api/admin/remote-play/config', json={
        'enabled': True,
        'provider': 'wolf',
        'wolf_base_url': 'http://192.168.1.50:47989',
        'host_label': 'Living room PC',
        'pin_hint': '1234',
        'token': 'operator-secret-token',
    })
    assert saved.status_code == 200, saved.get_data(as_text=True)[:200]

    member = _person(db_session, 'user')
    _login(client, lan_app, member)
    raw = client.get('/api/remote-play/status').get_data(as_text=True)
    status = client.get('/api/remote-play/status').get_json()

    assert status['enabled'] and status['configured'] and status['provider'] == 'wolf'
    assert (status['moonlight_host'], status['moonlight_port']) == ('192.168.1.50', 47989)
    assert 'Living room PC' in status['copy_hint'] and 'PIN: 1234' in status['copy_hint']
    assert 'operator-secret-token' not in raw


def test_enabling_without_a_host_is_refused(client, lan_app, db_session):
    _login(client, lan_app, _person(db_session, 'admin'))
    response = client.put('/api/admin/remote-play/config', json={'enabled': True})
    assert response.status_code == 400


def test_a_cloud_metadata_host_is_refused_even_on_a_lan_install(client, lan_app, db_session):
    _login(client, lan_app, _person(db_session, 'admin'))
    response = client.put('/api/admin/remote-play/config', json={
        'enabled': True, 'sunshine_base_url': 'http://169.254.169.254:47989',
    })
    assert response.status_code == 400


def test_members_cannot_write_the_config(client, lan_app, db_session):
    _login(client, lan_app, _person(db_session, 'user'))
    response = client.put('/api/admin/remote-play/config', json={'enabled': True})
    assert response.status_code in (302, 401, 403)
