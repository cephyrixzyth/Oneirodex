#!/usr/bin/env python3
"""Fail release builds when tracked third-party licence records are absent."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


REQUIRED_FILES = (
    "LICENSE",
    "oneirodex/setup/fonts/OFL.txt",
    "oneirodex/static/vendor/THIRD-PARTY-NOTICES.md",
    "oneirodex/static/vendor/webretro/LICENSE",
    "oneirodex/static/vendor/nostalgist/LICENSE",
    "oneirodex/static/vendor/emulatorjs/LICENSE",
)
REQUIRED_NOTICE_TEXT = (
    "6.5 | MIT",
    "0.21.1 | MIT",
    "EmulatorJS",
    "4.2.3 | GPL-3.0",
)
PINNED_LICENSE_SHA256 = {
    "oneirodex/setup/fonts/OFL.txt": "004fc993a3bdaaf0fd443cb58d7e5c2fd09fc3a93b23309d0005421f7b8b7123",
    "oneirodex/static/vendor/webretro/LICENSE": "ca0b4ec2c39e4ca23545e1181e5fbf2e598c5f646eb1a7b464559f10fcce25e1",
    "oneirodex/static/vendor/nostalgist/LICENSE": "298d2b528c4ff4d4a1406fe48db90a9fe4c4de7363a4215c9606b9013acbcda2",
    "oneirodex/static/vendor/emulatorjs/LICENSE": "a617fab6d251b3302b1cb2c1c94f52d1c584f6fcb2fc218ec1a475bc08053a61",
}


def check_release_license_files(root: Path) -> list[str]:
    problems = [
        f"required licence file missing or empty: {relative}"
        for relative in REQUIRED_FILES
        if not (root / relative).is_file() or (root / relative).stat().st_size == 0
    ]
    for relative, expected in PINNED_LICENSE_SHA256.items():
        path = root / relative
        if path.is_file() and path.stat().st_size:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                problems.append(f"pinned licence digest mismatch: {relative}")
    notices = root / "oneirodex/static/vendor/THIRD-PARTY-NOTICES.md"
    if notices.is_file():
        text = notices.read_text(encoding="utf-8")
        problems.extend(
            f"third-party notice is missing required entry: {marker}"
            for marker in REQUIRED_NOTICE_TEXT
            if marker not in text
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    problems = check_release_license_files(args.root.resolve())
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        return 1
    print(f"Release licence check passed ({len(REQUIRED_FILES)} files and notice entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
