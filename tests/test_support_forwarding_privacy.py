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
        status = 201
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
    preview = _json(support_client.post('/api/support/preview', json=payload))['preview']
    payload.update({key: preview[key] for key in ['preview_token', 'request_id']})
    response = support_client.post('/api/support/tickets', json=payload)
    assert response.status_code == 201
    saved = db_session.get(SupportTicket, _json(response)['ticket']['id'])
    assert saved.body == payload['body']
    assert saved.logs == payload['logs']
    assert len(captured_forwarding) == 1
    outbound = captured_forwarding[0]['title'] + '\n' + captured_forwarding[0]['body']
    assert all(value not in outbound for value in canaries)
    assert captured_forwarding[0]['title'] == preview['title']
    assert captured_forwarding[0]['body'] == preview['body']


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


def test_preview_is_redacted_and_does_not_create_or_forward(
    support_client, db_session, captured_forwarding,
):
    before = db_session.query(SupportTicket).count()
    payload = {'title': 'Preview api_key=SYNTHETIC_PREVIEW_KEY',
               'body': 'Contact synthetic.preview@example.invalid', 'sync_to_github': True}
    response = support_client.post('/api/support/preview', json=payload)
    assert response.status_code == 200
    data = _json(response)['preview']
    assert data['destination'] == 'example-owner/example-repo'
    assert data['visibility'] == 'unknown'
    assert data['redaction'] == 'mandatory'
    assert 'SYNTHETIC_PREVIEW_KEY' not in data['title']
    assert 'synthetic.preview@example.invalid' not in data['body']
    assert data['preview_token']
    assert db_session.query(SupportTicket).count() == before
    assert captured_forwarding == []


def test_opt_in_without_preview_cannot_forward(support_client, captured_forwarding):
    response = support_client.post('/api/support/tickets', json={
        'title': 'No preview', 'sync_to_github': True,
    })
    assert response.status_code == 409
    assert captured_forwarding == []


@pytest.mark.parametrize('change', ['body', 'request_id', 'destination', 'signature'])
def test_changed_report_or_destination_invalidates_preview(
    support_client, captured_forwarding, db_session, monkeypatch, change,
):
    payload = {'title': 'Approved text', 'body': 'Original', 'sync_to_github': True}
    preview = _json(support_client.post('/api/support/preview', json=payload))['preview']
    payload.update({key: preview[key] for key in ['preview_token', 'request_id']})
    before = db_session.query(SupportTicket).count()
    if change == 'body': payload['body'] = 'Changed after preview'
    if change == 'request_id': payload['request_id'] = str(uuid4())
    if change == 'destination': monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'another-owner/another-repo')
    if change == 'signature': payload['preview_token'] += 'tampered'
    response = support_client.post('/api/support/tickets', json=payload)
    assert response.status_code == 409
    assert captured_forwarding == []
    assert db_session.query(SupportTicket).count() == before


@pytest.mark.parametrize('configuration', ['missing', 'invalid'])
def test_unavailable_forwarding_does_not_block_local_reporting(
    support_client, captured_forwarding, monkeypatch, configuration,
):
    if configuration == 'missing': monkeypatch.delenv('SUPPORT_GITHUB_TOKEN')
    else: monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'owner/repo?token=SYNTHETIC_INVALID_CONFIG')
    payload = {'title': 'Still useful locally'}
    response = support_client.post('/api/support/preview', json=payload)
    assert response.status_code == 200
    preview = _json(response)['preview']
    assert preview['available'] is False
    assert preview['preview_token'] is None
    assert 'SYNTHETIC_INVALID_CONFIG' not in json.dumps(preview)
    assert support_client.post('/api/support/tickets', json=payload).status_code == 201
    assert captured_forwarding == []


def test_preview_approval_is_account_bound_and_expires(captured_forwarding, monkeypatch):
    from oneirodex.utils.support_reports import preview_support_report, valid_support_preview
    from itsdangerous.timed import TimestampSigner
    user = SimpleNamespace(id=701, role='user')
    payload = {'title': 'Account-bound preview'}
    preview = preview_support_report(user, payload, 'synthetic-preview-signing-key')
    payload.update({key: preview[key] for key in ['preview_token', 'request_id']})
    assert valid_support_preview(user, payload, 'synthetic-preview-signing-key')
    assert not valid_support_preview(SimpleNamespace(id=702, role='user'), payload, 'synthetic-preview-signing-key')
    original = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: original(self) + 901)
    assert not valid_support_preview(user, payload, 'synthetic-preview-signing-key')
    assert captured_forwarding == []


def test_sender_rechecks_approved_destination_at_final_sink(captured_forwarding):
    from oneirodex.utils.github_issues import create_github_issue
    result = create_github_issue(title='Approved', body='Approved', expected_repository='old-owner/old-repo')
    assert result['ok'] is False
    assert result['skipped'] is True
    assert captured_forwarding == []


def test_preview_has_no_raw_override(support_client, captured_forwarding):
    response = support_client.post('/api/support/preview', json={
        'title': 'Do not bypass', 'redaction': 'disabled',
    })
    assert response.status_code == 422
    assert captured_forwarding == []


def test_preview_requires_csrf_when_enabled(support_client, captured_forwarding, app):
    app.config['WTF_CSRF_ENABLED'] = True
    response = support_client.post('/api/support/preview', json={'title': 'No CSRF'})
    assert response.status_code == 400
    assert captured_forwarding == []


def test_repeated_approved_request_returns_one_ticket_and_one_external_issue(
    support_client, captured_forwarding,
):
    payload = {'title': 'Same approved request', 'body': 'Retry after a lost response',
               'sync_to_github': True}
    preview = _json(support_client.post('/api/support/preview', json=payload))['preview']
    payload.update({key: preview[key] for key in ['preview_token', 'request_id']})
    first = support_client.post('/api/support/tickets', json=payload)
    second = support_client.post('/api/support/tickets', json=payload)
    assert first.status_code == second.status_code == 201
    assert _json(first)['ticket']['id'] == _json(second)['ticket']['id']
    assert len(captured_forwarding) == 1


def test_repeated_local_request_preserves_one_local_receipt(support_client, captured_forwarding):
    payload = {'title': 'Local request receipt', 'request_id': str(uuid4())}
    first = support_client.post('/api/support/tickets', json=payload)
    second = support_client.post('/api/support/tickets', json=payload)
    assert first.status_code == second.status_code == 201
    assert _json(first)['ticket']['id'] == _json(second)['ticket']['id']
    assert captured_forwarding == []


def test_lost_provider_response_is_uncertain_and_replay_does_not_resend(
    support_client, captured_forwarding, monkeypatch,
):
    import urllib.error
    import oneirodex.utils.github_issues as github
    intercept = github._open_github_request
    def lose_response(request, *, timeout):
        intercept(request, timeout=timeout)
        raise urllib.error.URLError('Synthetic response lost after provider accepted request')
    monkeypatch.setattr(github, '_open_github_request', lose_response)
    payload = {'title': 'Uncertain provider receipt', 'sync_to_github': True}
    preview = _json(support_client.post('/api/support/preview', json=payload))['preview']
    payload.update({key: preview[key] for key in ['preview_token', 'request_id']})
    first = support_client.post('/api/support/tickets', json=payload)
    assert first.status_code == 201
    assert _json(first)['ticket']['github_sync'] == 'unknown'
    second = support_client.post('/api/support/tickets', json=payload)
    assert second.status_code == 201
    assert _json(first)['ticket']['id'] == _json(second)['ticket']['id']
    assert len(captured_forwarding) == 1


def test_replay_reference_rejects_changed_contents(support_client, captured_forwarding):
    payload = {'title': 'Original local report', 'request_id': str(uuid4())}
    assert support_client.post('/api/support/tickets', json=payload).status_code == 201
    payload['title'] = 'Different report reusing the same reference'
    assert support_client.post('/api/support/tickets', json=payload).status_code == 409
    assert captured_forwarding == []


def test_existing_receipt_remains_readable_after_new_report_limit(support_client, captured_forwarding):
    payload = {'title': 'Original local receipt', 'request_id': str(uuid4())}
    first = support_client.post('/api/support/tickets', json=payload)
    assert first.status_code == 201
    for index in range(4):
        assert support_client.post('/api/support/tickets', json={'title': f'Other {index}'}).status_code == 201
    assert support_client.post('/api/support/tickets', json={'title': 'New sixth'}).status_code == 429
    replay = support_client.post('/api/support/tickets', json=payload)
    assert replay.status_code == 201
    assert _json(replay)['ticket']['id'] == _json(first)['ticket']['id']
    assert captured_forwarding == []
