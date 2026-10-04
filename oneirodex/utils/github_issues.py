"""Create GitHub Issues for in-app support tickets (free API; no chat SaaS)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def support_github_config() -> tuple[str | None, str]:
    token = (os.getenv('SUPPORT_GITHUB_TOKEN') or '').strip() or None
    # GitHub rename landed: default is cephyrixzyth/oneirodex. The old
    # cephyrixzyth/oneirodex URL still redirects; set SUPPORT_GITHUB_REPO if
    # this install files issues against a fork.
    repo = (os.getenv('SUPPORT_GITHUB_REPO') or 'cephyrixzyth/oneirodex').strip()
    return token, repo


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
    return '\n'.join(lines)


def create_github_issue(*, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
    """POST a GitHub issue. Returns {ok, number, url, error?}."""
    token, repo = support_github_config()
    if not token:
        return {'ok': False, 'skipped': True, 'error': 'SUPPORT_GITHUB_TOKEN not set'}
    if '/' not in repo:
        return {'ok': False, 'error': 'Invalid SUPPORT_GITHUB_REPO'}

    payload: dict[str, Any] = {'title': title[:200], 'body': body}
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
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return {
            'ok': True,
            'number': data.get('number'),
            'url': data.get('html_url'),
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:400]
        return {'ok': False, 'error': f'GitHub HTTP {exc.code}: {detail}'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
