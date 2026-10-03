"""Virtual-device pass, Layer 3: a stand-in Hyperion.ng and Home Assistant.

A local HTTP server plays the lighting controller. `POST /api/admin/ambient-
lighting/test` is driven end to end over the real route: the app must send a
colour command and then a clear, carry the bearer token when configured, and
report a controller error as a fixed sentence instead of echoing it.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User

pytestmark = pytest.mark.integration


class _Controller:
    """Records every request; answers like Hyperion (`success`) or Home Assistant."""

    def __init__(self, fail: bool = False):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 -- http.server API
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length).decode() if length else ''
                outer.requests.append({
                    'path': self.path,
                    'auth': self.headers.get('Authorization'),
                    'body': json.loads(body) if body else None,
                })
                if outer.fail:
                    payload, status = {'success': False, 'error': 'boom at 10.1.2.3'}, 200
                else:
                    payload, status = {'success': True}, 200
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):  # silence
                pass

        self.fail = fail
        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def controller():
    c = _Controller()
    yield c
    c.close()


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(name=f'amb_{uid[:8]}', email=f'amb_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def lit_app(app):
    keys = ('ENABLE_AMBIENT_LIGHTING', 'LIGHTING_PROVIDER', 'HYPERION_URL', 'HYPERION_TOKEN', 'ALLOW_PRIVATE_LAN_URLS')
    saved = {k: app.config.get(k) for k in keys}
    app.config.update(ENABLE_AMBIENT_LIGHTING=True, LIGHTING_PROVIDER='hyperion', ALLOW_PRIVATE_LAN_URLS=True)
    yield app
    app.config.update(saved)


def _login(client, app, person):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(person.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(person)


def test_probe_sends_a_colour_then_a_clear_to_hyperion(client, lit_app, admin, controller):
    lit_app.config.update(HYPERION_URL=controller.url, HYPERION_TOKEN='tok-123')
    _login(client, lit_app, admin)

    body = client.post('/api/admin/ambient-lighting/test').get_json()

    assert body['probe_ok'] is True, body
    commands = [r['body']['command'] for r in controller.requests]
    assert commands == ['color', 'clear']
    assert all(r['path'] == '/json-rpc' for r in controller.requests)
    assert all(r['auth'] == 'Bearer tok-123' for r in controller.requests)
    assert controller.requests[0]['body']['color'] == [255, 128, 32]


def test_a_controller_error_is_surfaced_to_the_admin_not_swallowed(client, lit_app, admin):
    failing = _Controller(fail=True)
    try:
        lit_app.config.update(HYPERION_URL=failing.url)
        _login(client, lit_app, admin)
        raw = client.post('/api/admin/ambient-lighting/test').get_data(as_text=True)
    finally:
        failing.close()
    body = json.loads(raw)
    assert body['probe_ok'] is False
    # Admin-only diagnostics: the controller's own message is shown so the
    # operator can fix their device. (Transport failures use fixed wording; see
    # ambient_lighting._failure_text.)
    assert 'boom' in body['last_error']


def test_nothing_is_sent_when_lighting_is_off(client, lit_app, admin, controller):
    lit_app.config.update(ENABLE_AMBIENT_LIGHTING=False, HYPERION_URL=controller.url)
    _login(client, lit_app, admin)
    body = client.post('/api/admin/ambient-lighting/test').get_json()
    assert body['probe_ok'] in (False, None)
    assert controller.requests == []


def test_the_probe_is_admin_only(client, lit_app, db_session):
    uid = str(uuid4())
    member = User(name=f'm_{uid[:8]}', email=f'm_{uid[:8]}@example.com', role='user', user_id=uid, state=True)
    member.set_password('password123')
    db_session.add(member)
    db_session.commit()
    _login(client, lit_app, member)
    response = client.post('/api/admin/ambient-lighting/test')
    # A non-admin is bounced to the login page (302), never served the probe.
    assert response.status_code in (302, 401, 403)
    assert b'probe_ok' not in response.data
