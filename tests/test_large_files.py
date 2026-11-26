"""New large files must not enter git history.

Every tracked file stays in every clone forever, even after it is deleted, so
``.git`` grew past 300 MB largely from per-release screenshots, captures and
videos under ``docs/media``. Release evidence belongs in workflow or release
artifacts (``actions/upload-artifact``), not commits.

``scripts/large_files.baseline`` records each tracked file over the limit with
its size at the time. A file not listed may not exceed the limit, and a listed
file may not grow. Remove a line when its file is deleted or shrinks below the
limit. Add one only for a runtime asset the app genuinely ships (a texture, an
icon), never for documentation evidence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'scripts' / 'large_files.baseline'
LIMIT_BYTES = 512 * 1024


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ['git', '-c', 'safe.directory=*', 'ls-files', '-z'],
            cwd=ROOT, check=True, capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f'git unavailable for the large-file check: {exc}')
    return [p for p in out.decode('utf-8').split('\0') if p]


def _baseline() -> dict[str, int]:
    recorded: dict[str, int] = {}
    for line in BASELINE.read_text(encoding='utf-8').splitlines():
        if line.strip():
            path, size = line.rsplit(' ', 1)
            recorded[path] = int(size)
    return recorded


def test_no_new_or_growing_large_files_are_tracked():
    recorded = _baseline()
    offenders = []
    for rel in _tracked_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size <= LIMIT_BYTES:
            continue
        allowed = recorded.get(rel)
        if allowed is None or size > allowed:
            offenders.append(f'{rel} ({size // 1024} KB, allowed {(allowed or LIMIT_BYTES) // 1024} KB)')
    assert not offenders, (
        'Large files would enter git history. Publish captures and evidence as '
        'workflow or release artifacts instead, or compress the asset:\n  '
        + '\n  '.join(offenders)
    )
