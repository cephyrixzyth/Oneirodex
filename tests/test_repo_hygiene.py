"""Agent-harness files must never be tracked, whatever agent or model is in use.

The human ruled on 2026-09-17: ``CLAUDE.md`` / ``AGENTS.md`` (how an agent is run
against this repo -- seats, skills, ship procedure) and the ``.claude/`` /
``.cursor/`` kit stay off GitHub. PR #115 had tracked the two files on the
theory that a fresh clone needed project instructions; the conventions a
contributor actually needs now live in ``CONTRIBUTING.md`` instead.

This test is the guard the ruling asked for. It reads the *index*, not the
working tree, so it fails the moment any agent stages one of these paths --
including a future one that has never read the ruling.

Agent *handoff briefs* are the same class (PR #140, 2026-09-18, tried to route
one into ``docs/HANDOFF.md`` because the root ``/*.md`` ignore swallowed it).
They describe how an agent is run -- plan files, memories, queue mechanics --
and name the operator's own hosts and containers. They live in ``docs/_private/``
(ignored) like the 2026-09-01 brief before them.

Exempt: ``.cursor/environment.json`` / ``install.sh`` / ``start.sh`` -- Cursor's
cloud-agent *environment* bootstrap (a Postgres install and a generated key),
which contain no agent instructions and which the cloud agent cannot clone
without. Add to the exemption only with the same justification.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Paths (or prefixes ending in '/') that must never appear in `git ls-files`.
FORBIDDEN = (
    'CLAUDE.md',
    'AGENTS.md',
    '.claude/',
    '.agents/',
    '.cursor/',
    'docs/HANDOFF.md',
    'docs/_private/',
)

EXEMPT = frozenset({
    '.cursor/environment.json',
    '.cursor/install.sh',
    '.cursor/start.sh',
})


def _tracked_paths() -> list[str]:
    try:
        out = subprocess.run(
            ['git', '-c', 'safe.directory=*', 'ls-files', '-z', '--', *FORBIDDEN],
            cwd=ROOT, check=True, capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f'git unavailable for the hygiene check: {exc}')
    return [p for p in out.decode('utf-8').split('\0') if p]


def test_agent_harness_files_are_not_tracked():
    offenders = sorted(p for p in _tracked_paths() if p not in EXEMPT)
    assert not offenders, (
        'agent-harness paths are tracked in git; the human ruled they stay local '
        '(2026-09-17). Untrack them with `git rm --cached`:\n  ' + '\n  '.join(offenders)
    )


def test_gitignore_still_names_the_policy():
    """The ignore lines are the first line of defence; the test is the second."""
    text = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for line in ('/AGENTS.md', '/CLAUDE.md', '.claude/', '.agents/', 'docs/_private/'):
        assert line in text, f'{line!r} missing from .gitignore'
