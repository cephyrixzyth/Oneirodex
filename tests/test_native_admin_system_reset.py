from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.product import RESET_CONFIRM_PHRASE
from oneirodex.runtime_native.admin_system_reset import create_admin_system_reset_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeReset:
    scopes = {'catalog': ('games',), 'users': ('users',)}

    def __init__(self):
        self.calls = []

    def plan(self, scopes):
        self.calls.append(('plan', list(scopes)))
        return {'scopes': list(scopes), 'tables': ['games'], 'touches_files': False}

    def expand(self, scopes):
        return list(scopes)

    def perform(self, scopes, **kwargs):
        self.calls.append(('perform', list(scopes), kwargs))
        return {'scopes': list(scopes), 'performed': True, 'actor_restored': False}


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-system-reset', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=7, user_id='admin', role=role, state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '7:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    reset = FakeReset()
    events = []
    app = FastAPI()
    app.include_router(create_admin_system_reset_router(
        flask_app,
        find_user=lambda uid: user if uid == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager,
        database_scope=lambda _app: nullcontext(),
        reset_service=reset,
        event_logger=lambda *args, **kwargs: events.append((args, kwargs)),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, reset, events


def test_reset_preview_lists_damage_without_performing_it():
    client, reset, events = _client()
    response = client.post('/admin/api/system/reset', json={'scopes': ['catalog']})
    assert response.status_code == 200
    assert response.json()['performed'] is False
    assert response.json()['touches_files'] is False
    assert reset.calls == [('plan', ['catalog'])]
    assert events == []


def test_reset_requires_valid_scopes_and_exact_confirmation_phrase():
    client, reset, events = _client()
    invalid_scope = client.post('/admin/api/system/reset', json={'scopes': ['unknown']})
    invalid_phrase = client.post(
        '/admin/api/system/reset', json={'scopes': ['catalog'], 'confirm': 'wrong'},
    )
    assert invalid_scope.status_code == 400
    assert invalid_scope.json()['detail']['valid_scopes'] == ['catalog', 'users']
    assert invalid_phrase.status_code == 422
    assert reset.calls == [] and events == []


def test_reset_confirm_uses_fake_transaction_adapter_and_records_actor():
    client, reset, events = _client()
    response = client.post('/admin/api/system/reset', json={
        'scopes': ['users'], 'confirm': RESET_CONFIRM_PHRASE,
    })
    assert response.status_code == 200 and response.json()['performed'] is True
    assert reset.calls == [('perform', ['users'], {'actor_user_id': 7})]
    assert events[0][1]['audit_user'] == 7


def test_reset_rejects_missing_csrf_without_calling_reset_service():
    client, reset, _events = _client()
    response = client.post(
        '/admin/api/system/reset', json={'scopes': ['catalog']},
        headers={'X-CSRFToken': ''},
    )
    assert response.status_code == 400
    assert reset.calls == []
