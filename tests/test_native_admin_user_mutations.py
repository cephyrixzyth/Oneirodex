from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, Response

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
    flask_app.config.update(
        SECRET_KEY='native-user-mutation-secret', CSP_ENABLED=False, TESTING=True,
    )
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


def test_authenticated_native_admin_route_deletes_child_and_anonymizes_audit(app):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from oneirodex import db
    from oneirodex.models import SystemEvents, User
    from oneirodex.runtime_native.admin_user_mutations import AdminUserMutationData
    from oneirodex.runtime_native.db_session import native_session_scope

    suffix = uuid4().hex[:10]
    admin = User(
        name=f'native_route_admin_{suffix}', email=f'{suffix}-admin@example.org',
        role='admin', state=True, is_email_verified=True, user_id=str(uuid4()),
    )
    child = User(
        name=f'native_route_child_{suffix}', email=f'{suffix}-child@example.org',
        role='child', state=True, is_email_verified=True, user_id=str(uuid4()),
    )
    admin.set_password('long enough test password')
    child.set_password('long enough test password')
    audit = None

    with app.app_context():
        engine = db.engine
        with Session(engine) as setup:
            setup.add_all([admin, child])
            setup.flush()
            audit = SystemEvents(
                event_type='audit',
                event_text=(f'{child.name} ({child.email}) accessed '
                            r'C:\Users\private\child-save.sav'),
                event_level='information',
                audit_user=child.id,
            )
            setup.add(audit)
            setup.commit()
            admin_id, child_id, audit_id = admin.id, child.id, audit.id

        flask_app = app
        flask_app.config['TESTING'] = True
        manager = SimpleNamespace(
            login_view='login.login', blueprint_login_views={},
            login_message='Please log in to access this page.',
            login_message_category='message', localize_callback=None,
            session_protection='basic',
        )
        identity = f'{admin_id}:native-test-fingerprint'
        session_data = {'_user_id': identity, '_fresh': True}
        router = create_admin_user_mutation_router(
            flask_app,
            find_user=lambda user_id: admin if user_id == admin_id else None,
            find_token=lambda _prefix: None,
            commit_token_touch=lambda _token: None,
            load_user_id=lambda value: admin if value == identity else None,
            login_manager=manager,
            database_scope=lambda current_app: native_session_scope(current_app, db),
            data_access=AdminUserMutationData(),
        )
        runtime = FastAPI()
        runtime.include_router(router)
        client = TestClient(runtime)
        csrf = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
        client.cookies.set('session', dump_session_cookie(
            session_data, flask_app.config['SECRET_KEY'],
        ))

        try:
            response = client.delete(
                f'/admin/api/user/{child_id}', headers={'X-CSRFToken': csrf},
            )
            assert response.status_code == 200, response.text
            with Session(engine) as check:
                assert check.get(User, child_id) is None
                retained = check.get(SystemEvents, audit_id)
                assert retained is not None
                assert retained.audit_user is None
                assert child.name not in retained.event_text
                assert child.email not in retained.event_text
                assert r'C:\Users\private\child-save.sav' not in retained.event_text
        finally:
            client.close()
            with Session(engine) as cleanup:
                cleanup.execute(delete(SystemEvents).where(
                    (SystemEvents.id == audit_id) | (SystemEvents.audit_user == admin_id)
                ))
                cleanup.execute(delete(User).where(User.id.in_([admin_id, child_id])))
                cleanup.commit()


def test_admin_user_mutation_rejects_oversized_json_body_before_data_access():
    client, data, csrf = _client()
    response = client.put(
        '/admin/api/user/42', content=b' ' * (64 * 1024 + 1),
        headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
    )
    assert response.status_code == 413
    assert response.json()['error_code'] == 'payload_too_large'
    assert data.calls == []


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


def test_admin_remember_cookie_duration_cannot_exceed_thirty_days():
    from oneirodex.runtime_native.admin_user_mutations import _write_remember_cookie

    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-user-mutation-secret', TESTING=True,
        REMEMBER_COOKIE_DURATION=timedelta(days=90),
    )
    response = Response()
    before = datetime.now(timezone.utc)

    _write_remember_cookie(
        response,
        flask_app,
        {'_user_id': '18:fingerprint', '_remember_seconds': 60 * 60 * 24 * 60},
    )

    cookies = SimpleCookie()
    cookies.load(response.headers['set-cookie'])
    expires = parsedate_to_datetime(cookies['remember_token']['expires'])
    assert before + timedelta(days=29, hours=23) <= expires
    assert expires <= before + timedelta(days=30, minutes=1)


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


@pytest.mark.parametrize(('field', 'value', 'message'), [
    ('denied_genres', ['genre'] * 101, 'denied_genres cannot contain more than 100 values'),
    ('denied_themes', ['x' * 51], 'denied_themes values cannot exceed 50 characters'),
    ('denied_genres', [42], 'denied_genres values must be strings'),
])
def test_content_filters_are_bounded_before_admin_database_mutation(field, value, message):
    from oneirodex.runtime_native.admin_user_mutations import AdminUserMutationData

    payload, error, refresh = AdminUserMutationData().update(999, {field: value}, 999)
    assert payload is None
    assert error[:2] == (message, 'bad_request')
    assert refresh is False
