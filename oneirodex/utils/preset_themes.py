"""Install the current selectable UI theme presets derived from the default theme.

Presets live under ``static/library/themes/<slug>`` which is runtime state (a
Docker volume in production), while the tracked source of truth is
``oneirodex/setup/default_theme``.  Every preset is a copy of that source with
a handful of *managed* files rewritten to carry the preset's colours:

    theme.json        identity + the provenance marker used for staleness checks
    css/base.css      --btn-primary / --bg-dark-* recoloured
    css/od-tokens.css the --od-* design tokens the rest of the CSS keys on

Everything else in a preset must stay byte-identical to the source, which is
what lets :func:`sync_theme_tree` refresh presets in place without undoing
their colours.

The v11 cycle (H-D.4) moved the catalogue itself to ``preset_themes_catalog``
and the per-system chrome geometry to ``preset_themes_geometry`` as pure
moves; ``PRESET_THEMES``, ``PRESET_SLUGS``, ``GENERATOR_VERSION`` and the
install / sync entry points are still imported from here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import date

from oneirodex.product import LEGACY_NAME, PRODUCT_NAME
from oneirodex.utils.preset_themes_catalog import PRESET_THEMES
from oneirodex.utils.preset_themes_geometry import _system_geometry

# Bump when the generator's output format changes so existing presets rebuild.
# 11 (GT-A1): od-tokens gained radius / spacing / type / shadow / motion scales
# and the tree gained od-primitives.css. source_fingerprint() would catch the
# file changes on its own, but the bump makes the token-layer break explicit for
# operators reading theme.json markers, and forces a rebuild of any preset whose
# folder was hand-edited.
# 12 (GT-A2/A4/A5): od-tokens gained the upper type steps and --od-radius-3xl
# that base.css's legacy scales now alias onto; od-primitives gained the
# canonical --secondary / --ghost button variants; and the tree gained
# od-bootstrap-bridge.css, which the base templates link and every preset
# therefore needs on disk. source_fingerprint() would notice the file changes
# anyway, but the bump makes the new required asset explicit for operators
# reading theme.json markers.
# 13 (UX-C8/W27-C2): the tree gained od_sortable_table.js, which both base
# templates load, and table-components.css gained the .od-sort-btn rules it
# builds. Same reasoning as 12 — a preset missing the script has tables whose
# headers simply do not respond, which reads as the feature never shipping.
# 14 (W27-C1 buttons): od-appbar's .od-cbtn gained a disabled state, a hover
# guard and the same focus ring as .od-btn, and both focus rules gained a
# fallback so a theme without --od-focus-ring loses the colour rather than the
# outline. A preset still carrying the old copy shows disabled chrome buttons
# as though they were live.
# 15 (W28-5 focus visibility): seven controls across od-loading-motifs,
# form-components, settings/od-account, admin-shell, admin_manage_themes,
# admin_manage_igdb_settings and admin_manage_scanjobs gained a real
# :focus-visible ring. A preset still carrying the old copies has controls a
# keyboard user cannot locate.
# 16 (UID-006 art packs): each preset now authors radius / space / type /
# shadow as a system visual language, not hue-only tint. Operators must
# Reset Themes so regenerated od-tokens.css picks up the geometry.
# 17 (decade rooms): presets carry an era room (same setting language as the
# play shell) so chrome is wallpaper/window/floor, not a solid colour slab.
# The tree gained css/od-era.css. Reset Themes so every pack copies it and
# regenerated od-tokens.css picks up --od-era.
# 18: Libraries & scans — skip drain-on-busy poll contention; flatten nested
# scan-jobs / unmatched cards so the page is one list per pane, not a card in
# a card. Reset Themes so volume copies pick up admin_manage_scanjobs CSS/JS.
# 19: Discover top bar fades (opacity) when a tile enlarges instead of popping
# z-index; era hover stack matches. Reset Themes so volume copies pick up
# od-shell.css / od-era.css.
# 20: Admin account menu / prefs host + leftover chrome.
# 21: Libraries & scans — patch job progress in place; skip unmatched rebuild
# while that pane is hidden; do not remount the scan motif every tick.
# Account dropdown panel layout lives in od-shell.css so admin is not stuck
# with member-only TopNav.css. Reset Themes for admin_manage_scanjobs.js,
# scanJobsDom.js, and od-shell.css.
# Tile hover: tight outline only while enlarged; library L/R overlap via
# overflow-clip-margin (not extra inline pad / inward origin).
# Libraries panel: inline filters, page-local games popover, grouping, no
# rest underlines on seg/cbtn links.
# 29: Button language — the bar's "one bar" is broken into separate buttons.
# `.od-seg` and `.od-cbtn-group` no longer weld their members into a single
# outlined pill (no outer border, no overflow clip, no -1px fusing margin);
# each member carries its own border and radius, 2px apart. Every button box
# (.od-btn, .od-cbtn, .od-seg__item) is now font-relative — `em` padding and a
# `1lh` content floor over a `--od-btn-h-base` density floor — so a button
# tracks the type it renders instead of sitting inside a fixed height, and is
# tighter at rest. od-density.css stopped re-asserting `.od-btn` metrics, which
# is what made UID-050 possible. A preset still carrying the old copies shows
# the fused bars and the old fixed-height buttons, so Reset Themes is required.
# UID-060: Discovery shelves delete uses the house confirm dialog in theme JS
# (cannot import frontend/shared). Reset Themes required so the volume copy
# of discovery_sections.js / admin_discovery_sections.css picks it up.
# Auto Scan: Refresh-all is an icon + od-tip in the panel header (no banner row).
# Library tools: THN owns tool views; pane chrome is borderless.
# 37 (THEME-AI first pass): each theme carries **drawn room art**, not gradients
# alone — `art/era/<era>.svg` under the theme's own folder, painted by the new
# `.od-era-scene` layer and recoloured per preset on one accent sentinel. A
# preset missing `art/` shows the old flat room, so Reset Themes is required.
# 38 (E2 + E4): loading motifs read `--od-platform-accent`, so a console's
# motif carries that console's colour instead of the theme accent everywhere;
# and the rail glyphs are one shared module rather than two drifting copies.
# A preset still carrying the old od-loading-motifs.css spins every motif in
# the theme accent, so Reset Themes is required.
# 39 (UID-064): `.od-seg` wraps. A six-item segmented strip was 457px wide
# inside a 315px parent on Admin -> Integrations at phone width, pushing the
# page sideways. A preset still carrying the old od-appbar.css keeps the
# nowrap strip, so Reset Themes is required.
# 40 = E1 console-family packs (six `group: 'console'` presets); existing
# presets are byte-identical, the bump is what makes Reset Themes install them.
# 41 = admin_metadata_providers.js learns the hash_identify switch (INSP-31);
# the theme JS lives on the volume, so the handler change needs a Reset.
GENERATOR_VERSION = 42

# Play-room id used when a theme does not name one (default + uploaded packs).
DEFAULT_ERA = 'wood_den_80s'

# Key written into each generated theme.json; also our ownership proof.
PRESET_MARKER_KEY = 'oneirodex_preset'

# ---------------------------------------------------------------------------
# Stock avatars
# ---------------------------------------------------------------------------
#
# The seven shipped avatars are hand-drawn emblem SVGs using the default
# theme's accent, panel, and muted colours. They are served as <img>, so they
# cannot inherit `currentColor` or read CSS custom properties; regenerate their
# accent with each preset so they belong to the selected design.
#
# So they are generated per preset, exactly like `od-tokens.css` is. The source
# files carry these three colours and nothing else, which is what makes a
# straight substitution safe rather than a guess.
#
# Anyone editing the source SVGs must stay inside this palette. `AVATAR_SOURCE_*`
# is the contract, and `tests/test_preset_avatars.py` fails if a file drifts off
# it — otherwise a new colour would silently survive into every preset unchanged
# and only ever be noticed as "that one avatar is still green".
AVATAR_SOURCE_ACCENT = '#2fd67b'
AVATAR_SOURCE_PANEL = '#12161c'
AVATAR_SOURCE_MUTED = '#8a94a3'

# Drawn room art (THEME-AI). One SVG per era, copied into every preset and
# recoloured on a single sentinel so the screen glow matches the theme while the
# room keeps its own era palette — a wood den does not turn green.
#
# `docs/dev/theme-art-direction.md` is the contract these files answer to. A
# generated (AI) backdrop replaces the same path and needs no code change.
ART_ACCENT_SENTINEL = '#2fd67b'

ERA_ART_FILES = (
    'arcade_cabinet.svg',
    'carpet_den_late_90s.svg',
    'desk.svg',
    'media_center_00s.svg',
    'teen_bedroom_90s.svg',
    'wood_den_80s.svg',
)

AVATAR_FILES = (
    'arcade.svg',
    'cartridge.svg',
    'controller.svg',
    'default.svg',
    'disc.svg',
    'dpad.svg',
    'joystick.svg',
)

# Files the generator writes for *every* preset, unconditionally. Two things
# follow from that: sync_theme_tree must never overwrite them from the source,
# and a preset missing any of them is stale and gets rebuilt.
PRESET_MANAGED_FILES = (
    'theme.json',
    'css/base.css',
    'css/od-tokens.css',
)

# The recoloured avatars — protected from the sync exactly like the colour CSS,
# but deliberately *not* part of PRESET_MANAGED_FILES.
#
# The difference is that these are written only when the source tree actually
# ships `avatars/`. Folding them into the managed list made their absence mean
# "stale", so an install whose source predates them — or any caller passing a
# source tree without them — would rebuild all nine presets on every single
# boot, forever, trying to produce files that could never exist. Staleness has
# to be conditional on the source having something to generate from; see
# `preset_needs_rebuild`.
PRESET_AVATAR_FILES = tuple(f'avatars/{name}' for name in AVATAR_FILES)

# The recoloured room art — same conditional-staleness reasoning as the avatars
# above: generated only when the source tree ships `art/`, never a permanent
# rebuild trigger for an install whose source predates it.
PRESET_ART_FILES = tuple(f'art/era/{name}' for name in ERA_ART_FILES)

# What the sync pass must leave alone: everything the generator owns, whether
# or not its absence would trigger a rebuild.
PRESET_PROTECTED_FILES = PRESET_MANAGED_FILES + PRESET_AVATAR_FILES + PRESET_ART_FILES
PRESET_SLUGS = tuple(preset['slug'] for preset in PRESET_THEMES)
PRESET_BY_SLUG = {preset['slug']: preset for preset in PRESET_THEMES}

# Retired built-ins are replaced by the six new visual designs. Preferences
# using a retired slug keep a nearby palette until the member chooses again.
RETIRED_PRESET_ALIASES = {
    'aurora': 'afterglow', 'ember': 'afterglow', 'era-arcade': 'afterglow',
    'violet': 'tape-deck', 'rose': 'tape-deck', 'era-90s': 'tape-deck',
    'era-late90s': 'tape-deck',
    'forest': 'greenhouse', 'mono': 'monochrome', 'era-desk': 'greenhouse',
    'console-terminal': 'greenhouse', 'console-signal': 'greenhouse',
    'sunset': 'signal', 'era-80s': 'signal', 'console-woodgrain': 'signal',
    'console-cartridge': 'signal',
    'ice': 'deep-space', 'ocean': 'deep-space', 'era-00s': 'deep-space',
    'console-disc': 'deep-space', 'console-deepblue': 'deep-space',
}


def canonical_theme_slug(slug: str | None) -> str:
    """Resolve a retired built-in id to its replacement design."""
    key = (slug or '').strip() or 'default'
    replacement = RETIRED_PRESET_ALIASES.get(key)
    if not replacement:
        return key
    # A household upload may occupy a former preset slug. Startup pruning only
    # removes generator-owned folders, so an extant unmarked folder keeps its identity.
    try:
        from oneirodex.utils.library_paths import library_dir

        old_folder = os.path.join(library_dir(), 'themes', key)
        metadata = _read_theme_json(os.path.join(old_folder, 'theme.json'))
        marker = metadata.get(PRESET_MARKER_KEY) if metadata else None
        owned_old_preset = (
            isinstance(marker, dict)
            and marker.get('slug') == key
            and metadata.get('author') in {PRODUCT_NAME, LEGACY_NAME}
        )
        if os.path.isdir(old_folder) and not owned_old_preset:
            return key
    except Exception:  # noqa: BLE001 — resolve safely outside an app context
        pass
    return replacement


def era_for_theme(slug: str | None) -> str:
    """Play-room / UI atmosphere id for a theme folder slug."""
    key = canonical_theme_slug(slug)
    if key == 'default':
        return DEFAULT_ERA
    preset = PRESET_BY_SLUG.get(key)
    if preset:
        return str(preset.get('era') or DEFAULT_ERA)
    return DEFAULT_ERA


def theme_picker_groups(choices) -> list[dict]:
    """Group Preferences theme choices into decade rooms, system families, colour cabinets, uploads.

    *choices* is the WTForms ``(value, label)`` list. Unknown / uploaded slugs
    land in Installed so the picker still covers every installed folder.
    """
    groups = {
        'decade': {
            'id': 'decade',
            'label': 'Decade rooms',
            'hint': 'The room you started in — same scenery language as browser play.',
            'items': [],
        },
        'console': {
            'id': 'console',
            'label': 'System families',
            'hint': 'The shell language of a console family, in the room it lived in.',
            'items': [],
        },
        'cabinet': {
            'id': 'cabinet',
            'label': 'Colour cabinets',
            'hint': 'Palette packs that still sit in an era room, not a flat colour.',
            'items': [],
        },
        'installed': {
            'id': 'installed',
            'label': 'Installed',
            'hint': 'Themes uploaded on this server.',
            'items': [],
        },
    }
    for value, label in choices:
        slug = str(value)
        name = str(label)
        preset = PRESET_BY_SLUG.get(slug)
        if slug == 'default':
            groups['cabinet']['items'].append({
                'slug': slug,
                'name': name,
                'description': 'System default — wood den scenery, green glass.',
                'era': DEFAULT_ERA,
                'icon_pack': 'outline',
            })
            continue
        if preset:
            gid = str(preset.get('group') or 'cabinet')
            if gid not in groups:
                gid = 'installed'
            groups[gid]['items'].append({
                'slug': slug,
                'name': name,
                'description': str(preset.get('description') or ''),
                'era': str(preset.get('era') or DEFAULT_ERA),
                'icon_pack': preset_icon_pack(preset),
            })
            continue
        groups['installed']['items'].append({
            'slug': slug,
            'name': name,
            'description': 'Uploaded theme.',
            'era': DEFAULT_ERA,
            'icon_pack': '',
        })
    return [group for group in (groups['decade'], groups['console'], groups['cabinet'], groups['installed']) if group['items']]


# --------------------------------------------------------------------------
# File-tree helpers (hash based, shared with the boot-time sync)
# --------------------------------------------------------------------------

def iter_tree_files(root: str):
    """Yield every file under *root* as a '/'-separated relative path."""
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(files):
            rel = name if rel_dir == '.' else os.path.join(rel_dir, name)
            yield rel.replace(os.sep, '/')


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(root: str) -> str:
    """Content fingerprint of a theme source tree.

    Changes whenever a tracked file is added, removed or edited, which is what
    tells us a preset generated from an older snapshot is stale.
    """
    digest = hashlib.sha256()
    digest.update(f'generator={GENERATOR_VERSION}\n'.encode('utf-8'))
    for rel in sorted(iter_tree_files(root)):
        digest.update(f'{rel}:{file_digest(os.path.join(root, *rel.split("/")))}\n'.encode('utf-8'))
    return digest.hexdigest()


#: A modification time this recent is not trusted to prove two files match:
#: a file rewritten within the filesystem's timestamp granularity can keep it.
_QUICK_CHECK_MIN_AGE = 2.0


def _files_match(src: str, dest: str) -> bool:
    try:
        src_stat, dest_stat = os.stat(src), os.stat(dest)
    except OSError:
        return False
    if src_stat.st_size != dest_stat.st_size:
        return False
    # copy2 keeps the source's mtime, so an untouched copy matches on size and
    # mtime without reading either file. Every boot syncs ~100 files into each
    # of 21 presets; opening and hashing both sides took ~16 s on Windows.
    if (src_stat.st_mtime_ns == dest_stat.st_mtime_ns
            and time.time() - src_stat.st_mtime > _QUICK_CHECK_MIN_AGE):
        return True
    return file_digest(src) == file_digest(dest)


def sync_theme_tree(source_root: str, target_root: str, *, protected=()) -> int:
    """Copy every source file whose content differs at the target.

    Files listed in *protected* are skipped entirely: those are the ones a
    preset legitimately owns.  Extra files at the target are left alone so a
    hand-added asset is never deleted.  Returns the number of files written.
    """
    if not os.path.isdir(source_root):
        return 0

    protected_set = {p.replace('\\', '/') for p in protected}
    written = 0
    for rel in iter_tree_files(source_root):
        if rel in protected_set:
            continue
        parts = rel.split('/')
        src = os.path.join(source_root, *parts)
        dest = os.path.join(target_root, *parts)
        if os.path.isfile(dest) and _files_match(src, dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        written += 1
    return written


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------

def _replace_css_var(css: str, name: str, value: str) -> str:
    pattern = re.compile(rf'(--{re.escape(name)}:\s*)([^;]+)(;)')
    if not pattern.search(css):
        return css
    return pattern.sub(rf'\g<1>{value}\g<3>', css, count=1)


def _upsert_css_var(css: str, name: str, value: str) -> str:
    """Replace a CSS variable, adding it to the first :root block if absent."""
    pattern = re.compile(rf'(--{re.escape(name)}:\s*)([^;]+)(;)')
    if pattern.search(css):
        return pattern.sub(rf'\g<1>{value}\g<3>', css, count=1)

    root = re.search(r':root\s*\{', css)
    if root:
        insert_at = root.end()
        return f'{css[:insert_at]}\n  --{name}: {value};{css[insert_at:]}'
    return f':root {{\n  --{name}: {value};\n}}\n{css}'


def _rgba_to_hex(value: str) -> str | None:
    """'rgba(10, 24, 32, 0.94)' -> '#0a1820' (alpha dropped)."""
    match = re.search(r'rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)', value or '')
    if not match:
        return None
    channels = [max(0, min(255, int(round(float(c))))) for c in match.groups()]
    return '#{:02x}{:02x}{:02x}'.format(*channels)


def _hex_to_rgb(value: str):
    value = value.lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _lighten(hex_color: str, amount: float) -> str:
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return hex_color
    lifted = [min(255, int(round(c + (255 - c) * amount))) for c in rgb]
    return '#{:02x}{:02x}{:02x}'.format(*lifted)


def _relative_luminance(hex_color: str) -> float:
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return 0.0
    channels = []
    for raw in rgb:
        c = raw / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def preset_tokens(preset: dict) -> dict:
    """The --od-* overrides that make this preset visually distinct.

    Base colours always derive from btn_primary / bg_dark_*. Optional
    ``tokens`` on the preset expand glass, typography, CRT, and icon geometry
    so packs diverge beyond accent hue alone.
    """
    accent = preset['btn_primary']
    surface = _rgba_to_hex(preset.get('bg_dark_40', '')) or '#141820'
    tokens = {
        'od-bg': _rgba_to_hex(preset.get('bg_dark_30', '')) or '#0b0d10',
        'od-surface': surface,
        'od-surface-2': _lighten(surface, 0.10),
        'od-accent': accent,
        # Text drawn on top of the accent needs to flip with accent brightness.
        'od-accent-contrast': '#0b0d10' if _relative_luminance(accent) > 0.30 else '#f2f4f8',
    }
    extra = preset.get('tokens') or {}
    if isinstance(extra, dict):
        for name, value in extra.items():
            if value is None or value == '':
                continue
            tokens[str(name)] = str(value)
    tokens['od-era'] = str(preset.get('era') or DEFAULT_ERA)
    for name, value in _system_geometry(str(preset.get('slug') or '')).items():
        tokens[name] = value
    return tokens


def preset_icon_pack(preset: dict) -> str:
    """Paired icon pack id for a colour preset (outline if unset)."""
    pack = preset.get('icon_pack') or 'outline'
    return str(pack).strip() or 'outline'


# --------------------------------------------------------------------------
# Preset ownership + staleness
# --------------------------------------------------------------------------

def _read_theme_json(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_managed_preset(target: str, preset: dict) -> bool:
    """True when the folder at a preset slug was generated by us.

    A user can upload a custom theme whose name collides with a preset slug;
    regenerating over it would destroy their work.  We only claim a folder if
    it carries our marker, or — for presets written before the marker existed —
    if its theme.json still matches the identity we would have written.
    """
    theme_json = os.path.join(target, 'theme.json')
    if not os.path.isfile(theme_json):
        # No theme.json means no usable theme here, so there is nothing to lose.
        return True

    data = _read_theme_json(theme_json)
    if data is None:
        return False

    marker = data.get(PRESET_MARKER_KEY)
    if isinstance(marker, dict):
        return marker.get('slug') == preset['slug']

    return (
        data.get('author') in {PRODUCT_NAME, LEGACY_NAME}
        and data.get('name') == preset['name']
        and data.get('description') == preset['description']
    )


def preset_needs_rebuild(
    target: str, preset: dict, fingerprint: str, source_root: str | None = None
) -> bool:
    """True when the preset on disk was generated from a different source.

    ``source_root`` is optional and only widens the check: given one, a preset
    is also stale when the source ships avatars that the target is missing.
    Without it the avatars are ignored entirely, which is what keeps a source
    tree with no ``avatars/`` folder from looking permanently stale.
    """
    theme_json = os.path.join(target, 'theme.json')
    data = _read_theme_json(theme_json)
    if data is None:
        return True

    marker = data.get(PRESET_MARKER_KEY)
    if not isinstance(marker, dict):
        return True
    if marker.get('generator') != GENERATOR_VERSION:
        return True
    if marker.get('source') != fingerprint:
        return True

    # A managed file deleted at runtime cannot be restored by the sync pass
    # (the sync deliberately skips managed files), so rebuild instead.
    required = list(PRESET_MANAGED_FILES)

    # Same argument for the avatars — the sync skips those too — but only for
    # the ones the source could actually regenerate. Asking for a file the
    # generator will not write is how a rebuild loop starts.
    if source_root and os.path.isdir(os.path.join(source_root, 'avatars')):
        required += [
            rel
            for rel in PRESET_AVATAR_FILES
            if os.path.isfile(os.path.join(source_root, *rel.split('/')))
        ]

    # Room art, same rule again.
    if source_root and os.path.isdir(os.path.join(source_root, 'art', 'era')):
        required += [
            rel
            for rel in PRESET_ART_FILES
            if os.path.isfile(os.path.join(source_root, *rel.split('/')))
        ]

    return any(
        not os.path.isfile(os.path.join(target, *rel.split('/')))
        for rel in required
    )


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def _write_theme_json(
    path: str,
    *,
    name: str,
    description: str,
    slug: str,
    fingerprint: str,
    icon_pack: str = 'outline',
    era: str = DEFAULT_ERA,
    group: str = 'cabinet',
) -> None:
    payload = {
        'name': name,
        'author': PRODUCT_NAME,
        'description': description,
        'version': '1.0.0',
        'release_date': date.today().isoformat(),
        'default_icon_pack': icon_pack,
        'era': era,
        'group': group,
        PRESET_MARKER_KEY: {
            'slug': slug,
            'generator': GENERATOR_VERSION,
            'source': fingerprint,
            'icon_pack': icon_pack,
            'era': era,
            'group': group,
        },
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2)
        fh.write('\n')


def _write_preset_base_css(target: str, preset: dict) -> None:
    base_css_path = os.path.join(target, 'css', 'base.css')
    if not os.path.isfile(base_css_path):
        return

    with open(base_css_path, 'r', encoding='utf-8') as fh:
        css = fh.read()

    css = _replace_css_var(css, 'btn-primary', preset['btn_primary'])
    css = _replace_css_var(css, 'btn-primary-hover', preset['btn_primary_hover'])
    css = _replace_css_var(css, 'bg-dark-40', preset['bg_dark_40'])
    css = _replace_css_var(css, 'bg-dark-30', preset['bg_dark_30'])

    with open(base_css_path, 'w', encoding='utf-8') as fh:
        fh.write(css)


def _write_preset_tokens_css(source_root: str, target: str, preset: dict) -> None:
    """Write the preset's own od-tokens.css, derived from the source tokens.

    Starting from the source file (rather than a hand-written stub) means any
    token added upstream automatically reaches every preset on the next
    regeneration.
    """
    rel_parts = ('css', 'od-tokens.css')
    source_tokens = os.path.join(source_root, *rel_parts)
    if os.path.isfile(source_tokens):
        with open(source_tokens, 'r', encoding='utf-8') as fh:
            css = fh.read()
    else:
        css = ':root {\n}\n'

    for name, value in preset_tokens(preset).items():
        css = _upsert_css_var(css, name, value)

    target_tokens = os.path.join(target, *rel_parts)
    os.makedirs(os.path.dirname(target_tokens), exist_ok=True)
    with open(target_tokens, 'w', encoding='utf-8') as fh:
        fh.write(css)


def _write_preset_avatars(source_root: str, target: str, preset: dict) -> None:
    """Recolour the shipped avatars into this preset's palette.

    Substitution rather than templating, because the source files are plain art
    with three known colours and no markup we control — see the palette note at
    the top of this module.

    A missing source folder is not an error: an install that predates the themed
    avatars keeps serving the ones under `static/newstyle/avatars/`, which is
    what `avatar_url` falls back to.
    """
    source_dir = os.path.join(source_root, 'avatars')
    if not os.path.isdir(source_dir):
        return

    tokens = preset_tokens(preset)
    replacements = (
        (AVATAR_SOURCE_ACCENT, tokens.get('od-accent') or AVATAR_SOURCE_ACCENT),
        (AVATAR_SOURCE_PANEL, tokens.get('od-surface') or AVATAR_SOURCE_PANEL),
        (AVATAR_SOURCE_MUTED, tokens.get('od-text-muted') or AVATAR_SOURCE_MUTED),
    )

    target_dir = os.path.join(target, 'avatars')
    os.makedirs(target_dir, exist_ok=True)

    for name in AVATAR_FILES:
        source_file = os.path.join(source_dir, name)
        if not os.path.isfile(source_file):
            continue
        with open(source_file, 'r', encoding='utf-8') as fh:
            svg = fh.read()
        for source_colour, themed in replacements:
            # Case-insensitively, because SVG hex is case-free and the source
            # files are hand-edited art.
            svg = re.sub(re.escape(source_colour), themed, svg, flags=re.IGNORECASE)
        with open(os.path.join(target_dir, name), 'w', encoding='utf-8') as fh:
            fh.write(svg)


def _write_preset_era_art(source_root: str, target: str, preset: dict) -> None:
    """Recolour the drawn room art into this preset's accent.

    Only the sentinel moves. The room's own palette (wood, carpet, glass) is
    era-owned and deliberately untouched: tinting a whole scene to the accent
    is what made the old gradient rooms read as nine copies of one room.

    A missing source folder is not an error — the preset simply has no scene
    layer and falls back to the gradient room, exactly as before.
    """
    source_dir = os.path.join(source_root, 'art', 'era')
    if not os.path.isdir(source_dir):
        return

    accent = preset_tokens(preset).get('od-accent') or ART_ACCENT_SENTINEL
    target_dir = os.path.join(target, 'art', 'era')
    os.makedirs(target_dir, exist_ok=True)

    for name in ERA_ART_FILES:
        source_file = os.path.join(source_dir, name)
        if not os.path.isfile(source_file):
            continue
        with open(source_file, 'r', encoding='utf-8') as fh:
            svg = fh.read()
        svg = re.sub(re.escape(ART_ACCENT_SENTINEL), accent, svg, flags=re.IGNORECASE)
        with open(os.path.join(target_dir, name), 'w', encoding='utf-8') as fh:
            fh.write(svg)


def build_preset(source_root: str, target: str, preset: dict, fingerprint: str) -> None:
    """Regenerate one preset from scratch."""
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(source_root, target)

    _write_theme_json(
        os.path.join(target, 'theme.json'),
        name=preset['name'],
        description=preset['description'],
        slug=preset['slug'],
        fingerprint=fingerprint,
        icon_pack=preset_icon_pack(preset),
        era=str(preset.get('era') or DEFAULT_ERA),
        group=str(preset.get('group') or 'cabinet'),
    )
    _write_preset_base_css(target, preset)
    _write_preset_tokens_css(source_root, target, preset)
    _write_preset_avatars(source_root, target, preset)
    _write_preset_era_art(source_root, target, preset)


def install_preset_themes(themes_path: str, default_source: str, *, force: bool = False) -> int:
    """
    Generate/refresh the preset themes under *themes_path*.

    Presets are rebuilt when they are missing, were generated by an older
    generator, or were generated from a different snapshot of *default_source* —
    which is how an edited stylesheet reaches a preset's own colour files.
    Presets that are still current are left to :func:`sync_preset_themes`.

    Folders occupying a preset slug that we did not generate (e.g. a theme the
    admin uploaded) are left untouched.

    Returns the number of presets rebuilt.
    """
    if not os.path.isdir(default_source):
        return 0

    os.makedirs(themes_path, exist_ok=True)
    # Remove only generated Oneirodex presets from the retired catalogue.
    # Uploaded themes are preserved even when they use a formerly built-in slug.
    for retired_slug in RETIRED_PRESET_ALIASES:
        retired_path = os.path.join(themes_path, retired_slug)
        metadata = _read_theme_json(os.path.join(retired_path, 'theme.json'))
        marker = metadata.get(PRESET_MARKER_KEY) if metadata else None
        if (
            os.path.isdir(retired_path)
            and metadata
            and metadata.get('author') in {PRODUCT_NAME, LEGACY_NAME}
            and isinstance(marker, dict)
            and marker.get('slug') == retired_slug
        ):
            shutil.rmtree(retired_path)

    fingerprint = source_fingerprint(default_source)
    rebuilt = 0

    for preset in PRESET_THEMES:
        target = os.path.join(themes_path, preset['slug'])

        if os.path.isdir(target) and not is_managed_preset(target, preset):
            continue

        if force or preset_needs_rebuild(target, preset, fingerprint, default_source):
            build_preset(default_source, target, preset, fingerprint)
            rebuilt += 1

    return rebuilt


def sync_preset_themes(themes_path: str, default_source: str) -> int:
    """Refresh the shared (non-colour) files of every installed preset.

    Returns the number of files written across all presets.
    """
    if not os.path.isdir(default_source) or not os.path.isdir(themes_path):
        return 0

    written = 0
    for preset in PRESET_THEMES:
        target = os.path.join(themes_path, preset['slug'])
        if not os.path.isdir(target) or not is_managed_preset(target, preset):
            continue
        written += sync_theme_tree(default_source, target, protected=PRESET_PROTECTED_FILES)
    return written
