"""Virtual-device pass, Layer 3: a stand-in game server on a real local socket.

The registry's status route does a TCP connect (or an HTTP health GET) to a
household server. A listener on an ephemeral loopback port stands in for the
Minecraft/Valheim box: reachable while it listens, unreachable once it closes,
and the answer never carries the host or the exception text.
"""
import socket
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(name=f'gs_{uid[:8]}', email=f'gs_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
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
def listener():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(5)
    yield sock
    sock.close()


def _register(client, port):
    response = client.post('/api/game-servers', json={
        'display_name': 'Fake Valheim',
        'connect_string': f'127.0.0.1:{port}',
    })
    assert response.status_code == 201, response.get_data(as_text=True)[:200]
    return response.get_json()['uuid']


def test_status_follows_the_listener_up_and_down(client, app, admin, listener):
    _login(client, app, admin)
    server_uuid = _register(client, listener.getsockname()[1])

    up = client.get(f'/api/game-servers/{server_uuid}/status').get_json()
    assert up['reachable'] is True and up['method'] == 'tcp'

    listener.close()
    down = client.get(f'/api/game-servers/{server_uuid}/status').get_json()
    assert down['reachable'] is False


def test_status_answer_never_leaks_the_host_or_exception_text(client, app, admin, listener):
    _login(client, app, admin)
    port = listener.getsockname()[1]
    server_uuid = _register(client, port)
    listener.close()
    raw = client.get(f'/api/game-servers/{server_uuid}/status').get_data(as_text=True)
    assert 'Errno' not in raw and 'refused' not in raw.lower()
    assert f'127.0.0.1:{port}' not in raw


def test_a_blocked_health_url_is_reported_without_the_url(client, app, admin):
    _login(client, app, admin)
    response = client.post('/api/game-servers', json={
        'display_name': 'Metadata probe',
        'connect_string': '127.0.0.1:1',
        'health_url': 'http://169.254.169.254/latest/meta-data/',
    })
    server_uuid = response.get_json()['uuid']
    status = client.get(f'/api/game-servers/{server_uuid}/status').get_json()
    assert status['reachable'] is False
    assert '169.254' not in str(status['error'])
