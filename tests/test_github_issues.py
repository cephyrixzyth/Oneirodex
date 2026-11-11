"""GitHub Issues helper + support ticket create (token missing → skipped)."""

import io
import json
from unittest.mock import patch

import pytest
import urllib.error
import urllib.request

from oneirodex.utils.github_issues import (
    _GitHubRedirectHandler,
    _open_github_request,
    build_issue_body,
    create_github_issue,
    support_github_config,
    read_support_issue,
)


@pytest.mark.parametrize('change', [
    {'number': True}, {'number': 702}, {'html_url': 'https://fixture.invalid/issues/701'},
    {'html_url': 'https://github.com/example/repo/issues/701?private=value'},
    {'pull_request': {}}, {'title': None}, {'body': []}, {'status': 201}, {'oversized': True},
    {'invalid_json': True}, {'status': 302}, {'exception': 404}, {'exception': 403}, {'exception': 500},
    {},
])
def test_readonly_issue_lookup_checks_fixed_origin_and_hides_invalid_provider_data(change, monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator')
    # Reconciliation checks the retained attempt destination, even after config changes.
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'different/repo')
    class Response:
        status = change.get('status', 200)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1):
            if change.get('oversized'): return b'x' * size
            if change.get('invalid_json'): return b'not-json PRIVATE_PROVIDER_BODY'
            return json.dumps({'number': 701, 'html_url': 'https://github.com/example/repo/issues/701',
                               'title': 'Exact', 'body': 'Exact', **change}).encode()[:size]
    def intercept(request, *, timeout):
        assert request.get_method() == 'GET' and request.data is None
        assert request.full_url == 'https://api.github.com/repos/example/repo/issues/701'
        assert timeout == 20
        if 'exception' in change:
            raise urllib.error.HTTPError(request.full_url, change['exception'], 'private', {}, io.BytesIO(b'PRIVATE_PROVIDER_BODY'))
        return Response()
    with patch('oneirodex.utils.github_issues._open_github_request', side_effect=intercept):
        result = read_support_issue(repository='example/repo', issue_number=701)
    if change:
        assert result is None
    else:
        assert result == {'number': 701, 'html_url': 'https://github.com/example/repo/issues/701', 'title': 'Exact', 'body': 'Exact'}


@pytest.mark.parametrize('receipt', [
    {}, [], {'number': True, 'html_url': 'https://github.com/example/repo/issues/1'},
    {'number': 17, 'html_url': 'https://fixture.invalid/issues/17'},
    {'number': 17, 'html_url': 'https://github.com/example/repo/issues/18'},
])
def test_unconfirmed_provider_receipt_is_unknown(receipt, monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator')
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'example/repo')
    class Response:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return json.dumps(receipt).encode()[:size]
    with patch('oneirodex.utils.github_issues._open_github_request', return_value=Response()):
        result = create_github_issue(title='Report', body='Report')
    assert result['ok'] is False
    assert result['outcome'] == 'unknown'


@pytest.mark.parametrize(('status', 'outcome'), [(403, 'rejected'), (422, 'rejected'), (500, 'unknown'), (408, 'unknown')])
def test_provider_errors_report_safe_definite_or_uncertain_outcome(status, outcome, monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator')
    error = urllib.error.HTTPError('https://api.github.com/repos/example/repo/issues', status,
                                   'Synthetic error', {}, io.BytesIO(b'SYNTHETIC_PRIVATE_PROVIDER_DETAIL'))
    with patch('oneirodex.utils.github_issues._open_github_request', side_effect=error):
        result = create_github_issue(title='Report', body='Report')
    assert result['outcome'] == outcome
    assert 'SYNTHETIC_PRIVATE_PROVIDER_DETAIL' not in json.dumps(result)


def test_non_created_status_does_not_claim_a_created_issue(monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator')
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'example/repo')
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1):
            return b'{"number":17,"html_url":"https://github.com/example/repo/issues/17"}'[:size]
    with patch('oneirodex.utils.github_issues._open_github_request', return_value=Response()):
        result = create_github_issue(title='Report', body='Report')
    assert result['ok'] is False
    assert result['outcome'] == 'unknown'


@pytest.mark.parametrize(('headers', 'minimum'), [
    ({'Retry-After': '120'}, 120),
    ({}, 60),
    ({'Retry-After': 'not-a-delay'}, 60),
])
def test_rate_limit_receipt_preserves_provider_cooldown(headers, minimum, monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'synthetic-operator')
    error = urllib.error.HTTPError('https://api.github.com/repos/example/repo/issues', 429,
                                   'Limited', headers, io.BytesIO(b'private provider detail'))
    with patch('oneirodex.utils.github_issues._open_github_request', side_effect=error):
        result = create_github_issue(title='Report', body='Report')
    assert result['http_status'] == 429
    assert result['retry_after_seconds'] >= minimum
    assert result['outcome'] == 'rejected'


def test_build_issue_body_includes_fields():
    body = build_issue_body({
        'id': 7,
        'user_id': 3,
        'role_at_submit': 'user',
        'severity': 'P1',
        'area': 'download',
        'deploy_hint': 'Unraid',
        'client_hint': 'browser',
        'url_hint': '/downloads',
        'body': 'Queue stuck',
        'logs': 'timeout',
    })
    assert 'Ticket ID:** 7' in body
    assert 'Queue stuck' in body
    assert '@issue-assess' in body


def test_support_github_repo_defaults_to_oneirodex(monkeypatch):
    monkeypatch.delenv('SUPPORT_GITHUB_REPO', raising=False)
    _token, repo = support_github_config()
    assert repo == 'cephyrixzyth/oneirodex'


def test_create_github_issue_skipped_without_token(monkeypatch):
    monkeypatch.delenv('SUPPORT_GITHUB_TOKEN', raising=False)
    result = create_github_issue(title='t', body='b')
    assert result.get('skipped') is True
    assert result.get('ok') is False


def test_create_github_issue_posts_when_token_set(monkeypatch):
    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'ghp_test')
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'cephyrixzyth/oneirodex')

    class Resp:
        status = 201
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return b'{"number": 42, "html_url": "https://github.com/cephyrixzyth/oneirodex/issues/42"}'[:size]

    with patch('oneirodex.utils.github_issues._open_github_request', return_value=Resp()):
        result = create_github_issue(title='hello', body='world', labels=['support'])
    assert result['ok'] is True
    assert result['number'] == 42


def test_create_github_issue_rejects_oversized_provider_response(monkeypatch):
    from oneirodex.utils.github_issues import MAX_GITHUB_RESPONSE_BYTES

    monkeypatch.setenv('SUPPORT_GITHUB_TOKEN', 'ghp_test')
    monkeypatch.setenv('SUPPORT_GITHUB_REPO', 'cephyrixzyth/oneirodex')

    class Resp:
        status = 201
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            assert size == MAX_GITHUB_RESPONSE_BYTES + 1
            return b'x' * size

    with patch('oneirodex.utils.github_issues._open_github_request', return_value=Resp()):
        result = create_github_issue(title='hello', body='world')

    assert result == {'ok': False, 'outcome': 'unknown', 'error': 'GitHub API response exceeded the size limit'}


def test_github_redirect_handler_refuses_unpreviewed_repository_rename():
    req = urllib.request.Request(
        'https://api.github.com/repos/old/repo/issues',
        headers={'Authorization': 'Bearer test-token'},
        data=b'{}',
        method='POST',
    )
    with pytest.raises(urllib.error.HTTPError) as raised:
        _GitHubRedirectHandler().redirect_request(
            req, io.BytesIO(), 301, 'Moved', {}, 'https://api.github.com/repos/new/repo/issues'
        )
    raised.value.close()


@pytest.mark.parametrize('url', [
    'http://api.github.com/repos/new/repo/issues',
    'https://api.github.com.evil.example/repos/new/repo/issues',
    'https://api.github.com@evil.example/repos/new/repo/issues',
    'https://api.github.com:444/repos/new/repo/issues',
])
def test_github_redirect_handler_rejects_non_api_origin(url):
    req = urllib.request.Request(
        'https://api.github.com/repos/old/repo/issues',
        headers={'Authorization': 'Bearer test-token'},
        data=b'{}',
        method='POST',
    )

    with pytest.raises(urllib.error.HTTPError) as raised:
        _GitHubRedirectHandler().redirect_request(req, io.BytesIO(), 301, 'Moved', {}, url)
    raised.value.close()


def test_open_github_request_uses_restricted_redirect_handler():
    req = urllib.request.Request('https://api.github.com/repos/owner/repo/issues')
    with patch('oneirodex.utils.github_issues.urllib.request.build_opener') as opener:
        _open_github_request(req, timeout=20)

    opener.assert_called_once_with(_GitHubRedirectHandler)
    opener.return_value.open.assert_called_once_with(req, timeout=20)
