#!/usr/bin/env python3
"""Download the OFL theme fonts Oneirodex's font picker offers.

Why this exists
---------------
The font registry in ``oneirodex/utils/theme_fonts.py`` names five open-licence
faces, but the **binaries are not vendored** in this repo — same stance as
WebRetro cores and reference DATs. Without them every built-in except
``system-ui`` silently falls through to a CSS fallback, so the picker appears to
do nothing. This script fetches them.

All five are **SIL Open Font License 1.1** from the official `google/fonts`
repository. The OFL permits redistribution, so an operator may also mirror these
internally; we fetch rather than vendor to keep binaries out of git history.

Files land in ``oneirodex/static/library/fonts/`` (gitignored) under exactly the
names the registry expects — a mismatch means the face still won't load.

Usage:
  python scripts/fetch-fonts.py
  python scripts/fetch-fonts.py --dry-run
  python scripts/fetch-fonts.py --out /path/to/fonts
  python scripts/fetch-fonts.py --force        # re-download existing files
"""

from __future__ import annotations

import argparse
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "oneirodex" / "static" / "library" / "fonts"

USER_AGENT = "Oneirodex-fetch-fonts/1.0 (+https://github.com/cephyrixzyth/oneirodex)"

# Leading bytes for each accepted container — mirrors theme_fonts._FONT_MAGIC.
# A 404 HTML page saved as .ttf would otherwise sit there looking installed.
FONT_MAGIC = (
    b"\x00\x01\x00\x00",  # TrueType
    b"true",              # TrueType (Apple)
    b"ttcf",              # TrueType collection
    b"OTTO",              # OpenType/CFF
    b"wOFF",              # WOFF
    b"wOF2",              # WOFF2
)

RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# (registry id, destination filename, url, licence, what it is for)
FONTS: list[tuple[str, str, str, str, str]] = [
    (
        "press-start",
        "PressStart2P-Regular.ttf",
        f"{RAW}/pressstart2p/PressStart2P-Regular.ttf",
        "SIL OFL 1.1",
        "8-bit — NES / SNES / Master System / PC Engine",
    ),
    (
        "silkscreen",
        "Silkscreen-Regular.ttf",
        f"{RAW}/silkscreen/Silkscreen-Regular.ttf",
        "SIL OFL 1.1",
        "compact pixel — Game Boy / Color / Advance, Game Gear",
    ),
    (
        "vt323",
        "VT323-Regular.ttf",
        f"{RAW}/vt323/VT323-Regular.ttf",
        "SIL OFL 1.1",
        "CRT terminal — MS-DOS / Amiga / C64",
    ),
    (
        "share-tech-mono",
        "ShareTechMono-Regular.ttf",
        f"{RAW}/sharetechmono/ShareTechMono-Regular.ttf",
        "SIL OFL 1.1",
        "arcade — Arcade / Neo Geo / Mega Drive / 32X",
    ),
    (
        "orbitron",
        "Orbitron-Variable.ttf",
        # Upstream ships Orbitron as a variable font only — there is no static
        # Bold. The registry declares a `weight` range for this face so the
        # @font-face exposes the axis rather than pinning one instance.
        f"{RAW}/orbitron/Orbitron%5Bwght%5D.ttf",
        "SIL OFL 1.1",
        "32-bit / disc — PS1 / PS2 / Saturn / Dreamcast / N64 / GameCube",
    ),
]

# Licence text sits beside the fonts, since the OFL requires it travel with them.
LICENSE_URLS = {
    "OFL.txt": f"{RAW}/pressstart2p/OFL.txt",
}


def _opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def _looks_like_font(head: bytes) -> bool:
    return any(head.startswith(sig) for sig in FONT_MAGIC)


def fetch(opener, url: str, dest: Path, *, expect_font: bool = True) -> tuple[bool, str]:
    try:
        with opener.open(url, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"unreachable ({exc.reason})"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"

    if not payload:
        return False, "empty response"
    if expect_font and not _looks_like_font(payload[:4]):
        # Almost always an HTML error page with a .ttf name.
        return False, "not a font file (upstream path may have moved)"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return True, f"{len(payload) / 1024:.0f} KB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="re-download files that already exist")
    args = parser.parse_args()

    out: Path = args.out
    print(f"Theme fonts -> {out}")
    print("All five are SIL Open Font License 1.1, from google/fonts.\n")

    if args.dry_run:
        for font_id, filename, url, licence, use in FONTS:
            print(f"  {font_id:16} {filename:28} {licence}")
            print(f"  {'':16} {use}")
            print(f"  {'':16} {url}\n")
        return 0

    opener = _opener()
    got, skipped, failed = 0, 0, []

    for font_id, filename, url, _licence, use in FONTS:
        dest = out / filename
        if dest.exists() and not args.force:
            print(f"  = {filename:28} already present")
            skipped += 1
            continue
        ok, detail = fetch(opener, url, dest)
        if ok:
            print(f"  + {filename:28} {detail}  ({use})")
            got += 1
        else:
            print(f"  ! {filename:28} {detail}")
            failed.append(f"{filename}: {detail}")

    for name, url in LICENSE_URLS.items():
        dest = out / name
        if not dest.exists() or args.force:
            ok, detail = fetch(opener, url, dest, expect_font=False)
            print(f"  {'+' if ok else '!'} {name:28} {detail}")

    print(f"\n{got} downloaded, {skipped} already present, {len(failed)} failed")
    if failed:
        for item in failed:
            print("  -", item)
        print("\nThe picker lists a face whose file is missing but reports")
        print("installed: false, so it will fall back rather than break.")
        return 1

    print("Restart is not required — the catalogue is read from disk per request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
