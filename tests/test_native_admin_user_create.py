from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_user_create import create_admin_user_create_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeUserCreate:
    def __init__(self):
        self.calls = []
        self.error = None

    def create(self, body, actor):
        self.calls.append((body, actor.id))
        if self.error:
            return None, self.error
        return {'user': {
            'id': 31, 'name': body.get('username'), 'email': body.get('email') or None,
            'has_email': bool(body.get('email')), 'role': body.get('role', 'user'),
        }}, None


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-user-create-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint', name='Admin',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeUserCreate()
    router = create_admin_user_create_router(
        flask_app, find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, csrf


def test_create_user_requires_csrf_and_preserves_success_projection():
    denied_client, denied_data, _ = _client()
    denied = denied_client.put('/admin/api/user/0', json={'username': 'living-room'})
    assert denied.status_code == 400 and denied_data.calls == []

    client, data, csrf = _client()
    response = client.put(
        '/admin/api/user/0',
        json={
            'username': 'living-room', 'email': '', 'password': 'household password',
            'role': 'user', 'state': True,
        },
        headers={'X-CSRFToken': csrf},
    )
    assert response.status_code == 200
    assert response.json()['user']['id'] == 31
    assert response.json()['ok'] is True
    assert len(data.calls) == 1 and data.calls[0][1] == 18


def test_create_user_validation_and_admin_gate_do_not_create():
    client, data, csrf = _client()
    data.error = ('Username is required', 'bad_request', None)
    invalid = client.put(
        '/admin/api/user/0', json={'username': 'living-room'}, headers={'X-CSRFToken': csrf},
    )
    assert invalid.status_code == 400 and invalid.json()['error_code'] == 'bad_request'
    assert len(data.calls) == 1

    member_client, member_data, member_csrf = _client(role='user')
    denied = member_client.put(
        '/admin/api/user/0', json={'username': 'living-room'},
        headers={'X-CSRFToken': member_csrf}, follow_redirects=False,
    )
    assert denied.status_code == 302 and member_data.calls == []


def test_user_create_adapter_enforces_emailless_rules_and_database_uniqueness(monkeypatch):
    import oneirodex
    from oneirodex.models import User
    from oneirodex.runtime_native.admin_user_create import AdminUserCreateData
    from oneirodex.utils import event_logging

    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    created_rows = []
    session.add.side_effect = lambda row: (setattr(row, 'id', 77), created_rows.append(row))
    monkeypatch.setattr(oneirodex, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(User, 'set_password', lambda user, password: setattr(user, '_password_input', password))
    monkeypatch.setattr(event_logging, 'log_system_event', Mock(return_value=True))

    actor = SimpleNamespace(id=18, name='Admin')
    payload, error = AdminUserCreateData().create({
        'username': 'Living.Room', 'email': '', 'password': 'household password',
        'role': 'user', 'state': True, 'is_email_verified': True,
    }, actor)

    assert error is None
    assert payload['user'] == {
        'id': 77, 'name': 'Living.Room', 'email': None, 'has_email': False, 'role': 'user',
    }
    assert created_rows[0].email.endswith('@no-email.invalid')
    assert created_rows[0].is_email_verified is False
    assert created_rows[0]._password_input == 'household password'
    assert event_logging.log_system_event.call_args.kwargs['audit_user'] == actor.id

    rejected, error = AdminUserCreateData().create({
        'username': 'system', 'email': '', 'password': 'household password',
    }, actor)
    assert rejected is None and error[1] == 'bad_request'
    assert session.execute.call_count == 2


def test_native_user_create_adapter_persists_emailless_account(db_session):
    from uuid import uuid4

    from oneirodex import db
    from oneirodex.models import User
    from oneirodex.runtime_native.admin_user_create import AdminUserCreateData

    actor = User(
        name=f'native_create_admin_{uuid4().hex[:8]}',
        email=f'{uuid4().hex}@example.org', role='admin', state=True,
        is_email_verified=True, user_id=str(uuid4()),
    )
    actor.set_password('long enough test password')
    db_session.add(actor)
    db_session.flush()
    payload, error = AdminUserCreateData().create({
        'username': f'living_room_{uuid4().hex[:6]}', 'email': '',
        'password': 'household test password', 'role': 'user',
        'state': True, 'is_email_verified': True,
    }, actor)

    assert error is None
    assert payload['user']['has_email'] is False
    created = db.session.get(User, payload['user']['id'])
    assert created.email.endswith('@no-email.invalid')
    assert created.is_email_verified is False
    assert created.check_password('household test password')
