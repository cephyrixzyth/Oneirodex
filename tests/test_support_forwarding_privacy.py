"""Support forwarding must redact external fields while preserving local-only reports."""
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.models import SupportTicket, User
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.runtime_native.support_mutations import create_support_mutation_router


@pytest.fixture
def reporter(db_session):
    user = User(name='privacy-' + uuid4().hex[:8], email=uuid4().hex + '@example.invalid',
                password_hash='unused', role='user', user_id=str(uuid4()), invite_quota=0)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(params=['flask', 'native'])
def support_client(request, app, client, reporter, db_session, monkeypatch):
    if request.param == 'flask':
        with client.session_transaction() as session:
            session['_user_id'] = str(reporter.id)
            session['_fresh'] = True
        return client
    import oneirodex.runtime_native.db_session as native_session
    # Keep the production data adapter and ORM logic, with the owned PG test session.
    monkeypatch.setattr(native_session, 'native_db', SimpleNamespace(session=db_session))
    user = SimpleNamespace(id=reporter.id, role='user', is_active=True, state=True,
                           is_authenticated=True, name='Synthetic reporter')
    manager = SimpleNamespace(login_view='login.login', blueprint_login_views={},
                              login_message='Please log in.', login_message_category='message',
                              localize_callback=None, session_protection='basic')
    native = FastAPI()
    native.include_router(create_support_mutation_router(
        app, find_user=lambda value: user if value == reporter.id else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith(f'{reporter.id}:') else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
    ))
    native_client = TestClient(native)
    native_client.cookies.set('session', dump_session_cookie(
        {'_user_id': f'{reporter.id}:fixture'}, app.config['SECRET_KEY']))
    return native_client


def _json(response):
    return response.get_json() if hasattr(response, 'get_json') else response.json()


@pytest.fixture
def captured_forwarding(monkeypatch):
    import oneirodex.utils.github_issues as github
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator-credential-not-transmitted')
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'example-owner/example-repo')
    captured = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1):
            return b'{"number":701,"html_url":"https://github.com/example-owner/example-repo/issues/701"}'[:size]

    def intercept(request, *, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(github, '_open_github_request', intercept)
    return captured


def test_external_payload_redacts_synthetic_secrets_and_personal_context(
    support_client, db_session, captured_forwarding,
):
    canaries = ['gt_0123abcd_SYNTHETIC_SECRET_0123456789',
                'SYNTHETIC_QUERY_SECRET_0123456789',
                'synthetic.reporter@example.invalid',
                r'C:\Users\SyntheticReporter\fixture\client.log',
                'SYNTHETIC_TITLE_KEY_0123456789']
    payload = {
        'title': 'Fixture api_key=' + canaries[4],
        'body': 'Synthetic Authorization: Bearer ' + canaries[0],
        'url_hint': 'https://fixture.invalid/route?access_token=' + canaries[1],
        'logs': 'Email ' + canaries[2] + '\nPath ' + canaries[3],
        'sync_to_github': True,
    }
    response = support_client.post('/api/support/tickets', json=payload)
    assert response.status_code == 201
    saved = db_session.get(SupportTicket, _json(response)['ticket']['id'])
    assert saved.body == payload['body']
    assert saved.logs == payload['logs']
    assert len(captured_forwarding) == 1
    outbound = captured_forwarding[0]['title'] + '\n' + captured_forwarding[0]['body']
    assert all(value not in outbound for value in canaries)


def test_local_only_report_never_reaches_external_http(
    support_client, db_session, captured_forwarding,
):
    response = support_client.post('/api/support/tickets', json={
        'title': 'Keep local', 'body': 'Synthetic private report',
    })
    assert response.status_code == 201
    saved = db_session.get(SupportTicket, _json(response)['ticket']['id'])
    assert saved.body == 'Synthetic private report'
    assert saved.github_sync == 'local_only'
    assert captured_forwarding == []


@pytest.mark.parametrize(('text', 'private'), [
    ('Authorization: Basic SYNTHETIC_BASIC', 'SYNTHETIC_BASIC'),
    ('{"api_key": "SYNTHETIC_QUOTED"}', 'SYNTHETIC_QUOTED'),
    ('CLIENT_SECRET = \'SYNTHETIC_ENV\'', 'SYNTHETIC_ENV'),
    ('Cookie: session=SYNTHETIC_COOKIE; preference=dark', 'SYNTHETIC_COOKIE'),
    ('https://fixture.invalid/?%61ccess_token=SYNTHETIC_ENCODED', 'SYNTHETIC_ENCODED'),
    ('https://fixture.invalid/?ACCESS_TOKEN=SYNTHETIC_CASE', 'SYNTHETIC_CASE'),
    ('https://fixture.invalid/#token=SYNTHETIC_FRAGMENT', 'SYNTHETIC_FRAGMENT'),
    ('https://name:SYNTHETIC_PASSWORD@fixture.invalid/path', 'SYNTHETIC_PASSWORD'),
    ('https://[bad/?token=SYNTHETIC_MALFORMED', 'SYNTHETIC_MALFORMED'),
    ('-----BEGIN PRIVATE KEY-----\nSYNTHETIC_PEM\n-----END PRIVATE KEY-----', 'SYNTHETIC_PEM'),
    ('-----BEGIN RSA PRIVATE KEY-----\nSYNTHETIC_TRUNCATED_PEM', 'SYNTHETIC_TRUNCATED_PEM'),
    ('ghp_SYNTHETIC_BARE_PAT_0123456789', 'ghp_SYNTHETIC_BARE_PAT_0123456789'),
    ('/home/SyntheticReporter/fixture/client.log', 'SyntheticReporter'),
    ('/Users/SyntheticReporter/fixture/client.log', 'SyntheticReporter'),
    ('synthetic-operator-credential-not-transmitted', 'synthetic-operator-credential-not-transmitted'),
    ('{"refreshToken":"SYNTHETIC_CAMEL_TOKEN"}', 'SYNTHETIC_CAMEL_TOKEN'),
    ('{"Cookie":"session=SYNTHETIC_JSON_COOKIE"}', 'SYNTHETIC_JSON_COOKIE'),
    ('{"password":"SYNTHETIC_ESCAPED\\\"quote"}', 'SYNTHETIC_ESCAPED'),
    ('password="first segment SYNTHETIC_TRUNCATED_VALUE', 'SYNTHETIC_TRUNCATED_VALUE'),
    ('Authorization: Bearer\n\tSYNTHETIC_FOLDED_HEADER', 'SYNTHETIC_FOLDED_HEADER'),
    ('postgresql://user:SYNTHETIC_DATABASE_PASSWORD@fixture.invalid/db', 'SYNTHETIC_DATABASE_PASSWORD'),
])
def test_shared_sender_has_no_raw_title_or_body_bypass(text, private, captured_forwarding):
    from oneirodex.utils.github_issues import create_github_issue
    result = create_github_issue(title=text, body=text)
    assert result['ok'] is True
    outgoing = captured_forwarding[0]
    assert private not in outgoing['title']
    assert private not in outgoing['body']


def test_shared_sender_preserves_useful_diagnostics(captured_forwarding):
    from oneirodex.utils.github_issues import create_github_issue
    text = 'HTTP 403 /api/library; token_count=12; dark theme; https://example.invalid/docs'
    assert create_github_issue(title=text, body=text)['ok'] is True
    assert captured_forwarding[0]['title'] == text
    assert captured_forwarding[0]['body'] == text


def test_redaction_is_stable_when_preview_and_final_sender_filter_again():
    from oneirodex.utils.support_privacy import redact_support_text
    text = 'api_key=private\n{"password":"private"}\nhttps://name:private@fixture.invalid/?token=private'
    once = redact_support_text(text)
    assert redact_support_text(once) == once
