"""GitHub Issues helper + support ticket create (token missing → skipped)."""

from unittest.mock import patch

from oneirodex.utils.github_issues import build_issue_body, create_github_issue, support_github_config


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
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"number": 42, "html_url": "https://github.com/cephyrixzyth/oneirodex/issues/42"}'

    with patch('oneirodex.utils.github_issues.urllib.request.urlopen', return_value=Resp()):
        result = create_github_issue(title='hello', body='world', labels=['support'])
    assert result['ok'] is True
    assert result['number'] == 42
