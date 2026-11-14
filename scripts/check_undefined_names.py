#!/usr/bin/env python3
"""Fail on Pyflakes F821 references in production Python modules."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyflakes.checker import Checker
from pyflakes.messages import UndefinedName

ROOT = Path(__file__).resolve().parents[1]


def undefined_name_errors(paths: list[Path]) -> list[str]:
    errors = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        checker = Checker(ast.parse(source, filename=str(path)), str(path))
        errors.extend(
            f"{path}:{message.lineno}:{message.col + 1}: undefined name {message.message_args[0]!r}"
            for message in checker.messages
            if isinstance(message, UndefinedName)
        )
    return errors


def main() -> int:
    paths = sorted((ROOT / "oneirodex").rglob("*.py"))
    errors = undefined_name_errors(paths)
    if errors:
        print("Python undefined-name check failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Python undefined-name check passed ({len(paths)} production modules).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
