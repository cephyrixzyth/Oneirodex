#!/usr/bin/env python3
"""Blocking-database-call ratchet for ``async def`` native route handlers.

Why this exists
---------------
FastAPI runs a plain ``def`` handler on its threadpool, but an ``async def``
handler runs on the event loop itself. Native routes that read a request body
are ``async def``, and many of them then call ``request_auth_context`` (which
looks the member up in the database) or a ``data.<method>`` repository call
directly. While that synchronous query runs, the uvicorn worker serves nothing
else: one slow query or row lock stalls chat, the library and every other
request on that worker.

The fix for a handler is to await those calls through
``starlette.concurrency.run_in_threadpool`` (the request's database session
lives in context variables, which the threadpool copies), or to make the
handler a plain ``def`` when it never awaits anything.

This is the same per-file ratchet as ``scripts/print_lint.py``: existing
call sites are recorded, a file may never exceed its recorded count, and a
file with no record may have none.

What counts as a violation
--------------------------
Inside an ``async def`` (not inside a nested ``def`` or ``lambda``), a direct
call to ``request_auth_context(...)`` or ``data.<anything>(...)``. Passing the
callable to ``run_in_threadpool`` / ``to_thread.run_sync`` is not a call and is
not counted.

Scope
-----
``oneirodex/runtime_native/**/*.py``.

Usage
-----
    python scripts/async_blocking_lint.py            # check (exit 1 on regression)
    python scripts/async_blocking_lint.py --list     # show every call site it finds
    python scripts/async_blocking_lint.py --update   # re-record after a reduction
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "scripts" / "async_blocking_lint.baseline.json"
SCAN_ROOT = REPO_ROOT / "oneirodex" / "runtime_native"

BLOCKING_FUNCTIONS = {"request_auth_context"}
BLOCKING_RECEIVERS = {"data"}


def _is_blocking_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in BLOCKING_FUNCTIONS
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in BLOCKING_RECEIVERS
    return False


def _blocking_lines_in(func: ast.AsyncFunctionDef) -> list[int]:
    """Blocking calls made directly by ``func`` (nested scopes excluded)."""
    lines: list[int] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call) and _is_blocking_call(node):
            lines.append(node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(lines)


def blocking_call_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            lines.extend(_blocking_lines_in(node))
    return sorted(lines)


def count_blocking_calls(path: Path) -> int:
    """Single-file count. Takes any path (the tests hand it temp files)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError):
        return 0
    return len(blocking_call_lines(tree))


def scan(details: dict[str, list[int]] | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        found = blocking_call_lines(tree)
        if found:
            rel = path.relative_to(REPO_ROOT).as_posix()
            counts[rel] = len(found)
            if details is not None:
                details[rel] = found
    return counts


def read_baseline() -> dict[str, int]:
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def compare(counts: dict[str, int], baseline: dict[str, int]):
    regressions = sorted(
        (path, baseline.get(path, 0), count)
        for path, count in counts.items()
        if count > baseline.get(path, 0)
    )
    improvements = sorted(
        (path, allowed, counts.get(path, 0))
        for path, allowed in baseline.items()
        if counts.get(path, 0) < allowed
    )
    return regressions, improvements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="re-record the baseline")
    parser.add_argument("--list", action="store_true", help="list every call site")
    args = parser.parse_args(argv)

    details: dict[str, list[int]] = {}
    counts = scan(details)

    if args.list:
        for path in sorted(details):
            for line in details[path]:
                print(f"{path}:{line}")
        return 0

    if args.update:
        BASELINE_PATH.write_text(json.dumps(dict(sorted(counts.items())), indent=2) + "\n", encoding="utf-8")
        print(f"async-blocking-lint: recorded {sum(counts.values())} call sites in {len(counts)} files.")
        return 0

    regressions, improvements = compare(counts, read_baseline())
    if regressions:
        print("async-blocking-lint: blocking database calls added to async handlers:")
        for path, allowed, found in regressions:
            print(f"  {path}: {found} (allowed {allowed})")
        print(
            "Await them through starlette.concurrency.run_in_threadpool, or make the\n"
            "handler a plain `def` if it never awaits. See the module docstring."
        )
        return 1
    total = sum(counts.values())
    print(f"async-blocking-lint: OK ({total} known call sites, {len(improvements)} file(s) below baseline).")
    if improvements:
        print("  Baseline can be tightened: python scripts/async_blocking_lint.py --update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
