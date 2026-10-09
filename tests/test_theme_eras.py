"""Decade-room themes: era mapping, picker groups, atmosphere CSS.

Filesystem-only — no app, no database.
"""

import re
from pathlib import Path

from oneirodex.utils.play_rooms import ROOMS
from oneirodex.utils.preset_themes import (
    DEFAULT_ERA,
    PRESET_THEMES,
    era_for_theme,
    preset_tokens,
    theme_picker_groups,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME_SOURCE = REPO_ROOT / 'oneirodex' / 'setup' / 'default_theme'
TEMPLATES = REPO_ROOT / 'oneirodex' / 'templates'


def test_default_and_unknown_themes_use_the_wood_den():
    assert era_for_theme('default') == DEFAULT_ERA
    assert era_for_theme('') == DEFAULT_ERA
    assert era_for_theme(None) == DEFAULT_ERA
    assert era_for_theme('some-upload') == DEFAULT_ERA
    assert DEFAULT_ERA in ROOMS


def test_every_preset_names_a_real_play_room():
    for preset in PRESET_THEMES:
        era = era_for_theme(preset['slug'])
        assert era in ROOMS, f"{preset['slug']} era {era} is not a play room"
        assert preset_tokens(preset)['od-era'] == era


def test_replacement_presets_use_distinct_rooms():
    assert len({p['era'] for p in PRESET_THEMES}) >= 5


def test_picker_groups_new_designs_without_empty_categories():
    choices = (
        [('default', 'Default (system)')]
        + [(p['slug'], p['name']) for p in PRESET_THEMES]
        + [('custom-pack', 'Household upload')]
    )
    groups = theme_picker_groups(choices)
    assert [g['id'] for g in groups] == ['cabinet', 'installed']
    shipped = {item['slug'] for item in groups[0]['items']}
    assert shipped == {'default', *{preset['slug'] for preset in PRESET_THEMES}}
    assert groups[1]['items'][0]['slug'] == 'custom-pack'


def test_era_css_and_atmosphere_are_wired_into_every_shell():
    era_css = (THEME_SOURCE / 'css' / 'od-era.css').read_text(encoding='utf-8')
    assert 'html[data-era=' in era_css
    assert '#od-era-atmosphere' in era_css
    assert 'od-era-wall-drift' in era_css
    assert '--od-era-furniture' in era_css
    for room_id in ROOMS:
        assert f"data-era='{room_id}'" in era_css
    blob = ' '.join(ROOMS[r]['label'] + ' ' + ROOMS[r]['blurb'] for r in ROOMS).lower()
    for brand in ('nintendo', 'sega', 'sony', 'playstation', 'xbox', 'atari'):
        assert brand not in blob
        assert brand not in era_css.lower()

    atmosphere = (TEMPLATES / 'partials' / 'era_atmosphere.html').read_text(encoding='utf-8')
    assert 'id="od-era-atmosphere"' in atmosphere
    assert 'od-era-stand' in atmosphere
    for name in ('base.html', 'base_admin.html', 'base_empty.html'):
        html = (TEMPLATES / name).read_text(encoding='utf-8')
        assert 'data-era=' in html
        assert 'css/od-era.css' in html
        assert "partials/era_atmosphere.html" in html
        assert html.index('css/od-shell.css') < html.index('css/od-era.css')


def test_admin_chrome_stacks_above_era_atmosphere():
    """Admin #admin-app-root / .od-admin-shell are display:contents.

    #od-era-atmosphere is position:fixed behind the UI (z-index:-1). Chrome
    still gets its own stacking context; z-index on a flattened wrapper is a
    no-op so rail / topbar / main must be named explicitly.
    """
    era = (THEME_SOURCE / 'css' / 'od-era.css').read_text(encoding='utf-8')
    shell = (THEME_SOURCE / 'css' / 'od-shell.css').read_text(encoding='utf-8')
    assert 'display: contents' in shell
    assert re.search(r'#od-era-atmosphere\s*\{[^}]*z-index:\s*-1', era, re.S)
    assert re.search(r'html\[data-era\]\s*\{[^}]*background-color:', era, re.S)

    match = re.search(
        r'(html\[data-era\][^{]+)\{[^}]*z-index:\s*1',
        era,
        re.S,
    )
    assert match, 'era stacking rule with z-index: 1 is missing'
    selectors = match.group(1)
    for needed in ('.od-admin-main', '#admin-legacy-content'):
        assert needed in selectors, f'{needed} must stack above the atmosphere'
    rail = re.search(
        r'(html\[data-era\][^{]*\.od-rail[^{]*)\{[^}]*z-index:\s*2',
        era,
        re.S,
    )
    assert rail, 'rail stacking rule with z-index: 2 is missing'
    topbar = re.search(
        r'(html\[data-era\][^{]*\.od-topbar[^{]*)\{[^}]*z-index:\s*30',
        era,
        re.S,
    )
    assert topbar, 'topbar overlay stacking rule with z-index: 30 is missing'
    assert 'html[data-era] .od-shell:has(.game-card:hover) .od-topbar' not in era
    # No hover-driven lift of the scroll pane: it flipped across tile gaps and
    # made the top bar blink (found by scripts/vdevice/hover_stability.py).
    assert 'html[data-era] .od-shell:has(.game-card:hover) .od-shell__main' not in era
    assert 'html[data-era] .od-shell:has(.game-card:has(:focus-visible))' not in era
    assert 'opacity: 0' not in topbar.group(0)
    assert 'transition: opacity' not in era
    for flattened in ('#admin-app-root', '.od-admin-shell'):
        assert flattened not in selectors, (
            f'{flattened} is display:contents; z-index there cannot lift chrome'
        )
    assert re.search(r'isolation:\s*isolate', era)


def test_system_backdrop_sits_behind_library_tiles():
    css = (
        REPO_ROOT
        / 'frontend'
        / 'member-app'
        / 'src'
        / 'chrome'
        / 'systemBackdrop.css'
    ).read_text(encoding='utf-8')
    match = re.search(r'\.od-system-backdrop\s*\{([^}]*)\}', css, re.S)
    assert match, 'system backdrop rule missing'
    body = match.group(1)
    assert re.search(r'z-index:\s*-1', body)
    assert re.search(r'position:\s*absolute', body)


def test_decade_accents_are_unique():
    accents = [p['btn_primary'].lower() for p in PRESET_THEMES]
    assert len(accents) == len(set(accents))


def test_decade_copy_does_not_name_manufacturers():
    blob = ' '.join(
        f"{p['name']} {p['description']}" for p in PRESET_THEMES
    ).lower()
    for brand in ('nintendo', 'sega', 'sony', 'playstation', 'xbox', 'atari'):
        assert brand not in blob
