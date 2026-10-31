from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def test_support_ticket_serializes_database_timestamps_as_explicit_utc():
    from oneirodex.models import SupportTicket

    stored_utc = datetime(2026, 10, 31, 3, 0)
    stored_offset_time = datetime(2026, 10, 31, 8, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    ticket = SupportTicket(
        id=17, user_id=7, title='Synthetic report', body='',
        created_at=stored_utc, resolved_at=stored_offset_time,
    )

    result = ticket.to_dict()

    assert result['created_at'] == '2026-10-31T03:00:00+00:00'
    assert result['resolved_at'] == '2026-10-31T03:00:00+00:00'


def test_admin_resolve_is_scoped_and_not_found_is_explicit():
    data = FakeSupport()
    client = make_client(data=data, role='admin')
    response = client.post('/api/support/tickets/17/resolve')
    missing = client.post('/api/support/tickets/18/resolve')

    assert response.status_code == 200
    assert response.json()['ticket']['status'] == 'resolved'
    assert data.resolved == [(17, 7), (18, 7)]
    assert missing.status_code == 404


def test_admin_scoped_bearer_can_resolve_but_unscoped_or_member_cannot(monkeypatch):
    from oneirodex.runtime_native import support_mutations

    data = FakeSupport()
    admin = SimpleNamespace(id=7, role='admin')
    member = SimpleNamespace(id=8, role='user')

    def resolve_auth(request, *_args, **_kwargs):
        bearer = request.headers.get('authorization')
        if bearer == 'Bearer scoped-admin':
            return SimpleNamespace(user=admin, token=object(), has_scope=lambda scope: scope == 'admin', should_set_session_cookie=False)
        if bearer == 'Bearer unscoped-admin':
            return SimpleNamespace(user=admin, token=object(), has_scope=lambda _scope: False, should_set_session_cookie=False)
        if bearer == 'Bearer member-admin-scope':
            return SimpleNamespace(user=member, token=object(), has_scope=lambda scope: scope == 'admin', should_set_session_cookie=False)
        return SimpleNamespace(user=None, token=None, has_scope=lambda _scope: False, should_set_session_cookie=False)

    monkeypatch.setattr(support_mutations, 'request_auth_context', resolve_auth)
    app = FastAPI()
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-support-mutations-secret', TESTING=True, WTF_CSRF_ENABLED=False)
    app.include_router(create_support_mutation_router(
        flask_app, find_user=lambda _value: None, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None, load_user_id=None,
        login_manager=None, data_access=data,
    ))
    client = TestClient(app)

    allowed = client.post('/api/support/tickets/17/resolve', headers={'Authorization': 'Bearer scoped-admin'})
    unscoped = client.post('/api/support/tickets/17/resolve', headers={'Authorization': 'Bearer unscoped-admin'})
    member = client.post('/api/support/tickets/17/resolve', headers={'Authorization': 'Bearer member-admin-scope'})
    create = client.post('/api/support/tickets', json={'title': 'Not allowed'}, headers={'Authorization': 'Bearer scoped-admin'})

    assert allowed.status_code == 200
    assert unscoped.status_code == 403
    assert member.status_code == 403
    assert create.status_code == 403
    assert data.created is None
    assert data.resolved == [(17, 7)]
