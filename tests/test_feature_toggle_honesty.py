"""Every admin feature toggle must actually change something.

Written after a review found two toggles that did nothing: an admin could flip
them and observe no change. That is the opposite of the honesty this product
applies everywhere else (`why_unmatched`, BIOS readiness, `installed: false` on
fonts), so it gets a regression test rather than a one-off fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "oneirodex" / "utils" / "feature_catalog.py"

# Where a flag may legitimately be consumed.
SEARCH_ROOTS = [
    ROOT / "oneirodex",
    ROOT / "frontend" / "member-app" / "src",
    ROOT / "frontend" / "admin-app" / "src",
]
SEARCH_SUFFIXES = {".py", ".jsx", ".js", ".html", ".ts", ".tsx"}
SKIP_DIRS = {"__pycache__", "node_modules", "dist", "vendor", "static"}


def _declared_flags() -> list[tuple[str, str]]:
    src = FEATURES.read_text(encoding="utf-8")
    return [(m[0], m[1]) for m in re.findall(
        r"\(\s*'([a-z_]+)'\s*,\s*'([A-Z_]+)'\s*,\s*'([^']+)'", src
    )]


def _corpus() -> str:
    chunks = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SEARCH_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path == FEATURES:
                continue  # the declaration itself is not a use
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


@pytest.mark.parametrize("setting,env", _declared_flags())
def test_toggle_is_actually_consumed(setting, env):
    """A toggle shown to admins must be read somewhere outside its declaration."""
    corpus = _corpus()
    hits = len(re.findall(r"\b" + re.escape(env) + r"\b", corpus))
    assert hits > 0, (
        f"Admin feature toggle {env} ('{setting}') is declared in feature_catalog.py "
        f"but never read anywhere in oneirodex/ or the SPAs. An admin can flip "
        f"it and nothing happens. Either wire it up or remove the toggle."
    )
