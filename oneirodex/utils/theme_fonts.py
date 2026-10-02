"""Themeable fonts, including per-system faces for emulator/library surfaces.

Licensing stance
----------------
Oneirodex does **not** ship console manufacturers' typefaces. The real Nintendo,
Sega and Sony faces are trademarked and not licensed for redistribution, so
bundling them would put an infringing asset in every install.

What ships instead are **OFL / public-domain** fonts chosen to *evoke* each era —
the 8-bit pixel look, the 16-bit arcade look, the CRT terminal look. Operators
who hold a licence for something closer can drop it in themselves: any font
placed under ``static/library/fonts/`` is offered alongside the built-ins, with
no code change.

The registry is data, not behaviour — adding a face is one entry here plus the
file on disk.
"""

from __future__ import annotations

import os

from flask import current_app
from oneirodex.utils.library_paths import library_dir

# `stack` is a full CSS font-family value, so an absent file degrades to the
# next family rather than to an unstyled fallback.
BUILT_IN_FONTS: dict[str, dict] = {
    'system-ui': {
        'label': 'System UI (default)',
        'stack': '"Segoe UI", "Helvetica Neue", system-ui, sans-serif',
        'file': None,
        'era': 'modern',
        'license': 'n/a — uses the reader\'s own system fonts',
    },
    'press-start': {
        'label': 'Press Start 2P — 8-bit',
        'stack': '"Press Start 2P", "Courier New", monospace',
        'file': 'PressStart2P-Regular.ttf',
        'era': '8bit',
        'license': 'SIL Open Font License 1.1',
    },
    'silkscreen': {
        'label': 'Silkscreen — compact pixel',
        'stack': '"Silkscreen", "Press Start 2P", monospace',
        'file': 'Silkscreen-Regular.ttf',
        'era': '8bit',
        'license': 'SIL Open Font License 1.1',
    },
    'vt323': {
        'label': 'VT323 — CRT terminal',
        'stack': '"VT323", "Courier New", monospace',
        'file': 'VT323-Regular.ttf',
        'era': 'crt',
        'license': 'SIL Open Font License 1.1',
    },
    'share-tech-mono': {
        'label': 'Share Tech Mono — arcade cabinet',
        'stack': '"Share Tech Mono", "Courier New", monospace',
        'file': 'ShareTechMono-Regular.ttf',
        'era': 'arcade',
        'license': 'SIL Open Font License 1.1',
    },
    'orbitron': {
        'label': 'Orbitron — 32-bit / disc era',
        'stack': '"Orbitron", "Arial Black", sans-serif',
        # Orbitron ships upstream as a variable font only; there is no static
        # Bold to fetch. `weight` makes the @font-face declare the axis range so
        # the browser can synthesise Bold from it instead of pinning 400.
        'file': 'Orbitron-Variable.ttf',
        'weight': '400 900',
        'era': '32bit',
        'license': 'SIL Open Font License 1.1',
    },
}

# Which face suits which system, for the emulator surfaces. Deliberately by era
# rather than by brand — this is period flavour, not an imitation of a logo.
PLATFORM_FONT_HINTS: dict[str, str] = {
    'NES': 'press-start',
    'SNES': 'press-start',
    'GB': 'silkscreen',
    'GBC': 'silkscreen',
    'GBA': 'silkscreen',
    'SEGA_MS': 'press-start',
    'SEGA_MD': 'share-tech-mono',
    'SEGA_GG': 'silkscreen',
    'SEGA_32X': 'share-tech-mono',
    'ARCADE': 'share-tech-mono',
    'NEOGEO': 'share-tech-mono',
    'NEOGEO_CD': 'share-tech-mono',
    'PSX': 'orbitron',
    'PS2': 'orbitron',
    'SEGA_SATURN': 'orbitron',
    'SEGA_DC': 'orbitron',
    'N64': 'orbitron',
    'NGC': 'orbitron',
    'THREEDO': 'orbitron',
    'PCE': 'press-start',
    'AMIGA': 'vt323',
    'AMIGA_CD32': 'vt323',
    'ZX_SPECTRUM': 'vt323',
    'CPC': 'vt323',
    'MSX': 'vt323',
    'ATARI_ST': 'vt323',
    'APPLE_II': 'vt323',
    'ATARI_8BIT': 'vt323',
    'X68000': 'vt323',
    'PC_98': 'vt323',
    'BBC_MICRO': 'vt323',
    'GAME_WATCH': 'silkscreen',
    'PCDOS': 'vt323',
    'C64': 'vt323',
    'VICE_X64SC': 'vt323',
}

DEFAULT_FONT_ID = 'system-ui'


def fonts_dir() -> str:
    root = current_app.config.get('FONT_PATH')
    if root:
        return root
    return os.path.join(library_dir(), 'fonts')


def _operator_fonts() -> dict[str, dict]:
    """Anything the operator dropped in, offered next to the built-ins."""
    root = fonts_dir()
    found: dict[str, dict] = {}
    if not os.path.isdir(root):
        return found
    # Skip by *filename*, not by derived id: a built-in's file stem does not
    # match its registry key (PressStart2P-Regular.ttf -> 'press-start'), so an
    # id-only check lists every installed built-in a second time as "(operator)".
    builtin_files = {e['file'] for e in BUILT_IN_FONTS.values() if e.get('file')}
    for name in sorted(os.listdir(root)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in ('.ttf', '.otf', '.woff', '.woff2'):
            continue
        if name in builtin_files:
            continue
        key = stem.lower().replace(' ', '-').replace('_', '-')
        if key in BUILT_IN_FONTS:
            continue
        found[key] = {
            'label': f'{stem} (operator)',
            'stack': f'"{stem}", sans-serif',
            'file': name,
            'era': 'operator',
            'license': 'supplied by operator',
        }
    return found


def available_fonts() -> dict[str, dict]:
    """Built-ins plus operator drop-ins, with presence noted per entry.

    ``installed`` is reported honestly: a face whose file is missing still
    appears (so the picker is stable) but is flagged, because its CSS stack will
    silently fall through to the next family.
    """
    root = fonts_dir()
    catalogue = {**BUILT_IN_FONTS, **_operator_fonts()}
    for entry in catalogue.values():
        file_name = entry.get('file')
        entry['installed'] = (
            True if file_name is None else os.path.isfile(os.path.join(root, file_name))
        )
    return catalogue


def resolve_font(font_id: str | None) -> dict:
    catalogue = available_fonts()
    return catalogue.get((font_id or '').strip().lower()) or catalogue[DEFAULT_FONT_ID]


def font_for_platform(platform_key: str | None) -> dict:
    """Era-appropriate face for a platform; default when we have no opinion."""
    hint = PLATFORM_FONT_HINTS.get((platform_key or '').strip().upper())
    return resolve_font(hint or DEFAULT_FONT_ID)


def font_face_css() -> str:
    """``@font-face`` blocks for every installed face.

    Only emits rules for files that exist — a rule pointing at a missing file
    makes the browser fetch, fail, and fall back anyway, so it is noise.
    """
    blocks: list[str] = []
    for entry in available_fonts().values():
        file_name = entry.get('file')
        if not file_name or not entry.get('installed'):
            continue
        family = entry['stack'].split(',')[0].strip().strip('"')
        url = f'/static/library/fonts/{file_name}'
        fmt = 'woff2' if file_name.endswith('.woff2') else (
            'woff' if file_name.endswith('.woff') else (
                'opentype' if file_name.endswith('.otf') else 'truetype'
            )
        )
        # A variable face must declare its axis range, or the browser pins the
        # default instance and bold requests fall back to synthetic smearing.
        weight = entry.get('weight')
        weight_rule = f"  font-weight: {weight};\n" if weight else ''
        blocks.append(
            f"@font-face {{\n"
            f"  font-family: '{family}';\n"
            f"  src: url('{url}') format('{fmt}');\n"
            f"{weight_rule}"
            f"  font-display: swap;\n"
            f"}}"
        )
    return '\n'.join(blocks)


# Fonts are operator-supplied files landing on a served directory, so uploads
# are treated as untrusted: extension allowlist + size cap + magic-byte check.
ALLOWED_FONT_EXTENSIONS = frozenset({'.ttf', '.otf', '.woff', '.woff2'})
DEFAULT_FONT_MAX_BYTES = 8 * 1024 * 1024

# Leading bytes for each accepted container. Extension alone is not evidence —
# anything served back to a browser should be what it claims to be.
_FONT_MAGIC = (
    b'\x00\x01\x00\x00',  # TrueType
    b'true',              # TrueType (Apple)
    b'ttcf',              # TrueType collection
    b'OTTO',              # OpenType/CFF
    b'wOFF',              # WOFF
    b'wOF2',              # WOFF2
)


def _max_font_bytes() -> int:
    try:
        value = int(current_app.config.get('FONT_MAX_BYTES') or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_FONT_MAX_BYTES


def looks_like_font(head: bytes) -> bool:
    return any(head.startswith(sig) for sig in _FONT_MAGIC)


def store_font_file(file_storage) -> dict:
    """Validate and store an uploaded font. Raises ``ValueError`` with a reason."""
    from werkzeug.utils import secure_filename

    raw_name = getattr(file_storage, 'filename', '') or ''
    if not raw_name.strip():
        raise ValueError('Choose a font file to upload.')

    name = secure_filename(raw_name)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in ALLOWED_FONT_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_FONT_EXTENSIONS))
        raise ValueError(f'Font must be one of: {allowed}')
    if not stem:
        raise ValueError('Font file needs a name.')

    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size <= 0:
        raise ValueError('That file is empty.')
    cap = _max_font_bytes()
    if size > cap:
        raise ValueError(f'Font is larger than the {cap // (1024 * 1024)}MB limit.')

    head = stream.read(4)
    stream.seek(0)
    if not looks_like_font(head):
        raise ValueError('That file does not look like a font.')

    root = fonts_dir()
    os.makedirs(root, exist_ok=True)
    destination = os.path.join(root, name)
    file_storage.save(destination)

    return {
        'id': stem.lower().replace(' ', '-').replace('_', '-'),
        'filename': name,
        'family': stem,
        'size': size,
    }


def delete_font_file(filename: str) -> bool:
    """Remove an operator-uploaded font. Built-in names are refused."""
    from werkzeug.utils import secure_filename

    name = secure_filename(filename or '')
    if not name:
        return False
    builtin_files = {e['file'] for e in BUILT_IN_FONTS.values() if e.get('file')}
    if name in builtin_files:
        raise ValueError('That font ships with Oneirodex and cannot be deleted here.')
    path = os.path.join(fonts_dir(), name)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True
