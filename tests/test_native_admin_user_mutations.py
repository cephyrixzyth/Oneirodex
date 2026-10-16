from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_user_mutations import create_admin_user_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeUserMutations:
    def __init__(self):
        self.calls = []

    def update(self, user_id, body, actor_id):
        self.calls.append(('update', user_id, body, actor_id))
        return {}, None, bool(body.get('password'))

    def delete(self, user_id, actor_id):
        self.calls.append(('delete', user_id, actor_id))
        return {}, None


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-user-mutation-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint', name='Admin',
        get_id=lambda: '18:fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeUserMutations()
    router = create_admin_user_mutation_router(
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


def test_user_update_and_delete_require_csrf_and_preserve_native_dispatch():
    client, data, csrf = _client()
    denied_update = client.put('/admin/api/user/42', json={'about': 'child account'})
    denied_delete = client.delete('/admin/api/user/42')
    assert denied_update.status_code == 400
    assert denied_delete.status_code == 400
    assert data.calls == []

    updated = client.put(
        '/admin/api/user/42', json={'about': 'child account'},
        headers={'X-CSRFToken': csrf},
    )
    deleted = client.delete('/admin/api/user/42', headers={'X-CSRFToken': csrf})
    assert updated.status_code == 200 and updated.json()['ok'] is True
    assert deleted.status_code == 200 and deleted.json()['ok'] is True
    assert data.calls == [
        ('update', 42, {'about': 'child account'}, 18), ('delete', 42, 18),
    ]


def test_user_mutations_reject_non_admin_before_data_access():
    client, data, csrf = _client(role='user')
    response = client.put(
        '/admin/api/user/42', json={'about': 'child account'},
        headers={'X-CSRFToken': csrf}, follow_redirects=False,
    )
    assert response.status_code == 302
    assert data.calls == []


def test_admin_changing_own_password_refreshes_session_and_remember_cookie():
    client, data, csrf = _client()
    response = client.put(
        '/admin/api/user/18', json={'password': 'a new household password'},
        headers={'X-CSRFToken': csrf},
    )
    assert response.status_code == 200
    assert any(call[0] == 'update' for call in data.calls)
    assert 'remember_token=' in response.headers.get('set-cookie', '')


def _persist_admin(db_session, name):
    from oneirodex.models import User

    user = User(
        name=f'{name}_{uuid4().hex[:10]}', email=f'{uuid4().hex}@example.org',
        role='admin', state=True, is_email_verified=True, user_id=str(uuid4()),
    )
    user.set_password('long enough test password')
    db_session.add(user)
    db_session.flush()
    return user


def test_native_mutation_adapter_preserves_last_active_admin_guard(db_session):
    from oneirodex import db
    from oneirodex.models import User
    from oneirodex.runtime_native.admin_user_mutations import AdminUserMutationData

    sentinel = User(
        name=f'native_sentinel_{uuid4().hex[:10]}', email=f'{uuid4().hex}@example.org',
        role='user', state=True, is_email_verified=True, user_id=str(uuid4()),
    )
    sentinel.set_password('long enough test password')
    db_session.add(sentinel)
    db_session.flush()
    admin = _persist_admin(db_session, 'native_only_admin')
    adapter = AdminUserMutationData()

    payload, error, refresh = adapter.update(admin.id, {'state': False}, admin.id)
    assert payload is None and error[:2] == (
        'Cannot modify the last active admin account', 'forbidden',
    )
    assert refresh is False
    db.session.refresh(admin)
    assert admin.role == 'admin' and admin.state is True

    payload, error = adapter.delete(admin.id, admin.id)
    assert payload is None and error[:2] == ('Cannot modify the last active admin account', 'forbidden')
    db.session.refresh(admin)
    assert admin.role == 'admin' and admin.state is True


def test_native_mutation_adapter_allows_deactivation_when_another_admin_remains(db_session):
    from oneirodex import db
    from oneirodex.runtime_native.admin_user_mutations import AdminUserMutationData

    actor = _persist_admin(db_session, 'native_admin_actor')
    target = _persist_admin(db_session, 'native_admin_target')

    payload, error, refresh = AdminUserMutationData().update(
        target.id, {'state': False}, actor.id,
    )
    assert error is None and payload == {} and refresh is False
    db.session.refresh(target)
    assert target.state is False
