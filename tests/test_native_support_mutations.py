from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.runtime_native.support_mutations import create_support_mutation_router


class FakeSupport:
    def __init__(self):
        self.created = None
        self.resolved = []

    def recent_count(self, _user_id, _cutoff):
        return 0

    def create(self, user, body, _now):
        self.created = (user.id, body)
        return {'id': 17, 'title': body['title'], 'status': 'open'}

    def resolve(self, ticket_id, admin_id, _now):
        self.resolved.append((ticket_id, admin_id))
        return {'id': ticket_id, 'status': 'resolved'} if ticket_id == 17 else None


def make_client(*, data=None, role='user'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-support-mutations-secret', TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role=role, is_active=True, state=True, is_authenticated=True, name='Member')
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_support_mutation_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('7:') else None,
        login_manager=manager, data_access=data or FakeSupport(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-support-mutations-secret'))
    return client


def test_member_support_ticket_creation_validates_rate_limit_and_envelope():
    data = FakeSupport()
    response = make_client(data=data).post('/api/support/tickets', json={
        'title': 'A useful report', 'area': 'themes', 'kind': 'issue',
        'severity': 'P2', 'body': 'Details here',
    })

    assert response.status_code == 201
    assert response.json()['ticket']['id'] == 17
    assert response.json()['ok'] is True
    assert data.created[0] == 7
    assert data.created[1]['title'] == 'A useful report'


def test_admin_resolve_is_scoped_and_not_found_is_explicit():
    data = FakeSupport()
    client = make_client(data=data, role='admin')
    response = client.post('/api/support/tickets/17/resolve')
    missing = client.post('/api/support/tickets/18/resolve')

    assert response.status_code == 200
    assert response.json()['ticket']['status'] == 'resolved'
    assert data.resolved == [(17, 7), (18, 7)]
    assert missing.status_code == 404
