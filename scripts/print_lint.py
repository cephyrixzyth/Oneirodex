#!/usr/bin/env python3
"""``print()`` ratchet for the Oneirodex backend.

Why this exists
---------------
The backend shipped with no logging configuration and ~800 ``print()`` call
sites across ``oneirodex/`` and ``scripts/``. On Unraid that is an
unstructured, un-levelled, un-greppable stream on stdout, and every new route
reaches for ``print`` because the file next to it already does.

``oneirodex/utils/logging_setup.py`` gives the backend a real logging config.
This is the ratchet that stops the ``print`` count climbing back up while the
migration happens file by file — the exact model ``scripts/api_envelope_lint.py``
uses for the JSON envelope: existing call sites are recorded per file, a file
may never exceed its recorded count, and a file with no record may have none.

What counts as a violation
--------------------------
A call to the builtin ``print`` — ``ast.Call`` whose ``func`` is the bare name
``print``. ``logging`` calls, ``pprint(...)``, ``obj.print(...)`` and the string
``"print("`` inside a literal or comment are **not** counted (this is an AST
walk, not a grep).

Scope
-----
``oneirodex/**/*.py`` and the top level of ``scripts/*.py``. ``tests/`` is out
of scope (assertions and fixtures print freely). ``oneirodex/updateschema.py``
and ``scripts/get_json_lint.py`` are excluded: the former is an operator-run
migration whose progress ``print``s are its interface; the latter is a CLI
ratchet whose report is stdout.

Usage
-----
    python scripts/print_lint.py            # check (exit 1 on regression)
    python scripts/print_lint.py --list     # show every call site it finds
    python scripts/print_lint.py --update   # re-record after a reduction
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "scripts" / "print_lint.baseline.json"

#: Trees whose ``print()`` output should become ``logging``.
SCAN_ROOTS = ["oneirodex"]

#: ``scripts/`` is scanned one level deep only (no nested tooling packages).
SCRIPT_GLOB = "scripts/*.py"

#: Files that legitimately keep ``print`` as their interface.
EXEMPT = {
    "oneirodex/updateschema.py",  # operator-run migration; progress print is UX
    "scripts/get_json_lint.py",  # CLI ratchet; stdout is the report
    # These tools are CLI reports consumed directly by operators and scripts.
    "scripts/generate_icon_adapters.py",
    "scripts/p17_route_parity.py",
    # The docs-capture tools. Each is operator-run against a throwaway
    # instance, and its stdout *is* the deliverable: which surface was shot,
    # which was skipped and why, which clip was written, which affordance the
    # UI could not offer. Routing that through `logging` would put the report
    # behind a level and a handler nobody configures for a one-shot script —
    # the same reason `updateschema.py` and `get_json_lint.py` are here.
    "scripts/capture_common.py",
    "scripts/capture_docs_media.py",
    "scripts/capture_howto_videos.py",
    "scripts/render_readme_art.py",
    "scripts/serve_capture.py",
}


def _read_source(path: Path) -> str:
    """Read Python as text, tolerating a notepad-saved BOM (utf-8 raises on it)."""
    return path.read_text(encoding="utf-8-sig")


def iter_python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {"__pycache__", "node_modules", "static", "migrations"}
        ]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _iter_target_files():
    for root in SCAN_ROOTS:
        yield from iter_python_files(REPO_ROOT / root)
    yield from sorted((REPO_ROOT).glob(SCRIPT_GLOB))


def _print_call_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every ``print(...)`` builtin call in the tree."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            lines.append(node.lineno)
    return sorted(lines)


def count_print_calls(path: Path) -> int:
    """Single-file count. Takes any path (the tests hand it temp files)."""
    try:
        tree = ast.parse(_read_source(path))
    except (SyntaxError, UnicodeDecodeError):
        return 0
    return len(_print_call_lines(tree))


def scan(details: dict[str, list[int]] | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for path in _iter_target_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in seen or rel in EXEMPT:
            continue
        seen.add(rel)
        try:
            tree = ast.parse(_read_source(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        found = _print_call_lines(tree)
        if found:
            counts[rel] = len(found)
            if details is not None:
                details[rel] = found
    return counts


def read_baseline() -> dict[str, int]:
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def compare(counts: dict[str, int], baseline: dict[str, int]):
    regressions, improvements = [], []
    for file, found in sorted(counts.items()):
        allowed = baseline.get(file, 0)
        if found > allowed:
            regressions.append((file, found, allowed))
        elif found < allowed:
            improvements.append((file, found, allowed))
    for file, allowed in sorted(baseline.items()):
        if file not in counts and allowed:
            improvements.append((file, 0, allowed))
    return regressions, improvements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="re-record the baseline")
    parser.add_argument(
        "--list", action="store_true", help="print every call site found"
    )
    args = parser.parse_args()

    details: dict[str, list[int]] = {}
    counts = scan(details)
    total = sum(counts.values())

    if args.list:
        for file in sorted(details):
            print(f"{file}")
            for line in details[file]:
                print(f"  {file}:{line}")
        print(f"\nprint-lint: {total} call sites across {len(counts)} files.")
        return 0

    if args.update:
        BASELINE_PATH.write_text(
            json.dumps(dict(sorted(counts.items())), indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"print-lint: recorded {total} existing call sites "
            f"across {len(counts)} files."
        )
        return 0

    baseline = read_baseline()
    regressions, improvements = compare(counts, baseline)

    if regressions:
        print("print-lint: new print() call sites\n")
        for file, found, allowed in regressions:
            print(f"  {file}: {found} > {allowed} allowed")
            for line in details.get(file, []):
                print(f"      {file}:{line}")
        print(
            "\nUse logging instead: `logger = logging.getLogger(__name__)` at module\n"
            "level, then logger.info()/warning()/error(). Config lives in\n"
            "oneirodex/utils/logging_setup.py. If a reduction elsewhere makes this\n"
            "unavoidable, re-record: python scripts/print_lint.py --update"
        )
        return 1

    if improvements:
        print(
            f"print-lint: OK ({total} known call sites, "
            f"{len(improvements)} file(s) below baseline)."
        )
        print("  Baseline can be tightened: python scripts/print_lint.py --update")
        return 0

    print(f"print-lint: OK ({total} known call sites, none new).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
