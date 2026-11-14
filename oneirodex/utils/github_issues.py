"""Create GitHub Issues for in-app support tickets (free API; no chat SaaS)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
import urllib.error
import urllib.request
from typing import Any

from oneirodex.utils.support_privacy import redact_support_text


MAX_GITHUB_RESPONSE_BYTES = 64 * 1024


def _github_retry_after(status, headers):
    """Retain provider pacing without retaining arbitrary response diagnostics."""
    headers = headers or {}
    now = datetime.now(timezone.utc)
    maximum = int((datetime.max.replace(tzinfo=timezone.utc) - now).total_seconds()) - 1
    def header(name):
        return headers.get(name) or headers.get(name.lower())
    wait = 60 if status in {403, 429} else 0
    value = header('Retry-After')
    if value is not None:
        try:
            raw = str(value).strip()
            if raw.isdecimal():
                wait = min(int(raw), maximum) if len(raw) < 20 else maximum
            else:
                target = parsedate_to_datetime(raw)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                wait = max(0, ceil((target - now).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            wait = max(wait, 60)
    if header('X-RateLimit-Remaining') == '0':
        try:
            raw = str(header('X-RateLimit-Reset') or '').strip()
            reset = int(raw) if len(raw) < 20 else maximum + ceil(now.timestamp())
            wait = max(wait, ceil(reset - now.timestamp()))
        except (ValueError, OverflowError):
            wait = max(wait, 60)
    return min(max(0, wait), maximum)


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A changed destination requires a new preview; never replay a support POST."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _open_github_request(req, *, timeout: int):
    opener = urllib.request.build_opener(_GitHubRedirectHandler)
    return opener.open(req, timeout=timeout)


def support_github_config() -> tuple[str | None, str]:
    token = (os.getenv('SUPPORT_GITHUB_TOKEN') or '').strip() or None
    # GitHub rename landed: default is cephyrixzyth/oneirodex. The old
    # cephyrixzyth/oneirodex URL still redirects; set SUPPORT_GITHUB_REPO if
    # this install files issues against a fork.
    repo = (os.getenv('SUPPORT_GITHUB_REPO') or 'cephyrixzyth/oneirodex').strip()
    return token, repo


def valid_support_repository(repo: str) -> bool:
    """A repository slug, never a URL, query, credential or extra API path."""
    owner, separator, name = repo.partition('/')
    return bool(separator and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner)
                and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name)
                and name not in {'.', '..'})


def build_issue_body(ticket: dict[str, Any]) -> str:
    lines = [
        '## Support ticket (Oneirodex)',
        '',
        f"**Ticket ID:** {ticket.get('id')}",
        f"**Reporter user_id:** {ticket.get('user_id')}",
        f"**Role at submit:** {ticket.get('role_at_submit') or '—'}",
        f"**Severity:** {ticket.get('severity') or 'P2'}",
        f"**Area:** {ticket.get('area') or '—'}",
        f"**Deploy:** {ticket.get('deploy_hint') or '—'}",
        f"**Client:** {ticket.get('client_hint') or '—'}",
        f"**URL:** {ticket.get('url_hint') or '—'}",
        '',
        '### Symptom',
        ticket.get('body') or '—',
        '',
    ]
    logs = (ticket.get('logs') or '').strip()
    if logs:
        lines.extend(['### Logs (trimmed)', '```', logs[:4000], '```', ''])
    lines.extend([
        '---',
        '_Filed from Oneirodex in-app Report. Triage with `@issue-assess`, fix with `@issue-fix`._',
    ])
    token, _repo = support_github_config()
    return redact_support_text('\n'.join(lines), secrets=(token or '',))


def create_github_issue(*, title: str, body: str, labels: list[str] | None = None,
                        expected_repository: str | None = None) -> dict[str, Any]:
    """POST a GitHub issue. Returns {ok, number, url, error?}."""
    token, repo = support_github_config()
    if not token:
        return {'ok': False, 'skipped': True, 'error': 'SUPPORT_GITHUB_TOKEN not set'}
    if not valid_support_repository(repo):
        return {'ok': False, 'error': 'Invalid SUPPORT_GITHUB_REPO'}
    if expected_repository is not None and repo != expected_repository:
        return {'ok': False, 'skipped': True, 'error': 'Support destination changed; preview again'}

    # Enforce at the final shared sink as well as the preview/body formatter.
    # Direct callers must not bypass filtering, including through the title.
    payload: dict[str, Any] = {
        'title': redact_support_text(title, secrets=(token,))[:200],
        'body': redact_support_text(body, secrets=(token,)),
    }
    if labels:
        payload['labels'] = labels[:10]

    url = f'https://api.github.com/repos/{repo}/issues'
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'Oneirodex-Support',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    try:
        with _open_github_request(req, timeout=20) as resp:
            raw = resp.read(MAX_GITHUB_RESPONSE_BYTES + 1)
            response_status = resp.status
        if len(raw) > MAX_GITHUB_RESPONSE_BYTES:
            return {'ok': False, 'outcome': 'unknown', 'error': 'GitHub API response exceeded the size limit'}
        data = json.loads(raw.decode('utf-8'))
        number = data.get('number') if isinstance(data, dict) else None
        issue_url = data.get('html_url') if isinstance(data, dict) else None
        expected_url = f'https://github.com/{repo}/issues/{number}'
        if (response_status != 201 or type(number) is not int or number <= 0
                or not isinstance(issue_url, str) or issue_url.casefold() != expected_url.casefold()):
            return {'ok': False, 'outcome': 'unknown', 'error': 'GitHub did not return a confirmed issue receipt'}
        return {
            'ok': True,
            'number': number,
            'url': issue_url,
            'http_status': 201,
        }
    except urllib.error.HTTPError as exc:
        status = exc.code
        cooldown = _github_retry_after(status, exc.headers)
        exc.close()
        # No automatic retries, even for definite rejection. In particular a
        # timeout or server error cannot establish that creation did not occur.
        outcome = 'rejected' if status in {400, 401, 403, 404, 410, 422, 429} else 'unknown'
        return {'ok': False, 'outcome': outcome, 'error': f'GitHub HTTP {status}',
                'http_status': status, 'retry_after_seconds': cooldown}
    except Exception:
        return {'ok': False, 'outcome': 'unknown', 'error': 'GitHub delivery could not be confirmed'}


def read_support_issue(*, repository: str, issue_number: int) -> dict[str, Any] | None:
    """Read only; never return arbitrary provider diagnostics to a member."""
    token, _repo = support_github_config()
    if not token or not valid_support_repository(repository) or type(issue_number) is not int or not 0 < issue_number <= 2_147_483_647:
        return None
    url = f'https://api.github.com/repos/{repository}/issues/{issue_number}'
    req = urllib.request.Request(url, method='GET', headers={
        'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {token}',
        'User-Agent': 'Oneirodex-Support', 'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with _open_github_request(req, timeout=20) as response:
            raw = response.read(MAX_GITHUB_RESPONSE_BYTES + 1)
            status = response.status
        if status != 200 or len(raw) > MAX_GITHUB_RESPONSE_BYTES:
            return None
        data = json.loads(raw.decode('utf-8'))
        expected = f'https://github.com/{repository}/issues/{issue_number}'
        if (not isinstance(data, dict) or type(data.get('number')) is not int
                or data['number'] != issue_number or data.get('pull_request') is not None
                or not isinstance(data.get('html_url'), str) or data['html_url'].casefold() != expected.casefold()
                or not isinstance(data.get('title'), str) or not isinstance(data.get('body'), str)):
            return None
        return {key: data[key] for key in ['number', 'html_url', 'title', 'body']}
    except urllib.error.HTTPError as exc:
        exc.close()
        return None
    except Exception:
        return None
