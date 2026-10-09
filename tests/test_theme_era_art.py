"""Drawn room art per theme (THEME-AI first pass).

The pre-37 rooms were gradients only, which is why fifteen presets read as one
room fifteen times. Each era now ships an authored SVG scene that the era CSS
paints as its own layer, and the generator recolours a single sentinel per
preset so the screen glow follows the theme while the room keeps its era
palette.

Three things have to hold or the feature silently stops working:

1. every era named by a preset has art, and the CSS points at it;
2. the art stays inside the sentinel contract (a second themed colour would
   survive into every preset unrecoloured — the same trap
   `test_preset_avatars.py` guards for avatars);
3. a preset generated from a source tree *with* art gets the art, and one
   generated from a tree *without* it is not permanently stale.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from oneirodex.utils.preset_themes import (
    ART_ACCENT_SENTINEL,
    ERA_ART_FILES,
    GENERATOR_VERSION,
    PRESET_ART_FILES,
    PRESET_PROTECTED_FILES,
    PRESET_THEMES,
    DEFAULT_ERA,
    build_preset,
    install_preset_themes,
    preset_needs_rebuild,
    preset_tokens,
    source_fingerprint,
    sync_preset_themes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME_SOURCE = REPO_ROOT / 'oneirodex' / 'setup' / 'default_theme'
ART_DIR = THEME_SOURCE / 'art' / 'era'
ERA_CSS = (THEME_SOURCE / 'css' / 'od-era.css').read_text(encoding='utf-8')


def test_every_era_a_preset_names_has_art():
    eras = {str(preset.get('era') or DEFAULT_ERA) for preset in PRESET_THEMES}
    eras.add(DEFAULT_ERA)
    shipped = {name[: -len('.svg')] for name in ERA_ART_FILES}
    assert eras <= shipped, f'eras with no room art: {sorted(eras - shipped)}'
    for name in ERA_ART_FILES:
        assert (ART_DIR / name).is_file(), f'{name} is declared but not shipped'


def test_css_paints_each_era_from_its_own_theme_folder():
    """The URL is relative on purpose: it resolves inside the preset's folder."""
    assert '.od-era-scene' in ERA_CSS
    assert 'var(--od-era-scene, none)' in ERA_CSS
    for name in ERA_ART_FILES:
        era = name[: -len('.svg')]
        assert f"--od-era-scene: url('../art/era/{era}.svg')" in ERA_CSS, era
        # A layer with no opacity is a layer nobody sees.
        block = ERA_CSS.split(f"--od-era-scene: url('../art/era/{era}.svg')", 1)[1][:200]
        assert '--od-era-scene-opacity' in block, era
    # Absolute URLs would pin every preset to the default theme's copy.
    assert "url('/static/library/themes" not in ERA_CSS


def test_the_atmosphere_partial_has_the_scene_layer():
    partial = (REPO_ROOT / 'oneirodex' / 'templates' / 'partials' / 'era_atmosphere.html').read_text(
        encoding='utf-8',
    )
    assert 'od-era-scene' in partial
    # Behind the window/posters/furniture, in front of the wall.
    assert partial.index('od-era-wall') < partial.index('od-era-scene') < partial.index('od-era-window')


def test_scene_motion_respects_reduced_motion():
    reduced = ERA_CSS.split('prefers-reduced-motion', 1)
    assert len(reduced) > 1, 'the scene layer animates and must honour reduced motion'
    assert 'od-era-scene' in reduced[1][:400]


def test_art_is_valid_svg_sized_for_the_layer():
    for name in ERA_ART_FILES:
        path = ART_DIR / name
        root = ET.parse(path).getroot()
        assert root.tag.endswith('svg'), name
        assert root.get('viewBox') == '0 0 1600 900', f'{name} must be 16:9 at 1600x900'
        assert root.get('preserveAspectRatio') == 'xMidYMid slice', name
        # Backdrops ship in the image; keep them cheap.
        assert path.stat().st_size < 60_000, f'{name} is {path.stat().st_size} bytes'


def test_art_carries_exactly_one_themed_colour():
    """The sentinel contract, enforced the way the avatar palette is.

    A second colour meant to follow the theme would survive into every preset
    unrecoloured, and the only symptom would be "that one room looks wrong on
    that one theme".
    """
    for name in ERA_ART_FILES:
        text = (ART_DIR / name).read_text(encoding='utf-8')
        assert re.search(re.escape(ART_ACCENT_SENTINEL), text, re.IGNORECASE), (
            f'{name} has nothing that follows the theme accent'
        )
        assert 'href="http' not in text and 'xlink:href="http' not in text, (
            f'{name} loads something off this box'
        )


def test_build_preset_recolours_only_the_sentinel(tmp_path):
    preset = next(p for p in PRESET_THEMES if p['slug'] == 'afterglow')
    target = tmp_path / 'afterglow'
    build_preset(str(THEME_SOURCE), str(target), preset, 'fp')

    accent = preset_tokens(preset)['od-accent']
    assert accent.lower() != ART_ACCENT_SENTINEL.lower()

    for name in ERA_ART_FILES:
        built = (target / 'art' / 'era' / name).read_text(encoding='utf-8')
        source = (ART_DIR / name).read_text(encoding='utf-8')
        assert ART_ACCENT_SENTINEL.lower() not in built.lower(), name
        assert accent in built, name
        # Everything else is byte-identical: the room keeps its era palette.
        assert re.sub(re.escape(accent), ART_ACCENT_SENTINEL, built, flags=re.IGNORECASE) == source


def test_art_is_protected_from_the_sync_pass(tmp_path):
    """Sync must not copy the source art back over a preset's recoloured copy."""
    assert set(PRESET_ART_FILES) <= set(PRESET_PROTECTED_FILES)

    themes = tmp_path / 'themes'
    themes.mkdir()
    install_preset_themes(str(themes), str(THEME_SOURCE))
    art = themes / 'afterglow' / 'art' / 'era' / 'wood_den_80s.svg'
    recoloured = art.read_text(encoding='utf-8')
    sync_preset_themes(str(themes), str(THEME_SOURCE))
    assert art.read_text(encoding='utf-8') == recoloured


def test_missing_art_in_the_source_is_not_permanent_staleness(tmp_path):
    """An install whose source predates the art must not rebuild forever."""
    source = tmp_path / 'source'
    source.mkdir()
    for rel in ('theme.json', 'css/base.css', 'css/od-tokens.css'):
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{}' if rel.endswith('.json') else '/* x */', encoding='utf-8')

    preset = next(p for p in PRESET_THEMES if p['slug'] == 'afterglow')
    target = tmp_path / 'afterglow'
    fingerprint = source_fingerprint(str(source))
    build_preset(str(source), str(target), preset, fingerprint)

    assert not (target / 'art').exists()
    assert preset_needs_rebuild(str(target), preset, fingerprint, str(source)) is False


def test_a_preset_missing_its_art_rebuilds(tmp_path):
    preset = next(p for p in PRESET_THEMES if p['slug'] == 'greenhouse')
    target = tmp_path / 'greenhouse'
    fingerprint = source_fingerprint(str(THEME_SOURCE))
    build_preset(str(THEME_SOURCE), str(target), preset, fingerprint)
    assert preset_needs_rebuild(str(target), preset, fingerprint, str(THEME_SOURCE)) is False

    os.remove(target / 'art' / 'era' / 'desk.svg')
    assert preset_needs_rebuild(str(target), preset, fingerprint, str(THEME_SOURCE)) is True


def test_generator_version_moved_for_this_change():
    """Room art only reaches the volume when the version forces a rebuild."""
    assert GENERATOR_VERSION >= 37


def test_loading_motifs_read_the_platform_accent():
    """E2: a console's motif carries that console's colour, not the theme's.

    Every motif is `currentColor`, and `--od-platform-accent` is already set on
    <html> per system family by platformSkins. The motifs simply never read it,
    so a Mega Drive cabinet span in the theme accent like everything else. The
    fallback keeps every non-system page exactly as it was.
    """
    css = (THEME_SOURCE / 'css' / 'od-loading-motifs.css').read_text(encoding='utf-8')
    assert 'color: var(--od-platform-accent, var(--od-accent));' in css
    assert GENERATOR_VERSION >= 38, 'motif CSS ships on the volume — bump so presets rebuild'
