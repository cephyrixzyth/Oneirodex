"""Theme fonts ship with the product; installing them must not need the network.

The regression this guards is a whole feature reading as broken: the font picker
lists five faces and reports `installed: False` for any whose file is absent, and
the only thing that ever wrote those files was a background download from
google/fonts run once at the end of first-run setup. A proxy, an air-gapped
host, an install already past setup, or a fetch that failed quietly all ended
with a picker offering five fonts and shipping none — with the remedy being a
script nobody knew to run.
"""

import os
import hashlib

import pytest

from oneirodex.utils.font_install import (
    BUNDLED_EXTRAS,
    BUNDLED_FONTS_DIR,
    missing_builtin_fonts,
    seed_builtin_fonts,
)
from oneirodex.utils.theme_fonts import BUILT_IN_FONTS


def test_every_registered_face_ships_in_the_bundle():
    """A face in the picker with no file beside it is one nobody can select."""
    registered = {
        entry['file'] for entry in BUILT_IN_FONTS.values() if entry.get('file')
    }
    bundled = set(os.listdir(BUNDLED_FONTS_DIR)) if os.path.isdir(BUNDLED_FONTS_DIR) else set()

    assert registered, 'BUILT_IN_FONTS carries no file-backed faces at all'
    assert registered <= bundled, (
        f'not bundled: {sorted(registered - bundled)} — add the file to '
        f'{BUNDLED_FONTS_DIR} or drop the entry from BUILT_IN_FONTS'
    )


def test_the_licence_travels_with_the_faces():
    """These are OFL 1.1 fonts; redistributing them without OFL.txt is not allowed."""
    for name in BUNDLED_EXTRAS:
        assert os.path.isfile(os.path.join(BUNDLED_FONTS_DIR, name)), name


def test_bundled_faces_match_reviewed_sha256_digests():
    from oneirodex.utils.font_install import FONT_SHA256

    for name, expected in FONT_SHA256.items():
        with open(os.path.join(BUNDLED_FONTS_DIR, name), 'rb') as handle:
            assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected, name


def test_seeding_installs_every_face_with_no_network(tmp_path, monkeypatch):
    """The copy is the install path. Any socket use here is the bug returning."""
    import oneirodex.utils.font_install as font_install

    def _no_network(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError('seed_builtin_fonts must not touch the network')

    monkeypatch.setattr(font_install, 'safe_get', _no_network)

    root = str(tmp_path / 'fonts')
    written = seed_builtin_fonts(root)

    assert written == len(
        [e for e in BUILT_IN_FONTS.values() if e.get('file')]
    )
    assert missing_builtin_fonts(root) == []


def test_seeding_is_safe_to_repeat_every_boot(tmp_path):
    """It runs on every startup so a fresh Docker volume repopulates itself."""
    root = str(tmp_path / 'fonts')
    seed_builtin_fonts(root)

    assert seed_builtin_fonts(root) == 0
    assert missing_builtin_fonts(root) == []


def test_seeded_files_are_real_fonts(tmp_path):
    """A truncated or HTML-bodied .ttf exists, never renders, and hides itself."""
    from oneirodex.utils.font_install import _looks_like_font

    root = str(tmp_path / 'fonts')
    seed_builtin_fonts(root)

    for entry in BUILT_IN_FONTS.values():
        name = entry.get('file')
        if not name:
            continue
        with open(os.path.join(root, name), 'rb') as handle:
            assert _looks_like_font(handle.read(4)), name


def test_seed_skips_bundled_font_with_unexpected_digest(tmp_path, monkeypatch):
    import oneirodex.utils.font_install as font_install

    source = tmp_path / 'bundle'
    source.mkdir()
    name = next(iter(font_install.FONT_SOURCES))
    (source / name).write_bytes(b'\x00\x01\x00\x00tampered')
    monkeypatch.setattr(font_install, 'BUNDLED_FONTS_DIR', str(source))
    monkeypatch.setattr(font_install, 'FONT_SHA256', {name: '0' * 64})

    assert seed_builtin_fonts(str(tmp_path / 'target')) == 0
    assert not (tmp_path / 'target' / name).exists()


def test_an_unwritable_target_costs_the_font_not_the_boot(tmp_path, monkeypatch):
    """Cosmetics must never take a server down — a face degrades to the next
    family in its CSS stack, which is the whole reason `stack` is a full CSS
    font-family value."""
    import shutil

    def _boom(*args, **kwargs):
        raise OSError('read-only volume')

    monkeypatch.setattr(shutil, 'copyfile', _boom)

    assert seed_builtin_fonts(str(tmp_path / 'fonts')) == 0
