"""Published deployment examples use the canonical Oneirodex checkout."""

from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[1]
CHECKOUT = re.compile(r'_projects[\\/]+([^\\/\s`"<>]+)')
TEXT_SUFFIXES = {'.md', '.yml', '.yaml', '.json', '.txt', '.html', '.example'}


def _live_files():
    # Machine-local editor instructions and private research stay ignored and
    # cannot be prerequisites of a reproducible repository/CI check.
    paths = subprocess.check_output([
        'git', 'ls-files', '-z', '--', 'docs', 'NAS-DEPLOY.md',
        '.env.unraid.example', '.env.nas.example', '.env.docker.example',
        'docker-compose*.yml',
    ], cwd=REPO).decode('utf-8').split('\0')
    for relative in paths:
        path = REPO / relative
        if not relative or 'archive' in path.parts or '_private' in path.parts:
            continue
        if path.suffix in TEXT_SUFFIXES and path.is_file():
            yield path


def test_operator_docs_checkout_is_oneirodex():
    hits = []
    checked = 0
    for path in _live_files():
        text = path.read_text(encoding='utf-8', errors='replace')
        if '> **Doc status:** Archive' in text:
            continue
        for folder in CHECKOUT.findall(text):
            checked += 1
            if folder.rstrip('.,);:') != 'Oneirodex':
                hits.append(path.relative_to(REPO).as_posix())
    assert checked > 0, 'No published deployment checkout examples were checked'
    assert hits == [], f'Noncanonical Oneirodex checkout examples in: {sorted(set(hits))}'
