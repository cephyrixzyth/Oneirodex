"""Phase 5 of the security/legal playbook — vendored code licensing (L1, L2, L3).

The notices test is the one that earns its keep: it fails when a *new* library is
vendored without a notice, which is how the eight already here came to have none.

See docs/strategy/security-legal-playbook.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR = REPO_ROOT / 'oneirodex' / 'static' / 'vendor'
NOTICES = VENDOR / 'THIRD-PARTY-NOTICES.md'


def _tracked(pattern: str) -> list[str]:
    # Per-command only — this checkout can sit on a UNC share where git
    # refuses ls-files as "dubious ownership" unless safe.directory is set.
    out = subprocess.run(
        ['git', '-c', 'safe.directory=*', 'ls-files', pattern],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


# --- L1: core binaries are out of the tree --------------------------------

class TestCoreBinariesNotTracked:
    def test_no_wasm_core_is_committed(self):
        """71MB of GPL / non-commercial WASM does not belong in the repo."""
        assert _tracked('oneirodex/static/vendor/webretro/cores/*_libretro.wasm') == []

    def test_no_core_loader_is_committed(self):
        assert _tracked('oneirodex/static/vendor/webretro/cores/*_libretro.js') == []

    def test_the_cores_readme_stays(self):
        """The directory still has to explain itself."""
        assert _tracked('oneirodex/static/vendor/webretro/cores/README.md')

    def test_gitignore_covers_both_halves(self):
        ignored = (REPO_ROOT / '.gitignore').read_text(encoding='utf-8')
        assert 'webretro/cores/*_libretro.js' in ignored
        assert 'webretro/cores/*_libretro.wasm' in ignored


# --- L3: third-party legal pages are gone ---------------------------------

class TestThirdPartyPagesRemoved:
    @pytest.mark.parametrize('name', [
        'tos.html', 'privacy.html', 'cookiepolicy.html', 'index.html', 'changelog.html',
    ])
    def test_upstream_legal_page_is_not_served(self, name):
        """Every deployment was serving another project's terms on its own domain."""
        assert not (VENDOR / 'webretro' / 'info' / name).exists()

    def test_info_directory_is_untracked(self):
        assert _tracked('oneirodex/static/vendor/webretro/info/*') == []

    def test_nothing_links_to_the_removed_pages(self):
        standalone = VENDOR / 'webretro' / 'standalone.html'
        assert 'href="info/"' not in standalone.read_text(encoding='utf-8', errors='replace')

    def test_the_emulator_frame_itself_survived(self):
        """standalone.html is the iframe webretro.html embeds — not dead weight."""
        assert (VENDOR / 'webretro' / 'standalone.html').is_file()
        webretro = (VENDOR / 'webretro' / 'webretro.html').read_text(
            encoding='utf-8', errors='replace'
        )
        assert 'standalone.html' in webretro

    def test_stray_debris_file_is_gone(self):
        assert not (VENDOR / 'webretro' / 'ddd.txt').exists()

    def test_only_one_sortablejs_version_remains(self):
        versions = sorted(p.name for p in (VENDOR / 'sortablejs').iterdir() if p.is_dir())
        assert versions == ['1.15.2']


# --- L2: every vendored library is accounted for --------------------------

class TestNotices:
    def test_notices_file_exists(self):
        assert NOTICES.is_file()

    def test_every_vendored_library_has_a_notice(self):
        """The ratchet: vendor something new without a notice and this fails."""
        text = NOTICES.read_text(encoding='utf-8')
        libraries = sorted(
            path.name for path in VENDOR.iterdir()
            if path.is_dir() and not path.name.startswith('.')
        )
        assert libraries, 'expected vendored libraries to be present'

        missing = [name for name in libraries if name.lower() not in text.lower()]
        assert missing == [], f'vendored without a notice: {missing}'

    def test_notices_carry_the_permission_text_not_just_a_label(self):
        """Naming the licence is not the same as including it."""
        text = NOTICES.read_text(encoding='utf-8')
        assert 'Permission is hereby granted' in text
        assert 'WITHOUT WARRANTY OF ANY KIND' in text

    def test_webretro_licence_is_mit_from_upstream(self):
        """The front end is MIT; cores stay operator-provisioned with their own terms."""
        text = NOTICES.read_text(encoding='utf-8')
        assert 'Verify before release' not in text
        assert 'Copyright (c) 2021 BinBashBanana' in text
        licence = VENDOR / 'webretro' / 'LICENSE'
        assert licence.is_file()
        body = licence.read_text(encoding='utf-8')
        assert 'MIT License' in body
        assert 'Copyright (c) 2021 BinBashBanana' in body

    def test_licence_fetch_script_is_executable_and_covers_the_tree(self):
        script = REPO_ROOT / 'scripts' / 'fetch-vendor-licenses.sh'
        assert script.is_file()
        body = script.read_text(encoding='utf-8')
        for name in ('bootstrap', 'jquery', 'sortablejs', 'datatables', 'cropperjs', 'webretro', 'nostalgist'):
            assert name in body
        assert 'BinBashBanana/webretro' in body
        assert 'arianrhodsandlot/nostalgist' in body


# --- Load sites: heavy vendor JS stays off the member shell ---------------

_DATATABLES_PATH = 'vendor/datatables/'
_CROPPER_PATH = 'vendor/cropperjs/'


class TestVendorLoadSites:
    def test_member_and_admin_shells_do_not_load_datatables_or_cropper(self):
        """Shared shells avoid loading table and image-cropper vendors."""
        for name in ('member_spa.py', 'admin_spa.py'):
            text = (REPO_ROOT / 'oneirodex' / 'utils' / name).read_text(encoding='utf-8')
            assert _DATATABLES_PATH not in text, name
            assert _CROPPER_PATH not in text, name

    def test_no_server_template_tree_remains(self):
        templates = REPO_ROOT / 'oneirodex' / 'templates'
        assert not templates.exists() or not list(templates.rglob('*.html'))

    def test_no_server_template_adapter_is_generated(self):
        generator = (REPO_ROOT / 'scripts' / 'generate_icon_adapters.py').read_text(encoding='utf-8')
        assert 'generate_jinja' not in generator
        assert 'JINJA_OUTPUT' not in generator
