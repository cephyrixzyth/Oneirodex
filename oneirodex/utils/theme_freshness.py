"""Is the served theme actually the theme we shipped?

Theme CSS/JS is served from ``static/library/themes/<theme>/`` and only gets
there when an admin runs **Reset Themes**, which copies it out of
``setup/default_theme/``. That is a deliberate design — an operator can edit a
theme in place and keep their edits across upgrades — but it has a sharp edge:
after any release that changes theme assets, the running product keeps serving
the previous copy, silently, until somebody presses the button.

Nothing reported that. A stylesheet fix could be written, reviewed, tested,
merged and deployed while the browser went on loading the old file, and the only
symptom was "the fix didn't work" — which sends everyone looking at the CSS
instead of at the copy step. That is exactly how a day gets lost.

Read-only and cheap: it hashes the source and deployed copies of the theme's
own assets and reports which are missing or behind. It never copies anything —
the fix is the existing Reset Themes action, which is an operator's decision.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from oneirodex.utils.library_paths import library_dir

#: Only the asset types Reset Themes actually manages. Images and fonts are
#: excluded: they are large, rarely edited, and an operator swapping artwork is
#: a supported thing to do rather than drift worth reporting.
TRACKED_SUFFIXES = frozenset({'.css', '.js'})


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def theme_freshness(app_root: str | Path, theme: str = 'default') -> dict[str, Any]:
    """Compare a deployed theme against the source it was copied from.

    Returns ``checked`` / ``missing`` / ``outdated`` / ``stale``. A theme that
    has never been deployed at all reports every tracked file as missing, which
    is the honest answer — it is not "up to date because there is nothing to
    compare".
    """
    root = Path(app_root)
    source = root / 'setup' / 'default_theme'
    deployed = Path(library_dir(root)) / 'themes' / theme

    if not source.is_dir():
        # Nothing to compare against — say so rather than implying freshness.
        #
        # Same key set as the success return, deliberately: a caller that only
        # wants the numbers must not have to know this branch exists. It did
        # once omit the two *_count keys, and the Ops panel that read them
        # KeyError'd, which 503'd an endpoint serving four unrelated panels.
        return {
            'theme': theme,
            'checked': 0,
            'missing': [],
            'missing_count': 0,
            'outdated': [],
            'outdated_count': 0,
            'stale': False,
            'reason': 'source theme not found',
        }

    missing: list[str] = []
    outdated: list[str] = []
    checked = 0

    for src_file in sorted(source.rglob('*')):
        if not src_file.is_file() or src_file.suffix.lower() not in TRACKED_SUFFIXES:
            continue
        rel = src_file.relative_to(source).as_posix()
        checked += 1

        target = deployed / rel
        if not target.is_file():
            missing.append(rel)
            continue
        if _digest(src_file) != _digest(target):
            outdated.append(rel)

    return {
        'theme': theme,
        'checked': checked,
        # Capped in the payload, not in the counts: a never-deployed theme would
        # otherwise dump a hundred paths into an Ops panel. The totals stay
        # honest, the list stays readable.
        'missing': missing[:20],
        'missing_count': len(missing),
        'outdated': outdated[:20],
        'outdated_count': len(outdated),
        'stale': bool(missing or outdated),
        'reason': None,
    }


def theme_freshness_summary(app_root: str | Path, theme: str = 'default') -> str:
    """One line for an Ops tile."""
    data = theme_freshness(app_root, theme)
    if data.get('reason'):
        return data['reason']
    if not data['stale']:
        return 'Up to date'
    parts = []
    if data['outdated_count']:
        parts.append(f"{data['outdated_count']} behind")
    if data['missing_count']:
        parts.append(f"{data['missing_count']} missing")
    return ' · '.join(parts) + ' — run Reset Themes'
