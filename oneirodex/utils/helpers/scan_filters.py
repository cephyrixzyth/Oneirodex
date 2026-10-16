"""Scan folder-skip globs / regexes + name-clean filter pattern loaders.

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""
import re
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import ReleaseGroup
from oneirodex.utils.quality_profiles import active_exclude_terms_for_scan

__all__ = [
    "DEFAULT_SKIP_DIR_GLOBS",
    "DEFAULT_SKIP_DIR_REGEXES",
    "_DIR_FILTER_PREFIX",
    "_REGEX_FILTER_PREFIX",
    "load_skip_dir_patterns",
    "load_skip_dir_regex_patterns",
    "_CASE_SENSITIVE_TRUE",
    "is_case_sensitive_flag",
    "normalize_case_sensitive",
    "load_scanning_filter_patterns",
]


# Folder-name globs skipped while listing game dirs (emu installs / FE / tools).
# Case-insensitive fnmatch. Source of truth: docs/strategy/console-gaming-libraries.md.
# Operators may add more via Admin → Scanning filters with prefix ``dir:``
# (e.g. ``dir:_MyTools``). Name-clean ReleaseGroup rows (no ``dir:``) are unchanged.
# Prefer prefix globs (``emu*``) over substring (``*emu*``) so real titles are
# not skipped — e.g. ``*dolphin*`` killed ``Ecco the Dolphin``; ``GOD *`` /
# ``GOD*`` killed ``God of War`` / ``God Hand``. Align with
# docs/strategy/console-gaming-libraries.md exclude list.
DEFAULT_SKIP_DIR_GLOBS = (
    '_Emulators',
    'Emulators',
    '*duckstation*',  # portable builds often have version prefixes
    'yuzu*',
    'ryujinx*',
    'xenia*',
    'zinc*',
    'mame0*',
    'bsnes*',
    'mgba*',
    'snes9x*',
    'virtualjaguar*',
    'pcsx2*',
    'dolphin*',
    'citra*',
    'flycast*',
    'vita3k*',
    'retroarch*',
    'cru-*',
    'pegasus*',
    'pegasus-fe*',
    'GOD v*',  # tool folder e.g. "GOD v1.0" — not "God of War"
    # Emulator install scaffolding (defense-in-depth when lib is pointed too high)
    'Config',
    'Lang',
    'Plugin',
    'ROMs',
    'docs',
    # Scan-root / lane leaks — never game folders
    '_console-gaming',
    '_pc',
    # Walkthrough / guide trees (not games)
    'walkthroughs',
    '_walkthroughs',
    '*walkthrough*',
    # Mod / VR-mod pack folders (generic markers — avoid ``*mod*`` mid-title false positives)
    '* MOD',
    '* MOD *',
    '*-MOD',
    '*-MOD-*',
    '* VR Mod*',
    '* VR mod*',
)

# Folder basenames matching these regexes are skipped (repack bracket tags, etc.).
# Operators may add more via Admin scanning filters prefixed with ``re:``.
DEFAULT_SKIP_DIR_REGEXES = (
    re.compile(
        r'\[\s*(?:[^\]]*?[^\s\]]\s+)?(?:HV\s+)?Repack\s*\]',
        re.IGNORECASE,
    ),
)

_DIR_FILTER_PREFIX = 'dir:'
_REGEX_FILTER_PREFIX = 're:'


def load_skip_dir_patterns():
    """Built-in skip-dir globs plus Admin scanning filters prefixed with ``dir:``."""
    patterns = list(DEFAULT_SKIP_DIR_GLOBS)
    try:
        rows = db.session.execute(
            select(ReleaseGroup).filter(ReleaseGroup.filter_pattern.isnot(None))
        ).scalars().all()
        for rg in rows:
            raw = (rg.filter_pattern or '').strip()
            if not raw.lower().startswith(_DIR_FILTER_PREFIX):
                continue
            extra = raw[len(_DIR_FILTER_PREFIX):].strip()
            if extra:
                patterns.append(extra)
        return patterns
    except SQLAlchemyError as e:
        print(f"An error occurred while fetching skip-dir patterns: {e}")
        return list(DEFAULT_SKIP_DIR_GLOBS)


def load_skip_dir_regex_patterns():
    """Built-in skip-dir regexes plus Admin scanning filters prefixed with ``re:``."""
    patterns = list(DEFAULT_SKIP_DIR_REGEXES)
    try:
        rows = db.session.execute(
            select(ReleaseGroup).filter(ReleaseGroup.filter_pattern.isnot(None))
        ).scalars().all()
        for rg in rows:
            raw = (rg.filter_pattern or '').strip()
            if not raw.lower().startswith(_REGEX_FILTER_PREFIX):
                continue
            extra = raw[len(_REGEX_FILTER_PREFIX):].strip()
            if not extra:
                continue
            try:
                patterns.append(re.compile(extra, re.IGNORECASE))
            except re.error as exc:
                print(f"Invalid skip-dir regex filter {extra!r}: {exc}")
        return patterns
    except SQLAlchemyError as e:
        print(f"An error occurred while fetching skip-dir regex patterns: {e}")
        return list(DEFAULT_SKIP_DIR_REGEXES)


# Truthy forms historically written by scan_management (bool) vs edit_filters ('yes'|'no').
_CASE_SENSITIVE_TRUE = frozenset({'yes', 'true', '1', 'y', 'on'})


def is_case_sensitive_flag(value) -> bool:
    """Normalize ReleaseGroup.case_sensitive stored forms to bool.

    Accepts bool, int/float (nonzero), and common string forms
    (``'yes'|'no'``, ``'true'|'false'``, ``'1'|'0'``).
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return False
    return text in _CASE_SENSITIVE_TRUE


def normalize_case_sensitive(value) -> str:
    """Canonical DB string for ``filters.case_sensitive`` (String column)."""
    return 'yes' if is_case_sensitive_flag(value) else 'no'


def load_scanning_filter_patterns():
    try:
        # Fetching insensitive patterns (not case-sensitive).
        # Skip ``dir:`` rows — those are folder-skip globs, not name cleaners.
        name_filter_rows = [
            rg for rg in db.session.execute(
                select(ReleaseGroup).filter(ReleaseGroup.filter_pattern.isnot(None))
            ).scalars().all()
            if not (rg.filter_pattern or '').strip().lower().startswith(_DIR_FILTER_PREFIX)
            and not (rg.filter_pattern or '').strip().lower().startswith(_REGEX_FILTER_PREFIX)
        ]
        insensitive_patterns = [
            "-" + rg.filter_pattern for rg in name_filter_rows
        ] + [
            "." + rg.filter_pattern for rg in name_filter_rows
        ]

        # Rows with a case_sensitive flag (any stored shape) drive the
        # (pattern, is_case_sensitive) pairs used by name cleaning.
        sensitive_patterns = []
        for rg in db.session.execute(select(ReleaseGroup).filter(ReleaseGroup.case_sensitive.isnot(None))).scalars().all():
            raw_fp = (rg.filter_pattern or '').strip().lower()
            if raw_fp.startswith(_DIR_FILTER_PREFIX) or raw_fp.startswith(_REGEX_FILTER_PREFIX):
                continue
            is_case_sensitive = is_case_sensitive_flag(rg.case_sensitive)
            sensitive_patterns.append(("-" + rg.filter_pattern, is_case_sensitive))
            sensitive_patterns.append(("." + rg.filter_pattern, is_case_sensitive))

        # Active quality profile blocked groups / excluded terms (P1-12) —
        # same strip shape as ReleaseGroup name cleaners (-tag / .tag).
        try:
            for term in active_exclude_terms_for_scan():
                if not term:
                    continue
                insensitive_patterns.append("-" + term)
                insensitive_patterns.append("." + term)
                sensitive_patterns.append(("-" + term, False))
                sensitive_patterns.append(("." + term, False))
        except Exception as qp_exc:
            print(f"Quality profile scan filters skipped: {qp_exc}")

        return insensitive_patterns, sensitive_patterns
    except SQLAlchemyError as e:
        print(f"An error occurred while fetching scanning filter patterns: {e}")
        return [], []
