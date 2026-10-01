#!/usr/bin/env python3
"""Mirror canonical .cursor prompts to Claude and Codex discovery trees.

Canonical edit surface is ``.cursor/``. Claude Code still loads ``.claude/``,
so this script copies the trees. ``--check`` exits 1 if they differ (CI and
ship-ready). Does not copy ``.cursor/rules`` (Cursor glob rules only).
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAIRS = (
    (REPO / ".cursor" / "skills", REPO / ".claude" / "skills"),
    (REPO / ".cursor" / "agents", REPO / ".claude" / "agents"),
    (REPO / ".cursor" / "skills", REPO / ".agents" / "skills"),
)


def _rel_files(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def check() -> list[str]:
    problems: list[str] = []
    for src, dst in PAIRS:
        if not src.is_dir():
            problems.append(f"missing canonical directory: {src.relative_to(REPO)}")
            continue
        src_files = _rel_files(src)
        dst_files = _rel_files(dst)
        src_label = src.relative_to(REPO).as_posix()
        dst_label = dst.relative_to(REPO).as_posix()
        for rel in sorted(src_files - dst_files):
            problems.append(f"missing in {dst_label}: {rel}")
        for rel in sorted(dst_files - src_files):
            problems.append(f"extra in {dst_label}: {rel}")
        for rel in sorted(src_files & dst_files):
            if not filecmp.cmp(src / rel, dst / rel, shallow=False):
                problems.append(f"differ: {src_label}/{rel} vs {dst_label}/{rel}")
    return problems


def sync() -> int:
    copied = 0
    # Validate all resolved targets before touching any generated tree. Refuse
    # links/junctions and missing source trees instead of deleting a mirror.
    for src, dst in PAIRS:
        if not src.is_dir():
            raise ValueError(f"Missing canonical tree: {src}")
        for root in (src, dst):
            if not root.resolve().is_relative_to(REPO.resolve()):
                raise ValueError(f"Prompt tree escapes repository: {root}")
            for path in [root, *root.parents][:len(root.relative_to(REPO).parts)]:
                if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                    raise ValueError(f"Linked prompt directory: {path}")
            if root.exists():
                for path in root.rglob('*'):
                    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                        raise ValueError(f"Linked prompt entry: {path}")
    for src, dst in PAIRS:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied += len(_rel_files(dst))
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if generated .claude/ or .agents/ skills drifted",
    )
    args = parser.parse_args()
    if args.check:
        problems = check()
        if problems:
            print("prompt trees drifted:", file=sys.stderr)
            for item in problems:
                print(f"  {item}", file=sys.stderr)
            print("Run: python scripts/sync_prompt_trees.py", file=sys.stderr)
            return 1
        print("prompt trees in sync")
        return 0
    count = sync()
    # ASCII arrow on purpose: a Windows console defaults to cp1252, and the
    # U+2192 that used to be here raised UnicodeEncodeError *after* the mirror
    # had already succeeded — so the script exited non-zero on a clean run and
    # made `--check` look like drift.
    print(f"mirrored {count} files .cursor/ -> .claude/ and .agents/skills/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
