#!/usr/bin/env python
"""Generate the per-system loading-motif catalogue from LibraryPlatform.

The platform enum supplies the supported system IDs. Each platform maps to
a hardware silhouette and a stable variant, used by both the member and
admin renderers. Generate the backend and frontend catalogues together.

Archetypes are deliberately coarse. At 18-28px a Master System and a Mega Drive
cannot be told apart no matter how they are drawn, so the variant carries what
detail survives at that size: button count, screen shape, cartridge slot.

    python scripts/gen_loading_motifs.py            # write catalogue
    python scripts/gen_loading_motifs.py --check    # verify it is current
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PLATFORM_PY = REPO / 'oneirodex' / 'platform.py'
OUT_JSON = REPO / 'oneirodex' / 'data' / 'loading_motifs.json'
# Both native shells draw from this generated catalogue.
OUT_JS = REPO / 'frontend' / 'shared' / 'src' / 'loadingMotifs' / 'systemMotifCatalogue.ts'

# Family → the vendor grouping a member actually thinks in. Drives the grouped
# picker; the picker groups the catalogue by family.
FAMILY_RULES: list[tuple[str, str, str]] = [
    # (regex over the enum name, family, archetype)
    (r'^(AMIGA_CD32|JAGUAR_CD|CD_I)$', 'Disc era', 'disc'),
    (r'^(PCWIN|PCDOS|MAC|LINUX)$', 'Computer', 'computer'),
    # Commodore is its own picker group — VICE + Amiga outgrew a single
    # "Home computer" bucket once 8-bit micros were added (CI ratchet: 12).
    (r'^(AMIGA|VICE_|C16)', 'Commodore', 'computer'),
    (r'^(ATARI_ST|ATARI_8BIT|MSX|ZX|CPC|GX4000|APPLE_II|X68000|PC_98|BBC_MICRO)', 'Home computer', 'computer'),
    (r'^(NES|SNES|N64|NGC|WII|WII_U|SWITCH|FDS|SUFAMI)', 'Nintendo', 'pad'),
    (r'^(GB|GBA|GBC|NDS|N3DS|VB|POKE_MINI|GAME_WATCH)', 'Nintendo handheld', 'handheld'),
    (r'^(PSX|PS2|PS3|PS4|PS5)$', 'PlayStation', 'pad'),
    (r'^(PSP|PSVITA)$', 'PlayStation handheld', 'handheld'),
    (r'^(XBOX|X360|XONE|XSX)$', 'Xbox', 'pad'),
    (r'^SEGA_(GG)$', 'Sega handheld', 'handheld'),
    (r'^(SEGA_|GENESIS|DREAMCAST|SATURN)', 'Sega', 'console'),
    (r'^(LYNX|NGP|NGPC|WS|WSC|SUPERVISION|GAMATE|GAMEKING)', 'Handheld', 'handheld'),
    (r'^(ATARI_|JAGUAR|A5200|A7800|A2600)', 'Atari', 'console'),
    (r'^(PCE|PCFX|SUPERGRAFX|TG16)', 'NEC', 'console'),
    (r'^(NEOGEO)', 'SNK', 'console'),
    (r'^(ARCADE|MAME|FBNEO|CPS)', 'Arcade', 'cabinet'),
    (r'^(VECTREX)$', 'Vector', 'cabinet'),
    (r'^(THREEDO|CD_I|CDI|CDTV|SEGA_CD|PCE_CD|NEOGEO_CD|JAGUAR_CD|AMIGA_CD32)', 'Disc era', 'disc'),
    (r'^(INTV|COLECO|CHAF|O2EM|ASTROCADE|ARCADIA|VC4000|ELEKTOR)', 'Early console', 'console'),
]

DEFAULT_FAMILY = 'Other systems'
DEFAULT_ARCHETYPE = 'cart'
# Same ceiling as systemMotifs.test.jsx — a family past this needs splitting.
MAX_FAMILY_SIZE = 12

# Variant index within an archetype gives related systems distinguishable
# geometry (button counts, screen aspect) without inventing 117 drawings.
VARIANTS = 6


def read_platforms() -> list[tuple[str, str]]:
    """Members of LibraryPlatform only.

    Bounded at the next class declaration: platform.py also defines `Emulator`,
    which reuses names like O2EM with different values. Reading to end-of-file
    pulled those in and produced duplicate motif ids — caught by the guard in
    build(), which is why it is there.
    """
    source = PLATFORM_PY.read_text(encoding='utf-8')
    start = source.index('class LibraryPlatform')
    next_class = re.search(r'^class \w+', source[start + 1:], re.M)
    body = source[start:start + 1 + next_class.start()] if next_class else source[start:]
    return re.findall(r'^\s{4}([A-Z0-9_]+)\s*=\s*"([^"]+)"', body, re.M)


def classify(name: str) -> tuple[str, str]:
    for pattern, family, archetype in FAMILY_RULES:
        if re.match(pattern, name):
            return family, archetype
    return DEFAULT_FAMILY, DEFAULT_ARCHETYPE


def build() -> dict:
    rows = []
    seen_ids: set[str] = set()

    for name, label in read_platforms():
        motif_id = name.lower()
        if motif_id in seen_ids:
            raise SystemExit(f'duplicate motif id from enum name: {name}')
        seen_ids.add(motif_id)

        family, archetype = classify(name)
        rows.append({
            'id': motif_id,
            'name': label,
            'family': family,
            'archetype': archetype,
            # Stable per id, so a system's glyph never changes between builds.
            'variant': sum(ord(c) for c in motif_id) % VARIANTS,
        })

    families: dict[str, int] = {}
    for row in rows:
        families[row['family']] = families.get(row['family'], 0) + 1

    oversized = sorted(
        f'{name}:{count}'
        for name, count in families.items()
        if count > MAX_FAMILY_SIZE
    )
    if oversized:
        raise SystemExit(
            'motif family exceeds picker size — split FAMILY_RULES: '
            + ', '.join(oversized)
        )

    return {
        'generated_from': 'oneirodex/platform.py',
        'count': len(rows),
        'families': dict(sorted(families.items())),
        'motifs': rows,
    }


def js_module(payload: dict) -> str:
    """Frontend twin of the JSON catalogue."""
    rows = ",\n".join(
        "  { id: '%s', name: %s, family: '%s', archetype: '%s', variant: %d }"
        % (r["id"], json.dumps(r["name"]), r["family"], r["archetype"], r["variant"])
        for r in payload["motifs"]
    )
    header = [
        "// GENERATED by scripts/gen_loading_motifs.py - do not edit.",
        "//",
        "// One motif per system in LibraryPlatform (GT-B24). Generated so a new",
        "// platform cannot end up without a glyph, and so the picker, the backend",
        "// catalogue and the renderer cannot disagree about what exists.",
        "",
        "export const SYSTEM_MOTIFS = [",
    ]
    footer = [
        "]",
        "",
        "/** Grouped by family - a flat %d-row list is not a usable picker. */"
        % payload["count"],
        "export const SYSTEM_MOTIF_FAMILIES = SYSTEM_MOTIFS.reduce((acc, motif) => {",
        "  ;(acc[motif.family] ||= []).push(motif)",
        "  return acc",
        "}, {} as Record<string, typeof SYSTEM_MOTIFS>)",
        "",
        "export const SYSTEM_MOTIF_IDS = SYSTEM_MOTIFS.map((m) => m.id)",
        "",
    ]
    return "\n".join(header) + "\n" + rows + ",\n" + "\n".join(footer)


def main() -> int:
    payload = build()
    text = json.dumps(payload, indent=2) + '\n'

    if '--check' in sys.argv:
        current = OUT_JSON.read_text(encoding='utf-8') if OUT_JSON.exists() else ''
        current_js = OUT_JS.read_text(encoding='utf-8') if OUT_JS.exists() else ''
        if current != text or current_js != js_module(payload):
            print('loading_motifs.json is stale — run scripts/gen_loading_motifs.py')
            return 1
        print(f'loading_motifs.json current ({payload["count"]} systems)')
        return 0

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(text, encoding='utf-8')
    OUT_JS.write_text(js_module(payload), encoding='utf-8')
    print(f'wrote {OUT_JSON.relative_to(REPO)} — {payload["count"]} systems, '
          f'{len(payload["families"])} families')
    for family, count in payload['families'].items():
        print(f'  {family}: {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
