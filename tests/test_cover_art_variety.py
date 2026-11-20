"""Generated covers must differ from each other (GT-B28 · UID-011).

Reported symptom: "every image looks the same". The palette *was* seeded per
title, but the composition never varied — every cover ran one fixed sequence
(gradient, bands, orbs, bezel, centred initials), so two games produced the
same picture in two colours.

Variety has to be structural. These assert that different titles get different
compositions, that a given title is stable across regenerations, and that the
gating actually removed the furniture which used to appear on everything.
"""

import pytest

from oneirodex.utils.cover_art_studio import (
    ART_DIRECTIONS,
    _title_seed,
    pick_art_direction,
)


def test_directions_are_gaming_specific():
    """The brief was console/arcade hardware, not generic abstract shapes."""
    assert set(ART_DIRECTIONS) == {
        'cartridge', 'marquee', 'crt', 'pixel', 'boxart', 'neon',
    }


def test_a_title_always_gets_the_same_direction():
    """Regenerating a cover must not silently redraw it as something else."""
    for title in ('Chrono Trigger', 'DOOM', 'Celeste'):
        seed = _title_seed(title)
        assert pick_art_direction(seed) == pick_art_direction(seed)


def test_a_realistic_library_uses_most_directions():
    """The actual complaint: many titles, one look.

    A handful of games should not all land on the same composition. This is the
    property that was broken — not that any single cover was wrong.
    """
    titles = [
        'Super Metroid', 'Chrono Trigger', 'DOOM', 'Celeste', 'Hollow Knight',
        'Half-Life', 'Portal', 'Hades', 'Stardew Valley', 'Factorio',
        'Terraria', 'Undertale', 'Bastion', 'Braid', 'Limbo', 'Inside',
        'Cuphead', 'Katana Zero', 'Dead Cells', 'Ori and the Blind Forest',
    ]
    used = {pick_art_direction(_title_seed(t)) for t in titles}

    # Not demanding all six from twenty titles — that would be asserting the
    # hash is perfectly uniform — but a real spread rather than one or two.
    assert len(used) >= 4, f'only {len(used)} distinct compositions across 20 titles: {used}'


def test_distribution_is_not_degenerate():
    """Guards a hashing change that quietly collapses everything onto one look."""
    from collections import Counter

    counts = Counter(
        pick_art_direction(_title_seed(f'Game Title {n}')) for n in range(600)
    )

    assert len(counts) == len(ART_DIRECTIONS), 'some directions are unreachable'
    # No single direction should own more than half the library.
    assert max(counts.values()) < 300, f'skewed distribution: {counts}'


@pytest.mark.parametrize('direction', ['crt', 'boxart', 'marquee', 'workbench', 'cartridge'])
def test_frame_is_applied_only_when_the_composition_needs_it(direction, monkeypatch):
    from oneirodex.utils import cover_art_studio
    calls = []
    monkeypatch.setattr(cover_art_studio, '_draw_bezel_frame', lambda *a, **kw: calls.append(kw))
    cover_art_studio.render_cover_art(160, 240, title='Fixture', composition=direction)
    assert bool(calls) == (direction == 'cartridge')


def test_scanlines_are_limited_to_tube_era_directions():
    """Scanlines over a pixel mosaic or a retail box are wrong, and were global."""
    import inspect

    from oneirodex.utils import cover_art_studio

    src = inspect.getsource(cover_art_studio.render_cover_art)
    assert "direction in ('crt', 'marquee', 'neon')" in src
