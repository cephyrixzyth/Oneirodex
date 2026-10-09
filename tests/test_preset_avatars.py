"""The shipped avatars must stay recolourable.

The seven stock avatars are flat SVGs served as ``<img>``. They cannot inherit
``currentColor`` and cannot read a CSS custom property, so on every preset other
than the default they rendered in the default theme's green while the rest of
the UI changed around them — reported as "default avatars should have theme
ready versions for each one".

They are generated per preset instead, the same way ``od-tokens.css`` is:
:func:`_write_preset_avatars` substitutes three known source colours for the
preset's own. Straight substitution is only safe while the source art *stays*
inside those three colours, and nothing about editing an SVG makes that
obvious — a designer adding a highlight would produce art that silently
survives into all nine themes unrecoloured, and the only symptom would be one
avatar looking wrong on one theme.

So the palette is a contract, and this is the test that enforces it.
"""

from __future__ import annotations

import os
import re

from oneirodex.utils.preset_themes import (
    AVATAR_FILES,
    AVATAR_SOURCE_ACCENT,
    AVATAR_SOURCE_MUTED,
    AVATAR_SOURCE_PANEL,
    PRESET_AVATAR_FILES,
    PRESET_MANAGED_FILES,
    PRESET_THEMES,
    _write_preset_avatars,
    install_preset_themes,
    preset_tokens,
    sync_preset_themes,
)

SOURCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'oneirodex',
    'setup',
    'default_theme',
    'avatars',
)

ALLOWED = {
    AVATAR_SOURCE_ACCENT.lower(),
    AVATAR_SOURCE_PANEL.lower(),
    AVATAR_SOURCE_MUTED.lower(),
}

HEX = re.compile(r'#[0-9a-fA-F]{3,8}')


def test_every_declared_avatar_exists():
    missing = [n for n in AVATAR_FILES if not os.path.isfile(os.path.join(SOURCE_DIR, n))]
    assert missing == [], f'declared in AVATAR_FILES but not on disk: {missing}'


def test_source_avatars_use_only_the_recolourable_palette():
    """Every hex in the source art must be one the generator knows how to map."""
    strays: dict[str, set[str]] = {}
    for name in AVATAR_FILES:
        with open(os.path.join(SOURCE_DIR, name), encoding='utf-8') as fh:
            found = {value.lower() for value in HEX.findall(fh.read())}
        off_palette = found - ALLOWED
        if off_palette:
            strays[name] = off_palette

    assert strays == {}, (
        'These avatars use colours the preset generator will not recolour, so '
        'they would keep the default theme palette on every preset: '
        f'{strays}. Either use one of {sorted(ALLOWED)} or extend '
        'AVATAR_SOURCE_* and _write_preset_avatars together.'
    )


def test_generated_avatars_carry_the_preset_palette(tmp_path):
    """A generated avatar contains the preset's accent and none of the source's."""
    # Arcade Neon: the preset the original report named, and the one whose
    # accent (#22d3ee) is furthest from the source green.
    preset = next(p for p in PRESET_THEMES if p['slug'] == 'afterglow')
    target = tmp_path / 'afterglow'
    target.mkdir()

    _write_preset_avatars(os.path.dirname(SOURCE_DIR), str(target), preset)

    accent = preset_tokens(preset)['od-accent'].lower()
    for name in AVATAR_FILES:
        written = target / 'avatars' / name
        assert written.is_file(), f'{name} was not generated'
        svg = written.read_text(encoding='utf-8').lower()
        assert AVATAR_SOURCE_ACCENT.lower() not in svg, (
            f'{name} still carries the source accent after recolouring'
        )
        assert accent in svg, f'{name} does not carry the preset accent'


def test_generator_is_a_no_op_without_source_art(tmp_path):
    """An install predating the themed avatars must not raise, just do nothing."""
    preset = PRESET_THEMES[0]
    target = tmp_path / 'somewhere'
    target.mkdir()

    _write_preset_avatars(str(tmp_path / 'missing-source'), str(target), preset)

    assert not (target / 'avatars').exists()


# ---------------------------------------------------------------------------
# Generated-but-optional: the hazard of treating avatars as "managed"
# ---------------------------------------------------------------------------
#
# `PRESET_MANAGED_FILES` means two things at once — the sync must not overwrite
# these, *and* a preset missing one is stale. The avatars only ever wanted the
# first. Putting them in that tuple made their absence mean "stale", so a source
# tree with no `avatars/` folder rebuilt all nine presets on every boot, forever,
# chasing files the generator would never write. Hence `PRESET_AVATAR_FILES` and
# `PRESET_PROTECTED_FILES` as separate things.


def _bare_source(tmp_path):
    """A miniature source tree with no avatars — an older install, or a test."""
    root = tmp_path / 'default_theme'
    (root / 'css').mkdir(parents=True)
    (root / 'theme.json').write_text('{"name": "Default Theme"}', encoding='utf-8')
    (root / 'css' / 'base.css').write_text(
        ':root { --btn-primary: #ff5a36; --btn-primary-hover: #e04520; }\n',
        encoding='utf-8',
    )
    (root / 'css' / 'od-tokens.css').write_text(
        ':root { --od-accent: #ff5a36; }\n', encoding='utf-8'
    )
    return root


def _source_with_avatars(tmp_path):
    root = _bare_source(tmp_path)
    avatars = root / 'avatars'
    avatars.mkdir()
    for name in AVATAR_FILES:
        with open(os.path.join(SOURCE_DIR, name), encoding='utf-8') as fh:
            (avatars / name).write_text(fh.read(), encoding='utf-8')
    return root


def test_avatars_are_not_in_the_staleness_list():
    """Guards the split directly, so a future tidy-up cannot merge them back."""
    overlap = set(PRESET_AVATAR_FILES) & set(PRESET_MANAGED_FILES)
    assert overlap == set(), (
        'Avatars are generated only when the source ships them, so their '
        'absence must not mark a preset stale — see the note in preset_themes.'
    )


def test_a_source_without_avatars_does_not_rebuild_forever(tmp_path):
    source = _bare_source(tmp_path)
    themes = tmp_path / 'themes'
    themes.mkdir()

    first = install_preset_themes(str(themes), str(source))
    second = install_preset_themes(str(themes), str(source))

    assert first == len(PRESET_THEMES)
    # The whole point: nothing changed, so nothing is rebuilt.
    assert second == 0


def test_a_deleted_preset_avatar_is_restored(tmp_path):
    """The sync skips protected files, so only a rebuild can bring one back."""
    source = _source_with_avatars(tmp_path)
    themes = tmp_path / 'themes'
    themes.mkdir()
    install_preset_themes(str(themes), str(source))

    victim = themes / 'tape-deck' / 'avatars' / 'controller.svg'
    assert victim.is_file()
    victim.unlink()

    rebuilt = install_preset_themes(str(themes), str(source))

    assert rebuilt == 1
    assert victim.is_file()


def test_sync_does_not_overwrite_recoloured_avatars(tmp_path):
    """Otherwise every boot would put the default-green art back."""
    source = _source_with_avatars(tmp_path)
    themes = tmp_path / 'themes'
    themes.mkdir()
    install_preset_themes(str(themes), str(source))

    themed = (themes / 'tape-deck' / 'avatars' / 'controller.svg').read_text(encoding='utf-8')
    sync_preset_themes(str(themes), str(source))
    after = (themes / 'tape-deck' / 'avatars' / 'controller.svg').read_text(encoding='utf-8')

    assert after == themed
    assert AVATAR_SOURCE_ACCENT.lower() not in after.lower()
