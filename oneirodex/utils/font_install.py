"""Install the built-in theme fonts.

The faces ship *with* Oneirodex, in ``oneirodex/setup/fonts``. Installing them
is a file copy onto the library volume, and the network is only a fallback for
a face the bundle happens not to carry.

It did not used to be. The faces were fetched from ``google/fonts`` at first
boot and nothing else, so an install behind a proxy, on an air-gapped box, or
simply one where the fetch failed quietly ended up with a picker offering five
fonts and shipping none of them — every entry reading "not installed", with the
remedy being a script nobody knew to run. Downloading an asset we are allowed to
redistribute, in order to have it locally, was the wrong shape: it made a
cosmetic feature depend on the internet and on an admin.

The runtime location is a Docker volume in production, so a copy on every boot
is what keeps a fresh volume populated — ``oneirodex/static/library/fonts`` is
deliberately gitignored, like the rest of that tree.

All faces are SIL Open Font License 1.1 from the official ``google/fonts``
repository. ``OFL.txt`` travels with them and is copied alongside, because
redistributing them without the licence text is not permitted.
"""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request

#: Tracked directory the faces ship in, resolved relative to the package rather
#: than the process CWD — uvicorn and Docker do not agree on the latter.
BUNDLED_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'setup', 'fonts'
)

#: Files copied beside the faces. The licence is not optional.
BUNDLED_EXTRAS = ('OFL.txt',)

RAW = 'https://raw.githubusercontent.com/google/fonts/main/ofl'

USER_AGENT = 'Oneirodex-font-install/1.0 (+https://github.com/cephyrixzyth/oneirodex)'

#: ``(filename, url)`` for every built-in face that ships as a file.
#: Keep in step with ``BUILT_IN_FONTS`` in :mod:`oneirodex.utils.theme_fonts`;
#: :func:`missing_builtin_fonts` reads that registry rather than this table, so a
#: face added there without a source here is reported, not silently skipped.
FONT_SOURCES: dict[str, str] = {
    'PressStart2P-Regular.ttf': f'{RAW}/pressstart2p/PressStart2P-Regular.ttf',
    'Silkscreen-Regular.ttf': f'{RAW}/silkscreen/Silkscreen-Regular.ttf',
    'VT323-Regular.ttf': f'{RAW}/vt323/VT323-Regular.ttf',
    'ShareTechMono-Regular.ttf': f'{RAW}/sharetechmono/ShareTechMono-Regular.ttf',
    'Orbitron-Variable.ttf': f'{RAW}/orbitron/Orbitron%5Bwght%5D.ttf',
}

#: TrueType, OpenType, and the two WOFF wrappers.
_FONT_MAGIC = (b'\x00\x01\x00\x00', b'OTTO', b'true', b'ttcf', b'wOFF', b'wOF2')


def _looks_like_font(head: bytes) -> bool:
    return any(head.startswith(magic) for magic in _FONT_MAGIC)


def missing_builtin_fonts(root: str) -> list[str]:
    """Built-in font filenames not present under *root*."""
    from oneirodex.utils.theme_fonts import BUILT_IN_FONTS

    missing = []
    for entry in BUILT_IN_FONTS.values():
        name = entry.get('file')
        if name and not os.path.isfile(os.path.join(root, name)):
            missing.append(name)
    return missing


def seed_builtin_fonts(root: str, *, force: bool = False) -> int:
    """Copy bundled faces into *root*. Returns files written.

    The whole point of preloading: no network, no admin, no ordering
    requirement. Safe to call on every boot — it only writes what is missing
    unless *force* is set.
    """
    if not os.path.isdir(BUNDLED_FONTS_DIR):
        return 0

    os.makedirs(root, exist_ok=True)
    wanted = list(FONT_SOURCES) if force else missing_builtin_fonts(root)
    written = 0

    for name in [*wanted, *BUNDLED_EXTRAS]:
        source = os.path.join(BUNDLED_FONTS_DIR, name)
        dest = os.path.join(root, name)
        if not os.path.isfile(source):
            continue
        if os.path.isfile(dest) and not force and name in BUNDLED_EXTRAS:
            continue
        try:
            shutil.copyfile(source, dest)
        except OSError:
            # A read-only or full volume costs the face, not the boot.
            continue
        if name not in BUNDLED_EXTRAS:
            written += 1

    return written


def install_builtin_fonts(root: str, *, force: bool = False) -> int:
    """Ensure every built-in face exists under *root*. Returns files written.

    Bundle first, network second. The download is kept for a face registered in
    ``BUILT_IN_FONTS`` that the bundle does not carry — adding one to the
    registry should not need a release to be usable — but on a normal install
    the copy satisfies everything and nothing is fetched at all.

    Never raises for a single failure: a face that does not arrive falls through
    to the next family in its CSS stack, so one unreachable URL or one
    unwritable file should cost one font rather than the whole install.
    """
    os.makedirs(root, exist_ok=True)

    written = seed_builtin_fonts(root, force=force)

    remaining = list(FONT_SOURCES) if force else missing_builtin_fonts(root)
    if not remaining:
        return written

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', USER_AGENT)]

    for name in remaining:
        url = FONT_SOURCES.get(name)
        if not url:
            # Registered face with no source here — worth knowing about, but not
            # worth failing the others for.
            continue
        dest = os.path.join(root, name)
        try:
            with opener.open(url, timeout=60) as response:
                payload = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue

        # An HTML error page with a .ttf name is the usual failure, and writing
        # it would leave a file that exists, never renders, and stops this
        # function ever retrying.
        if not payload or not _looks_like_font(payload[:4]):
            continue

        with open(dest, 'wb') as handle:
            handle.write(payload)
        written += 1

    return written
