from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_newsletters import create_admin_newsletters_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeNewsletterData:
    def __init__(self, *, result=None):
        self.result = result or ({'newsletter': {'status': 'sent'}, 'failed_count': 0}, None, None)
        self.calls = []
        self.rollbacks = 0

    def send(self, subject, content, recipients, user):
        self.calls.append((subject, content, recipients, user.id))
        return self.result

    def rollback(self):
        self.rollbacks += 1


def _client(data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-newsletter-form-secret',
        WTF_CSRF_ENABLED=True,
        SESSION_COOKIE_NAME='session',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=4, role='admin', is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fp',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in.', login_message_category='message',
        session_protection='basic',
    )
    adapter = data or FakeNewsletterData()
    app = FastAPI()
    app.include_router(create_admin_newsletters_router(
        flask_app,
        find_user=lambda value: user if value == 4 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('4:') else None,
        login_manager=manager,
        data_access=adapter,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(app)
    session = {'_user_id': '4:fp', '_fresh': True}
    client.csrf_token = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.adapter = adapter
    return client


def test_legacy_newsletter_form_sends_through_adapter_and_redirects():
    client = _client()
    response = client.post(
        '/admin/newsletter',
        data={
            'csrf_token': client.csrf_token,
            'subject': 'Household update',
            'content': 'A short update.',
            'recipients': 'one@example.test, two@example.test',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/newsletter'
    assert client.adapter.calls == [(
        'Household update', 'A short update.',
        ['one@example.test', 'two@example.test'], 4,
    )]


def test_legacy_newsletter_form_requires_csrf_and_valid_fields():
    client = _client()
    denied = client.post('/admin/newsletter', data={
        'subject': 'Household update', 'content': 'A short update.',
        'recipients': 'one@example.test',
    })
    invalid = client.post('/admin/newsletter', data={
        'csrf_token': client.csrf_token, 'subject': '', 'content': 'A short update.',
        'recipients': 'one@example.test',
    }, follow_redirects=False)

    assert denied.status_code == 400
    assert invalid.status_code == 302
    assert client.adapter.calls == []
