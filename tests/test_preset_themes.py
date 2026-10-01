"""Preset generation, staleness detection and content-aware theme syncing.

These tests are filesystem-only: they build a miniature theme source in tmp_path
and never touch the database or the real static/library/themes folder.
"""

import json
import os
import re
import shutil
import time

import pytest

from oneirodex.utils.preset_themes import (
    PRESET_MANAGED_FILES,
    PRESET_MARKER_KEY,
    PRESET_SLUGS,
    PRESET_THEMES,
    install_preset_themes,
    is_managed_preset,
    preset_needs_rebuild,
    preset_tokens,
    source_fingerprint,
    sync_preset_themes,
    sync_theme_tree,
)

BASE_CSS = """:root {
    --bg-dark-40: rgba(18, 22, 28, 0.92);
    --bg-dark-30: rgba(12, 16, 22, 0.96);
    --btn-primary: #ff5a36;
    --btn-primary-hover: #e04520;
    --od-accent: var(--btn-primary);
}
"""

TOKENS_CSS = """:root {
  --od-bg: #0b0d10;
  --od-surface: #141820;
  --od-surface-2: #1c2230;
  --od-text: #f2f4f8;
  --od-accent: #ff5a36;
  --od-accent-contrast: #0b0d10;
}
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


@pytest.fixture
def source_tree(tmp_path):
    """A miniature stand-in for oneirodex/setup/default_theme."""
    root = tmp_path / 'default_theme'
    write(str(root / 'theme.json'), json.dumps({
        'name': 'Default Theme',
        'author': 'Oneirodex',
        'description': 'Darker default theme for Oneirodex',
        'version': '2.1.0',
        'release_date': '2026-07-23',
    }))
    write(str(root / 'css' / 'base.css'), BASE_CSS)
    write(str(root / 'css' / 'od-tokens.css'), TOKENS_CSS)
    write(str(root / 'css' / 'admin' / 'admin_ops.css'), '.ops { color: red; }\n')
    write(str(root / 'css' / 'site' / 'sidebar.css'), '.sidebar { width: 10px; }\n')
    write(str(root / 'js' / 'app.js'), 'console.log("v1");\n')
    return root


@pytest.fixture
def themes_root(tmp_path):
    root = tmp_path / 'themes'
    root.mkdir()
    return root


def read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def accent_of(themes_root, slug):
    """The --od-accent value declared in a preset's own token file."""
    tokens = read(str(themes_root / slug / 'css' / 'od-tokens.css'))
    for line in tokens.splitlines():
        stripped = line.strip()
        if stripped.startswith('--od-accent:'):
            return stripped.split(':', 1)[1].strip().rstrip(';')
    return None


class TestPresetGeneration:
    def test_installs_every_preset(self, source_tree, themes_root):
        count = install_preset_themes(str(themes_root), str(source_tree))

        assert count == len(PRESET_THEMES)
        for slug in PRESET_SLUGS:
            assert (themes_root / slug / 'theme.json').is_file()

    def test_every_preset_gets_its_own_token_file(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        accents = {slug: accent_of(themes_root, slug) for slug in PRESET_SLUGS}
        assert all((themes_root / slug / 'css' / 'od-tokens.css').is_file() for slug in PRESET_SLUGS)
        assert len(set(accents.values())) == len(PRESET_SLUGS), accents
        assert '#ff5a36' not in accents.values()

    def test_token_accent_matches_preset_button_colour(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        for preset in PRESET_THEMES:
            assert accent_of(themes_root, preset['slug']) == preset['btn_primary']

    def test_tokens_carry_preset_background(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        aurora = read(str(themes_root / 'aurora' / 'css' / 'od-tokens.css'))
        assert '--od-bg: #061018;' in aurora
        assert '--od-surface: #0a1820;' in aurora
        # Wave 2d: presets override text / glass / icon geometry, not only accent.
        assert '--od-text: #e0f7fa;' in aurora
        assert '--od-icon-stroke: 2.75;' in aurora
        assert '--od-crt-opacity: 0.09;' in aurora

    def test_every_preset_pairs_an_icon_pack(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        packs = set()
        for preset in PRESET_THEMES:
            data = json.loads(read(str(themes_root / preset['slug'] / 'theme.json')))
            assert data.get('default_icon_pack') == preset['icon_pack']
            packs.add(preset['icon_pack'])
        # At least three distinct icon languages across the preset set.
        assert len(packs) >= 3

    def test_presets_diverge_beyond_accent(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        strokes = {
            slug: re.search(r'--od-icon-stroke:\s*([^;]+);', read(str(themes_root / slug / 'css' / 'od-tokens.css'))).group(1)
            for slug in PRESET_SLUGS
        }
        blurs = {
            slug: re.search(r'--od-glass-blur:\s*([^;]+);', read(str(themes_root / slug / 'css' / 'od-tokens.css'))).group(1)
            for slug in PRESET_SLUGS
        }
        assert len(set(strokes.values())) >= 4, strokes
        assert len(set(blurs.values())) >= 4, blurs

        radii = {
            slug: preset_tokens(next(p for p in PRESET_THEMES if p['slug'] == slug))['od-radius-md']
            for slug in PRESET_SLUGS
        }
        assert len(set(radii.values())) >= 4, radii

    def test_accent_contrast_flips_with_accent_brightness(self):
        light_accent = preset_tokens({'btn_primary': '#7dd3fc', 'bg_dark_30': '', 'bg_dark_40': ''})
        dark_accent = preset_tokens({'btn_primary': '#3b82f6', 'bg_dark_30': '', 'bg_dark_40': ''})

        assert light_accent['od-accent-contrast'] == '#0b0d10'
        assert dark_accent['od-accent-contrast'] == '#f2f4f8'

    def test_base_css_keeps_preset_button_colours(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        base = read(str(themes_root / 'ember' / 'css' / 'base.css'))
        assert '--btn-primary: #f472b6;' in base
        assert '--btn-primary-hover: #ec4899;' in base
        assert '--bg-dark-40: rgba(28, 10, 22, 0.94);' in base

    def test_shared_files_are_copied_verbatim(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        assert read(str(themes_root / 'ocean' / 'js' / 'app.js')) == read(str(source_tree / 'js' / 'app.js'))
        assert (themes_root / 'ocean' / 'css' / 'admin' / 'admin_ops.css').is_file()

    def test_missing_source_is_a_noop(self, tmp_path, themes_root):
        assert install_preset_themes(str(themes_root), str(tmp_path / 'nope')) == 0


class TestStalenessDetection:
    def test_up_to_date_presets_are_not_rebuilt(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        assert install_preset_themes(str(themes_root), str(source_tree)) == 0

    def test_changed_source_marks_presets_stale(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        write(str(source_tree / 'js' / 'app.js'), 'console.log("v2");\n')

        fingerprint = source_fingerprint(str(source_tree))
        preset = PRESET_THEMES[0]
        assert preset_needs_rebuild(str(themes_root / preset['slug']), preset, fingerprint)

    def test_new_source_file_marks_presets_stale(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        write(str(source_tree / 'css' / 'od-chrome.css'), '.chrome {}\n')

        rebuilt = install_preset_themes(str(themes_root), str(source_tree))

        assert rebuilt == len(PRESET_THEMES)
        assert (themes_root / 'violet' / 'css' / 'od-chrome.css').is_file()

    def test_rebuild_keeps_preset_colours(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        write(str(source_tree / 'css' / 'od-chrome.css'), '.chrome {}\n')
        install_preset_themes(str(themes_root), str(source_tree))

        assert accent_of(themes_root, 'violet') == '#a78bfa'
        assert '--btn-primary: #a78bfa;' in read(str(themes_root / 'violet' / 'css' / 'base.css'))

    @pytest.mark.parametrize('author', ['Oneirodex', 'Oneirodex'])
    def test_legacy_preset_without_marker_is_rebuilt(self, source_tree, themes_root, author):
        """Presets on disk from before the provenance marker — both public strings."""
        preset = PRESET_THEMES[0]
        legacy = themes_root / preset['slug']
        write(str(legacy / 'theme.json'), json.dumps({
            'name': preset['name'],
            'author': author,
            'description': preset['description'],
            'version': '1.0.0',
            'release_date': '2026-07-23',
        }))
        write(str(legacy / 'css' / 'base.css'), BASE_CSS)

        rebuilt = install_preset_themes(str(themes_root), str(source_tree))

        assert rebuilt == len(PRESET_THEMES)
        marker = json.loads(read(str(legacy / 'theme.json')))[PRESET_MARKER_KEY]
        assert marker['slug'] == preset['slug']
        assert (legacy / 'css' / 'od-tokens.css').is_file()

    def test_deleted_managed_file_forces_rebuild(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        os.remove(str(themes_root / 'mono' / 'css' / 'od-tokens.css'))

        rebuilt = install_preset_themes(str(themes_root), str(source_tree))

        assert rebuilt == 1
        assert accent_of(themes_root, 'mono') == '#94a3b8'

    def test_all_managed_files_are_generated(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))

        for rel in PRESET_MANAGED_FILES:
            assert (themes_root / 'rose' / rel.replace('/', os.sep)).is_file()


class TestCustomThemePreservation:
    @staticmethod
    def _install_custom_theme_at(themes_root, slug):
        write(str(themes_root / slug / 'theme.json'), json.dumps({
            'name': 'My Handmade Theme',
            'author': 'A User',
            'description': 'Uploaded through the admin UI',
            'version': '3.0.0',
            'release_date': '2026-01-01',
        }))
        write(str(themes_root / slug / 'css' / 'base.css'), '/* precious */\n')

    def test_uploaded_theme_on_a_preset_slug_is_left_alone(self, source_tree, themes_root):
        self._install_custom_theme_at(themes_root, 'aurora')

        rebuilt = install_preset_themes(str(themes_root), str(source_tree))

        assert rebuilt == len(PRESET_THEMES) - 1
        assert read(str(themes_root / 'aurora' / 'css' / 'base.css')) == '/* precious */\n'
        assert json.loads(read(str(themes_root / 'aurora' / 'theme.json')))['author'] == 'A User'

    def test_forced_reinstall_still_spares_uploaded_theme(self, source_tree, themes_root):
        self._install_custom_theme_at(themes_root, 'ice')

        install_preset_themes(str(themes_root), str(source_tree), force=True)

        assert read(str(themes_root / 'ice' / 'css' / 'base.css')) == '/* precious */\n'

    def test_sync_skips_uploaded_theme(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        shutil.rmtree(str(themes_root / 'forest'))
        self._install_custom_theme_at(themes_root, 'forest')
        write(str(source_tree / 'js' / 'app.js'), 'console.log("v2");\n')

        sync_preset_themes(str(themes_root), str(source_tree))

        assert not (themes_root / 'forest' / 'js' / 'app.js').is_file()

    def test_ownership_check(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        preset = next(p for p in PRESET_THEMES if p['slug'] == 'sunset')

        assert is_managed_preset(str(themes_root / 'sunset'), preset)

        self._install_custom_theme_at(themes_root, 'sunset')
        assert not is_managed_preset(str(themes_root / 'sunset'), preset)

    def test_unrelated_theme_folders_are_never_visited(self, source_tree, themes_root):
        write(str(themes_root / 'retrowave' / 'theme.json'), json.dumps({'name': 'Retrowave'}))
        write(str(themes_root / 'retrowave' / 'css' / 'base.css'), '/* neon */\n')

        install_preset_themes(str(themes_root), str(source_tree))
        sync_preset_themes(str(themes_root), str(source_tree))

        assert read(str(themes_root / 'retrowave' / 'css' / 'base.css')) == '/* neon */\n'
        assert not (themes_root / 'retrowave' / 'js').exists()


def _age_tree(*roots):
    """Backdate every file an hour, as a copy made on an earlier boot would be."""
    old = time.time() - 3600
    for root in roots:
        for path in root.rglob('*'):
            if path.is_file():
                os.utime(path, (old, old))


class TestContentAwareSync:
    def test_changed_source_file_propagates(self, source_tree, tmp_path):
        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))
        write(str(source_tree / 'css' / 'admin' / 'admin_ops.css'), '.ops { color: blue; }\n')

        written = sync_theme_tree(str(source_tree), str(target))

        assert written == 1
        assert read(str(target / 'css' / 'admin' / 'admin_ops.css')) == '.ops { color: blue; }\n'

    def test_locally_modified_file_is_restored(self, source_tree, tmp_path):
        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))
        write(str(target / 'js' / 'app.js'), 'console.log("tampered");\n')

        sync_theme_tree(str(source_tree), str(target))

        assert read(str(target / 'js' / 'app.js')) == 'console.log("v1");\n'

    def test_unchanged_tree_writes_nothing(self, source_tree, tmp_path):
        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))

        assert sync_theme_tree(str(source_tree), str(target)) == 0

    def test_an_old_untouched_copy_is_matched_without_reading_it(self, source_tree, tmp_path, monkeypatch):
        import oneirodex.utils.preset_themes as preset_themes

        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))
        _age_tree(source_tree, target)

        def no_reads(_path):
            raise AssertionError('an unchanged copy should not be opened')

        monkeypatch.setattr(preset_themes, 'file_digest', no_reads)
        assert sync_theme_tree(str(source_tree), str(target)) == 0

    def test_a_same_size_edit_is_still_caught(self, source_tree, tmp_path):
        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))
        _age_tree(source_tree, target)
        write(str(target / 'js' / 'app.js'), 'console.log("XX");\n')  # same length as "v1"
        assert os.path.getsize(target / 'js' / 'app.js') == os.path.getsize(source_tree / 'js' / 'app.js')

        assert sync_theme_tree(str(source_tree), str(target)) == 1
        assert read(str(target / 'js' / 'app.js')) == 'console.log("v1");\n'

    def test_protected_files_are_not_overwritten(self, source_tree, tmp_path):
        target = tmp_path / 'preset'
        sync_theme_tree(str(source_tree), str(target))
        write(str(target / 'css' / 'base.css'), '/* recoloured */\n')

        sync_theme_tree(str(source_tree), str(target), protected=PRESET_MANAGED_FILES)

        assert read(str(target / 'css' / 'base.css')) == '/* recoloured */\n'

    def test_extra_target_files_survive(self, source_tree, tmp_path):
        target = tmp_path / 'default'
        sync_theme_tree(str(source_tree), str(target))
        write(str(target / 'css' / 'local_extra.css'), '/* mine */\n')

        sync_theme_tree(str(source_tree), str(target))

        assert (target / 'css' / 'local_extra.css').is_file()

    def test_preset_sync_reaches_presets_without_undoing_colours(self, source_tree, themes_root):
        install_preset_themes(str(themes_root), str(source_tree))
        write(str(source_tree / 'js' / 'app.js'), 'console.log("v2");\n')

        written = sync_preset_themes(str(themes_root), str(source_tree))

        assert written == len(PRESET_THEMES)
        assert read(str(themes_root / 'ocean' / 'js' / 'app.js')) == 'console.log("v2");\n'
        assert accent_of(themes_root, 'ocean') == '#3b82f6'
        assert '--btn-primary: #3b82f6;' in read(str(themes_root / 'ocean' / 'css' / 'base.css'))
