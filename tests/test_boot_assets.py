"""An install should arrive with its fonts and firmware.

Both capabilities existed as scripts — `scripts/fetch-fonts.py` and
`scripts/import_bios.py` — and nothing called either. The result was a font
picker offering five faces and shipping none (`available_fonts()` honestly
reporting `installed: False` for each), and a populated local firmware folder
that the Emulators page still reported as empty.

The logic is now importable so boot can use it and the scripts stay the manual
path. These tests cover the importable half: no network, no database.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------

def test_every_builtin_font_file_has_a_source(app):
    """A face registered without a download URL would report missing forever
    and never explain why."""
    from oneirodex.utils.font_install import FONT_SOURCES
    from oneirodex.utils.theme_fonts import BUILT_IN_FONTS

    registered = {e['file'] for e in BUILT_IN_FONTS.values() if e.get('file')}
    assert registered, 'no built-in faces ship files any more'
    assert registered <= set(FONT_SOURCES), (
        f'no source for: {sorted(registered - set(FONT_SOURCES))}'
    )


def test_missing_builtin_fonts_reports_only_absent_files(tmp_path, app):
    from oneirodex.utils.font_install import missing_builtin_fonts
    from oneirodex.utils.theme_fonts import BUILT_IN_FONTS

    names = [e['file'] for e in BUILT_IN_FONTS.values() if e.get('file')]
    assert missing_builtin_fonts(str(tmp_path)) == names

    (tmp_path / names[0]).write_bytes(b'\x00\x01\x00\x00stub')
    assert names[0] not in missing_builtin_fonts(str(tmp_path))


@pytest.fixture
def without_the_bundle(tmp_path, monkeypatch):
    """Neutralise the bundled faces so the **network fallback** is what runs.

    ``install_builtin_fonts`` is bundle-first: ``seed_builtin_fonts`` satisfies
    all five faces from ``oneirodex/setup/fonts``, ``remaining`` comes back
    empty, and the download beneath it never executes. The two tests below were
    written when the network was the only path, so as written neither reached
    the code it names — one failed on the five bundled copies it did not expect,
    and the other passed without its fake opener ever being called.

    Pointing ``BUNDLED_FONTS_DIR`` at a path that does not exist makes
    ``seed_builtin_fonts`` return 0 immediately, which is the smallest seam that
    restores what these tests were for. The bundle path itself is covered by
    ``tests/test_font_bundle.py``.
    """
    import oneirodex.utils.font_install as font_install

    monkeypatch.setattr(
        font_install, 'BUNDLED_FONTS_DIR', str(tmp_path / 'deliberately-absent')
    )
    return font_install


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Counts calls, so a test cannot silently stop exercising the network."""

    addheaders: list = []

    def __init__(self, payload: bytes):
        self._payload = payload
        self.calls = 0

    def open(self, url, timeout=None):
        self.calls += 1
        return _FakeResponse(self._payload)


def test_install_rejects_an_html_error_page(tmp_path, app, monkeypatch, without_the_bundle):
    """The usual upstream failure is an HTML page served under a .ttf name.
    Writing it would leave a file that exists, never renders, and stops this
    ever retrying — the worst of the three outcomes."""
    font_install = without_the_bundle
    opener = _FakeOpener(b'<!doctype html><title>404</title>')
    monkeypatch.setattr(font_install.urllib.request, 'build_opener', lambda: opener)

    written = font_install.install_builtin_fonts(str(tmp_path))

    assert opener.calls == len(font_install.FONT_SOURCES), (
        'the download path never ran, so this asserts nothing'
    )
    assert written == 0
    assert list(tmp_path.iterdir()) == []


def test_install_writes_a_real_font(tmp_path, app, monkeypatch, without_the_bundle):
    font_install = without_the_bundle
    opener = _FakeOpener(b'\x00\x01\x00\x00' + b'x' * 64)
    monkeypatch.setattr(font_install.urllib.request, 'build_opener', lambda: opener)

    written = font_install.install_builtin_fonts(str(tmp_path))

    assert opener.calls == len(font_install.FONT_SOURCES)
    assert written == len(font_install.FONT_SOURCES)
    # And a second call is a no-op, so boot does not re-download every start.
    assert font_install.install_builtin_fonts(str(tmp_path)) == 0


def test_bundle_short_circuits_the_download(tmp_path, app, monkeypatch):
    """The shipped behaviour, asserted where the fallback tests used to imply it.

    On a normal install the bundle satisfies every face and the network is never
    touched — which is exactly why the two tests above have to remove the bundle
    to reach it.
    """
    import oneirodex.utils.font_install as font_install

    def _no_network():
        raise AssertionError('install_builtin_fonts reached the network')

    monkeypatch.setattr(font_install.urllib.request, 'build_opener', _no_network)

    written = font_install.install_builtin_fonts(str(tmp_path))
    assert written == len(font_install.FONT_SOURCES)


# --------------------------------------------------------------------------
# Firmware
# --------------------------------------------------------------------------

def test_scan_finds_firmware_in_subdirectories(app, tmp_path):
    """Collections arrive organised per system. A flat listing missing them is
    the same bug the serving-side discovery fix addressed."""
    from oneirodex.utils.bios_install import scan_for_firmware, wanted_firmware_names

    name = next(iter(wanted_firmware_names().values()))
    nested = tmp_path / 'psx' / 'variants'
    nested.mkdir(parents=True)
    (nested / name).write_bytes(b'firmware')

    found = scan_for_firmware(str(tmp_path))
    assert name in found


def test_import_copies_missing_and_never_overwrites(app, tmp_path):
    """Safe to run on every boot: tops up gaps, leaves installed files alone —
    including firmware an operator deliberately swapped."""
    from oneirodex.utils.bios_install import import_bios_from, wanted_firmware_names

    names = list(wanted_firmware_names().values())[:2]
    source = tmp_path / 'src'
    dest = tmp_path / 'dest'
    source.mkdir()
    dest.mkdir()
    for name in names:
        (source / name).write_bytes(b'from-source')

    # One already present, deliberately different.
    (dest / names[0]).write_bytes(b'operator-supplied')

    copied = import_bios_from(str(source), str(dest))

    assert copied == 1
    assert (dest / names[0]).read_bytes() == b'operator-supplied'
    assert (dest / names[1]).read_bytes() == b'from-source'


def test_import_is_idempotent(app, tmp_path):
    from oneirodex.utils.bios_install import import_bios_from, wanted_firmware_names

    name = next(iter(wanted_firmware_names().values()))
    source = tmp_path / 'src'
    dest = tmp_path / 'dest'
    source.mkdir()
    (source / name).write_bytes(b'firmware')

    assert import_bios_from(str(source), str(dest)) == 1
    assert import_bios_from(str(source), str(dest)) == 0


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def test_boot_calls_both_installers():
    """Source guard: the whole point is that these stopped being scripts nobody
    ran. Importable helpers that boot never calls would be the same bug."""
    source = (ROOT / 'oneirodex' / 'init_data.py').read_text(encoding='utf-8')
    assert 'initialize_theme_fonts()' in source
    assert 'initialize_emulator_bios()' in source


def test_font_install_is_configurable_and_off_the_boot_path():
    """It downloads over the network. A slow or firewalled host must not become
    a slow or failed startup."""
    source = (ROOT / 'oneirodex' / 'init_data.py').read_text(encoding='utf-8')
    assert 'FETCH_FONTS_ON_BOOT' in source
    assert 'run_in_background' in source

    config = (ROOT / 'config.py').read_text(encoding='utf-8')
    assert 'FETCH_FONTS_ON_BOOT' in config
    assert 'BIOS_IMPORT_SOURCE' in config


def _run_bios_script_alone(cwd, code, **env):
    """Run Python in a fresh interpreter that has neither the oneirodex package
    on its path nor SECRET_KEY, the way an operator runs the script."""
    import subprocess
    import sys

    clean = {k: v for k, v in os.environ.items()
             if k not in ('PYTHONPATH', 'SECRET_KEY', 'ONEIRODEX_LIBRARY_DIR', 'EMULATOR_BIOS_PATH')}
    clean.update(env)
    return subprocess.run([sys.executable, '-c', code], cwd=cwd, env=clean,
                          capture_output=True, text=True, timeout=60)


def test_import_bios_script_starts_without_the_app_package(tmp_path):
    """It loads its helpers by path so it runs without SECRET_KEY; a top-level
    `from oneirodex...` import in one of them broke that unnoticed."""
    script = ROOT / 'scripts' / 'import_bios.py'
    done = _run_bios_script_alone(
        tmp_path, f'import runpy, sys; sys.argv = ["import_bios.py", "--help"]; runpy.run_path({str(script)!r}, run_name="__main__")'
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert '--source' in done.stdout


def test_import_bios_script_follows_a_moved_library(tmp_path):
    script = ROOT / 'scripts' / 'import_bios.py'
    load = (f'import importlib.util; spec = importlib.util.spec_from_file_location("s", {str(script)!r}); '
            'm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.DEFAULT_DEST)')
    data = tmp_path / 'data'
    moved = _run_bios_script_alone(tmp_path, load, ONEIRODEX_LIBRARY_DIR=str(data))
    assert moved.returncode == 0, moved.stderr[-2000:]
    assert moved.stdout.strip() == os.path.join(os.path.abspath(data), 'bios')
    default = _run_bios_script_alone(tmp_path, load)
    assert default.stdout.strip() == str(ROOT / 'oneirodex' / 'static' / 'library' / 'bios')
