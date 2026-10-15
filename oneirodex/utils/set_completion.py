"""ROM set completeness — DAT parse, title normalize, owned/missing match."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Library, ReferenceSet, ReferenceSetEntry
from oneirodex.platform import LibraryPlatform, NATIVE_PC_PLATFORMS
from oneirodex.utils.library_acl import apply_game_access_filters

# Pref order is the member/admin dropdown. FRA/DEU/ESP/GBR are DAT SKUs
# (a France-specific DAT), not IGDB release_date regions — PAL filenames
# still peel to EUR in rom_language.py.
REGION_PREF_ORDER = (
    'USA',
    'EUR',
    'JPN',
    'BRA',
    'KOR',
    'AUS',
    'GBR',
    'FRA',
    'DEU',
    'ESP',
    'CHN',
    'WORLD',
    'OTHER',
)
VALID_REGIONS = frozenset(REGION_PREF_ORDER)
# nointro / redump: cartridge and disc sets. tosec / mame (INSP-34, v11 H1b):
# home-computer and arcade sets -- TOSEC names carry `(1991)(Publisher)(EU)[cr X]`
# groups the peel already strips; MAME `machine` / softlist `software` nodes
# keep the human title in <description>, the attribute is the short set name.
VALID_SOURCES = frozenset({'nointro', 'redump', 'tosec', 'mame', 'other'})
# Sources whose XML nodes name the title in <description> rather than name="".
DESCRIPTION_TITLED_SOURCES = frozenset({'mame'})
REGION_LABELS = {
    'USA': 'United States',
    'EUR': 'Europe',
    'JPN': 'Japan',
    'BRA': 'Brazil',
    'KOR': 'Korea',
    'AUS': 'Australia',
    'GBR': 'United Kingdom',
    'FRA': 'France',
    'DEU': 'Germany',
    'ESP': 'Spain',
    'CHN': 'China',
    'WORLD': 'World',
    'OTHER': 'Other',
}

from oneirodex.utils.rom_name_peel import normalize_set_title_from_peel
_CLRMAME_GAME = re.compile(
    r'game\s*\(\s*name\s+"([^"]+)"(.*?)\)\s*(?=game\s*\(|$)',
    re.IGNORECASE | re.DOTALL,
)
_CLRMAME_ROM_CRC = re.compile(r'\bcrc\s+([0-9a-fA-F]+)\b')
_CLRMAME_ROM_MD5 = re.compile(r'\bmd5\s+([0-9a-fA-F]+)\b')
_CLRMAME_ROM_SHA1 = re.compile(r'\bsha1\s+([0-9a-fA-F]+)\b')
_CLRMAME_ROM_SIZE = re.compile(r'\bsize\s+(\d+)\b')
_CLRMAME_HEADER_NAME = re.compile(
    r'(?:clrmamepro|dat)\s*\(\s*.*?name\s+"([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)


def normalize_region(raw: str | None) -> str:
    text = (raw or '').strip().upper()
    aliases = {
        'US': 'USA',
        'U': 'USA',
        'NA': 'USA',
        'EUROPE': 'EUR',
        'EU': 'EUR',
        'E': 'EUR',
        'PAL': 'EUR',
        'JAPAN': 'JPN',
        'JP': 'JPN',
        'J': 'JPN',
        'NTSC-J': 'JPN',
        'W': 'WORLD',
        'WORLDWIDE': 'WORLD',
        'BRAZIL': 'BRA',
        'BR': 'BRA',
        'KOREA': 'KOR',
        'KR': 'KOR',
        'SOUTH KOREA': 'KOR',
        'AUSTRALIA': 'AUS',
        'AU': 'AUS',
        'UK': 'GBR',
        'GB': 'GBR',
        'UNITED KINGDOM': 'GBR',
        'GREAT BRITAIN': 'GBR',
        'FRANCE': 'FRA',
        'FR': 'FRA',
        'GERMANY': 'DEU',
        'DE': 'DEU',
        'GER': 'DEU',
        'SPAIN': 'ESP',
        'ES': 'ESP',
        'CHINA': 'CHN',
        'CN': 'CHN',
        'PRC': 'CHN',
    }
    text = aliases.get(text, text)
    if text in VALID_REGIONS:
        return text
    return 'OTHER'


def normalize_source(raw: str | None) -> str:
    text = (raw or 'nointro').strip().lower()
    return text if text in VALID_SOURCES else 'other'


def normalize_set_title(name: str | None) -> str:
    """Normalize DAT / library title for fuzzy ownership matching."""
    return normalize_set_title_from_peel(name)


def _rom_attrs_from_xml_game(node: ET.Element) -> dict[str, Any]:
    rom = None
    for child in list(node):
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == 'rom':
            rom = child
            break
    if rom is None:
        # MAME softlists nest <rom> under <part><dataarea>; take the first one
        # anywhere below the node rather than treating the entry as hashless.
        for desc in node.iter():
            if desc is not node and desc.tag.rsplit('}', 1)[-1] == 'rom':
                rom = desc
                break
    if rom is None:
        return {}
    size_raw = rom.attrib.get('size')
    try:
        size = int(size_raw) if size_raw else None
    except ValueError:
        size = None
    return {
        'crc': (rom.attrib.get('crc') or '').lower() or None,
        'md5': (rom.attrib.get('md5') or '').lower() or None,
        'sha1': (rom.attrib.get('sha1') or '').lower() or None,
        'size': size,
        'serial': rom.attrib.get('serial') or None,
    }


def parse_dat_xml(text: str, *, source: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    root = ET.fromstring(text)
    prefer_description = (source or '').strip().lower() in DESCRIPTION_TITLED_SOURCES

    def local(tag: str) -> str:
        return tag.rsplit('}', 1)[-1]

    def find_child(parent: ET.Element, name: str) -> ET.Element | None:
        for child in list(parent):
            if local(child.tag) == name:
                return child
        return None

    datafile = root if local(root.tag) == 'datafile' else None
    if datafile is None:
        for node in root.iter():
            if local(node.tag) == 'datafile':
                datafile = node
                break
    if datafile is None:
        datafile = root

    header_name = ''
    header = find_child(datafile, 'header')
    if header is not None:
        name_el = find_child(header, 'name')
        desc_el = find_child(header, 'description')
        if name_el is not None and name_el.text:
            header_name = name_el.text.strip()
        elif desc_el is not None and desc_el.text:
            header_name = desc_el.text.strip()

    entries: list[dict[str, Any]] = []
    by_norm: dict[str, int] = {}
    for node in list(datafile):
        if local(node.tag) not in ('game', 'machine', 'software'):
            continue
        name = (node.attrib.get('name') or '').strip()
        desc = find_child(node, 'description')
        desc_text = desc.text.strip() if desc is not None and desc.text else ''
        # MAME (and softlists): name="pacman" is the set id, <description> the
        # title a member would recognise. Match on the title, keep the id.
        if prefer_description and desc_text:
            name = desc_text
        if not name:
            name = desc_text
        if not name:
            continue
        norm = normalize_set_title(name)
        if not norm:
            continue
        parent = (node.attrib.get('cloneof') or node.attrib.get('romof') or '').strip() or None
        row = {
            'name': name,
            'normalized_name': norm,
            'parent_name': parent,
            **_rom_attrs_from_xml_game(node),
        }
        # One row per title. When a DAT lists the same title for several
        # regions, keep the one the household would want (REGION_PREF_ORDER),
        # not whichever the file happened to list first -- that is the 1G1R
        # region preference, applied at parse time so completion counts it once.
        if norm in by_norm:
            kept = entries[by_norm[norm]]
            if _region_rank(name) < _region_rank(kept['name']):
                entries[by_norm[norm]] = row
            continue
        by_norm[norm] = len(entries)
        entries.append(row)
    return header_name, entries


def _region_rank(dat_name: str) -> int:
    """Position of the entry's region in REGION_PREF_ORDER (unknown sorts last)."""
    try:
        from oneirodex.utils.rom_name_peel import parse_console_rom_label

        region = parse_console_rom_label(dat_name).get('rom_region')
    except Exception:  # noqa: BLE001
        region = None
    region = normalize_region(region) if region else None
    try:
        return REGION_PREF_ORDER.index(region) if region else len(REGION_PREF_ORDER)
    except ValueError:
        return len(REGION_PREF_ORDER)


def parse_dat_clrmame(text: str) -> tuple[str, list[dict[str, Any]]]:
    header_m = _CLRMAME_HEADER_NAME.search(text)
    header_name = header_m.group(1).strip() if header_m else ''
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _CLRMAME_GAME.finditer(text):
        name = match.group(1).strip()
        body = match.group(2) or ''
        norm = normalize_set_title(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        crc_m = _CLRMAME_ROM_CRC.search(body)
        md5_m = _CLRMAME_ROM_MD5.search(body)
        sha1_m = _CLRMAME_ROM_SHA1.search(body)
        size_m = _CLRMAME_ROM_SIZE.search(body)
        entries.append({
            'name': name,
            'normalized_name': norm,
            'crc': crc_m.group(1).lower() if crc_m else None,
            'md5': md5_m.group(1).lower() if md5_m else None,
            'sha1': sha1_m.group(1).lower() if sha1_m else None,
            'size': int(size_m.group(1)) if size_m else None,
            'serial': None,
        })
    return header_name, entries


def parse_dat_bytes(raw: bytes | str, *, source: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(raw, bytes):
        text = raw.decode('utf-8', errors='replace')
    else:
        text = raw
    stripped = text.lstrip()
    if stripped.startswith('<'):
        return parse_dat_xml(text, source=source)
    header, entries = parse_dat_clrmame(text)
    if entries:
        return header, entries
    raise ValueError('Unrecognized DAT format (expected XML datafile or ClrMamePro text)')


def validate_library_platform(platform_key: str) -> str:
    key = (platform_key or '').strip().upper()
    try:
        LibraryPlatform[key]
    except KeyError as exc:
        raise ValueError(f'Unknown library_platform: {platform_key}') from exc
    return key


def list_reference_sets() -> list[dict]:
    rows = db.session.execute(
        select(ReferenceSet).order_by(ReferenceSet.library_platform, ReferenceSet.region)
    ).scalars().all()
    return [r.to_dict() for r in rows]


def delete_reference_set(set_id: int) -> bool:
    row = db.session.get(ReferenceSet, set_id)
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


class ReferenceSetReplacementConflict(ValueError):
    """Replacing an installed platform/region requires explicit permission."""


def upsert_reference_set(
    *,
    library_platform: str,
    region: str,
    source: str,
    dat_bytes: bytes,
    name: str | None = None,
    uploader_id: int | None = None,
    allow_replace: bool = True,
) -> ReferenceSet:
    platform = validate_library_platform(library_platform)
    region_n = normalize_region(region)
    source_n = normalize_source(source)
    header_name, entries = parse_dat_bytes(dat_bytes, source=source_n)
    if not entries:
        raise ValueError('DAT contained no game entries')

    existing = db.session.execute(
        select(ReferenceSet).filter_by(library_platform=platform, region=region_n)
    ).scalars().first()
    if existing:
        if not allow_replace:
            raise ReferenceSetReplacementConflict('Reference set replacement requires confirmation')
        db.session.delete(existing)
        db.session.flush()

    ref = ReferenceSet(
        library_platform=platform,
        region=region_n,
        source=source_n,
        name=(name or header_name or f'{platform} {region_n}')[:255],
        entry_count=len(entries),
        uploaded_by_user_id=uploader_id,
    )
    db.session.add(ref)
    db.session.flush()
    for entry in entries:
        db.session.add(
            ReferenceSetEntry(
                set_id=ref.id,
                name=entry['name'][:512],
                normalized_name=entry['normalized_name'][:512],
                parent_name=(entry.get('parent_name') or None) and str(entry['parent_name'])[:512],
                crc=entry.get('crc'),
                md5=entry.get('md5'),
                sha1=entry.get('sha1'),
                size=entry.get('size'),
                serial=(entry.get('serial') or None),
            )
        )
    db.session.commit()
    return ref


def _owned_identity(library_platform: str, user) -> dict[str, set[str]]:
    platform = LibraryPlatform[library_platform]
    query = (
        select(Game.name, Game.full_disk_path, Game.file_crc, Game.file_md5, Game.file_sha1)
        .join(Library, Game.library_uuid == Library.uuid)
        .filter(Library.platform == platform)
    )
    query = apply_game_access_filters(query, user)
    titles: set[str] = set()
    crcs: set[str] = set()
    md5s: set[str] = set()
    sha1s: set[str] = set()
    for name, path, crc, md5, sha1 in db.session.execute(query).all():
        norm = normalize_set_title(name)
        if norm:
            titles.add(norm)
        if path:
            bn = normalize_set_title(Path(path).name)
            if bn:
                titles.add(bn)
        if crc:
            crcs.add(crc.lower())
        if md5:
            md5s.add(md5.lower())
        if sha1:
            sha1s.add(sha1.lower())
    return {'titles': titles, 'crc': crcs, 'md5': md5s, 'sha1': sha1s}


def preferred_entries(set_id: int) -> list[ReferenceSetEntry]:
    """The 1G1R view of a set: parents only (INSP-5).

    A DAT with parent/clone data lists every clone; completion should count
    each *game* once, so clones drop out here. A set with no clone data (most
    No-Intro uploads) is returned whole -- its region duplicates were already
    collapsed to the household's preferred region at parse time.
    """
    rows = list(
        db.session.execute(
            select(ReferenceSetEntry).filter_by(set_id=set_id)
        ).scalars().all()
    )
    if any(getattr(r, 'parent_name', None) for r in rows):
        return [r for r in rows if not getattr(r, 'parent_name', None)]
    return rows


def clone_parent_for(
    *,
    library_platform: str | None,
    crc: str | None = None,
    md5: str | None = None,
    sha1: str | None = None,
    name: str | None = None,
) -> str | None:
    """Name of the parent set when these digests belong to a *clone* entry, else None.

    Advisory only: the duplicate check reports `clone_of_owned_parent` so an
    operator can see that a second dump of an owned game arrived; nothing is
    marked or deleted on the strength of it.
    """
    key = (library_platform or '').strip().upper()
    norm = normalize_set_title(name) if name else ''
    if not key or not (crc or md5 or sha1 or norm):
        return None
    set_ids = [
        row for row in db.session.execute(
            select(ReferenceSet.id).filter_by(library_platform=key)
        ).scalars().all()
    ]
    if not set_ids:
        return None
    conds = []
    if crc:
        conds.append(ReferenceSetEntry.crc == crc.lower())
    if md5:
        conds.append(ReferenceSetEntry.md5 == md5.lower())
    if sha1:
        conds.append(ReferenceSetEntry.sha1 == sha1.lower())
    if norm:
        conds.append(ReferenceSetEntry.normalized_name == norm)
    hit = db.session.execute(
        select(ReferenceSetEntry.parent_name)
        .filter(ReferenceSetEntry.set_id.in_(set_ids), ReferenceSetEntry.parent_name.isnot(None), or_(*conds))
        .limit(1)
    ).scalar()
    return hit or None


def _match_entry(entry: ReferenceSetEntry, owned: dict[str, set[str]]) -> str | None:
    """Return match method name or None."""
    if entry.crc and entry.crc.lower() in owned['crc']:
        return 'crc'
    if entry.md5 and entry.md5.lower() in owned['md5']:
        return 'md5'
    if entry.sha1 and entry.sha1.lower() in owned['sha1']:
        return 'sha1'
    if entry.normalized_name in owned['titles']:
        return 'title'
    return None


def compute_set_completion(
    *,
    library_platform: str,
    region: str,
    user,
    include_matched: bool = True,
    missing_limit: int | None = None,
) -> dict[str, Any] | None:
    platform = validate_library_platform(library_platform)
    region_n = normalize_region(region)
    ref = db.session.execute(
        select(ReferenceSet).filter_by(library_platform=platform, region=region_n)
    ).scalars().first()
    if not ref:
        return None

    entries = preferred_entries(ref.id)
    owned = _owned_identity(platform, user)
    matched: list[dict] = []
    missing: list[dict] = []
    method_counts = {'crc': 0, 'md5': 0, 'sha1': 0, 'title': 0}
    for entry in entries:
        method = _match_entry(entry, owned)
        item = {
            'name': entry.name,
            'normalized_name': entry.normalized_name,
            'crc': entry.crc,
        }
        if method:
            item['match_method'] = method
            method_counts[method] = method_counts.get(method, 0) + 1
            matched.append(item)
        else:
            missing.append(item)

    total = len(entries)
    owned_count = len(matched)
    missing_count = len(missing)
    percent = round((owned_count / total) * 100, 1) if total else 0.0
    if missing_limit is not None:
        missing = missing[:missing_limit]
    result = {
        'library_platform': platform,
        'region': region_n,
        'source': ref.source,
        'set_id': ref.id,
        'set_name': ref.name,
        'total': total,
        'owned': owned_count,
        'missing_count': missing_count,
        'percent': percent,
        'missing': missing,
        'match_methods': method_counts,
    }
    if include_matched:
        result['matched'] = matched
    return result


def region_completions_for_platform(library_platform: str, user) -> list[dict[str, Any]]:
    """Per-region set completion summaries for heatmap chips (preferred order first)."""
    platform = validate_library_platform(library_platform)
    rows = db.session.execute(
        select(ReferenceSet).filter_by(library_platform=platform)
    ).scalars().all()
    if not rows:
        return []
    by_region = {r.region: r for r in rows}
    ordered_regions: list[str] = []
    for region in REGION_PREF_ORDER:
        if region in by_region:
            ordered_regions.append(region)
    for region in sorted(by_region.keys()):
        if region not in ordered_regions:
            ordered_regions.append(region)
    out: list[dict[str, Any]] = []
    for region in ordered_regions:
        report = compute_set_completion(
            library_platform=platform,
            region=region,
            user=user,
            include_matched=False,
            missing_limit=0,
        )
        if not report:
            continue
        out.append(
            {
                'region': report['region'],
                'owned': report['owned'],
                'total': report['total'],
                'percent': report['percent'],
                'missing_count': report['missing_count'],
                'set_id': report['set_id'],
            }
        )
    return out


def preferred_completion_for_platform(library_platform: str, user) -> dict[str, Any] | None:
    regions = region_completions_for_platform(library_platform, user)
    if not regions:
        return None
    preferred = dict(regions[0])
    preferred['regions'] = regions
    return preferred



def completion_summaries_by_platform(user) -> dict[str, dict[str, Any]]:
    """Map library_platform → preferred set_completion summary."""
    platforms = {
        r.library_platform
        for r in db.session.execute(select(ReferenceSet.library_platform)).all()
    }
    out: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        try:
            summary = preferred_completion_for_platform(platform, user)
        except ValueError:
            continue
        if summary:
            out[platform] = summary
    return out


def rehash_library_platform(library_platform: str, *, limit: int = 5000) -> dict[str, int]:
    """Compute file hashes for games on a platform that have a disk path."""
    from oneirodex.utils.rom_hash import apply_file_hashes_to_game

    platform = validate_library_platform(library_platform)
    enum_plat = LibraryPlatform[platform]
    games = list(
        db.session.execute(
            select(Game)
            .join(Library, Game.library_uuid == Library.uuid)
            .filter(Library.platform == enum_plat)
            .filter(Game.full_disk_path.isnot(None))
            .limit(limit)
        ).scalars().all()
    )
    hashed = 0
    skipped = 0
    for game in games:
        if apply_file_hashes_to_game(game):
            hashed += 1
        else:
            skipped += 1
    db.session.commit()
    return {'platform': platform, 'considered': len(games), 'hashed': hashed, 'skipped': skipped}


def is_dat_hash_identify_platform(library_platform: str | None) -> bool:
    """True for console/ROM leaves — skip native PC store libraries."""
    key = (library_platform or '').strip().upper()
    if not key or key in NATIVE_PC_PLATFORMS:
        return False
    try:
        LibraryPlatform[key]
    except KeyError:
        return False
    return True


def _entry_match_method(
    entry: ReferenceSetEntry,
    *,
    crc: str | None,
    md5: str | None,
    sha1: str | None,
) -> str | None:
    """Strongest hash that links file digests to this DAT row (sha1 > md5 > crc)."""
    if sha1 and entry.sha1 and entry.sha1.lower() == sha1:
        return 'sha1'
    if md5 and entry.md5 and entry.md5.lower() == md5:
        return 'md5'
    if crc and entry.crc and entry.crc.lower() == crc:
        return 'crc'
    return None


def lookup_unique_dat_hash_hit(
    *,
    library_platform: str,
    crc: str | None = None,
    md5: str | None = None,
    sha1: str | None = None,
) -> dict[str, Any] | None:
    """
    Return a unique DAT entry for console identify when exactly one title matches.

    Scope: all uploaded reference sets for ``library_platform``. Uniqueness is by
    ``normalized_name`` (region/rev peel). Multiple distinct titles sharing a hash
    (multicart / ambiguous) → None. No DAT / no hashable digests → None.
    Title-only matching is never used here.
    """
    if not is_dat_hash_identify_platform(library_platform):
        return None
    platform = validate_library_platform(library_platform)
    crc_n = (crc or '').strip().lower() or None
    md5_n = (md5 or '').strip().lower() or None
    sha1_n = (sha1 or '').strip().lower() or None
    if not crc_n and not md5_n and not sha1_n:
        return None

    set_ids = list(
        db.session.execute(
            select(ReferenceSet.id).filter_by(library_platform=platform)
        ).scalars().all()
    )
    if not set_ids:
        return None

    clauses = []
    if crc_n:
        clauses.append(ReferenceSetEntry.crc == crc_n)
    if md5_n:
        clauses.append(ReferenceSetEntry.md5 == md5_n)
    if sha1_n:
        clauses.append(ReferenceSetEntry.sha1 == sha1_n)
    if not clauses:
        return None

    rows = list(
        db.session.execute(
            select(ReferenceSetEntry, ReferenceSet)
            .join(ReferenceSet, ReferenceSetEntry.set_id == ReferenceSet.id)
            .filter(ReferenceSetEntry.set_id.in_(set_ids))
            .filter(or_(*clauses))
        ).all()
    )
    if not rows:
        return None

    by_norm: dict[str, tuple[ReferenceSetEntry, ReferenceSet, str]] = {}
    for entry, ref in rows:
        method = _entry_match_method(entry, crc=crc_n, md5=md5_n, sha1=sha1_n)
        if not method:
            continue
        norm = (entry.normalized_name or '').strip()
        if not norm:
            continue
        prev = by_norm.get(norm)
        if prev is None:
            by_norm[norm] = (entry, ref, method)
            continue
        # Prefer stronger method / keep first entry for same title.
        rank = {'sha1': 3, 'md5': 2, 'crc': 1}
        if rank.get(method, 0) > rank.get(prev[2], 0):
            by_norm[norm] = (entry, ref, method)

    if len(by_norm) != 1:
        return None

    entry, ref, method = next(iter(by_norm.values()))
    return {
        'name': entry.name,
        'normalized_name': entry.normalized_name,
        'crc': entry.crc,
        'md5': entry.md5,
        'sha1': entry.sha1,
        'match_method': method,
        'set_id': ref.id,
        'set_name': ref.name,
        'source': ref.source,
        'region': ref.region,
        'library_platform': platform,
        'identify_path': 'dat_hash',
        'match_reason': f'dat_unique_{method}',
    }


def _unique_hit_from_inner_digests(
    *,
    library_platform: str,
    digests: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """
    Map inner digests → unique DAT title.

    Zero hits or multiple distinct normalized titles → None (skip / no invent).
    """
    by_norm: dict[str, tuple[dict[str, Any], dict[str, str]]] = {}
    for digest in digests:
        hit = lookup_unique_dat_hash_hit(
            library_platform=library_platform,
            crc=digest.get('crc'),
            md5=digest.get('md5'),
            sha1=digest.get('sha1'),
        )
        if not hit:
            continue
        norm = (hit.get('normalized_name') or '').strip()
        if not norm:
            continue
        prev = by_norm.get(norm)
        if prev is None:
            by_norm[norm] = (hit, digest)
            continue
        # Same title from another member — keep stronger method if present.
        rank = {'sha1': 3, 'md5': 2, 'crc': 1}
        if rank.get(hit.get('match_method') or '', 0) > rank.get(
            prev[0].get('match_method') or '', 0,
        ):
            by_norm[norm] = (hit, digest)
    if len(by_norm) != 1:
        return None
    return next(iter(by_norm.values()))


def try_dat_hash_identify(
    *,
    full_disk_path: str,
    library_uuid: str,
    library_platform: str | None,
    size: int = 0,
    hashes: dict[str, str] | None = None,
) -> Game | None:
    """
    IGDB-miss DAT short-circuit: unique CRC/MD5/SHA1 → custom-range Game.

    Returns Game on unique hit; None on miss / ambiguous / PC / unhashable /
    missing reference set. Caller commits. Never fuzzy-matches DAT titles.

    When the outer file hash misses and the path is zip/7z/rar, optionally hash
    inner primary dump candidate(s) (``DAT_HASH_INNER_ARCHIVE``, default ON).
    Exactly one unique DAT title from inner digests identifies; zero or multiple
    distinct titles → skip.
    """
    if not is_dat_hash_identify_platform(library_platform):
        return None

    from oneirodex.utils.rom_hash import (
        hash_archive_inner_primary_dumps,
        hash_rom_file,
    )
    from oneirodex.utils.software_identify import create_custom_kinded_game

    digest = hashes
    if digest is None:
        digest = hash_rom_file(full_disk_path)

    platform_key = library_platform or ''
    hit = None
    identify_via = 'outer'
    if digest:
        hit = lookup_unique_dat_hash_hit(
            library_platform=platform_key,
            crc=digest.get('crc'),
            md5=digest.get('md5'),
            sha1=digest.get('sha1'),
        )

    inner_digests: list[dict] = []
    if not hit:
        inner_digests = hash_archive_inner_primary_dumps(
            full_disk_path,
            platform=platform_key,
        )
        if inner_digests:
            resolved = _unique_hit_from_inner_digests(
                library_platform=platform_key,
                digests=inner_digests,
            )
            if resolved:
                hit, digest = resolved
                identify_via = 'inner_archive'

    if not hit:
        # INSP-31 (v11 H1a): no local DAT knows this file -- ask the keyless
        # community hash service, outer digest first, then the inner dumps.
        # Same contract as a DAT hit (unique digest -> name); None on any miss.
        from oneirodex.utils.hash_identify import hash_identify_hit

        for candidate in ([digest] if digest else []) + list(inner_digests):
            hit = hash_identify_hit(candidate, library_platform=platform_key)
            if hit:
                digest = candidate
                identify_via = 'hash_service'
                break

    if not hit or not digest:
        return None

    name = (hit.get('name') or '').strip() or 'Untitled'
    method = hit.get('match_method') or 'hash'
    source = hit.get('source') or 'dat'
    via_note = 'inner archive dump, ' if identify_via == 'inner_archive' else ''
    if identify_via == 'hash_service':
        igdb_note = f' IGDB #{hit["igdb_id"]}.' if hit.get('igdb_id') else ''
        summary = (
            f'Identified via the community hash service ({hit.get("set_name") or "unknown"}, '
            f'unique {method}).{igdb_note}'
        )
    else:
        summary = (
            f'Identified via reference DAT ({source}, {via_note}unique {method}). '
            f'Set: {hit.get("set_name") or "unknown"}.'
        )

    def _stamp_hashes(game: Game) -> None:
        game.file_crc = digest.get('crc')
        game.file_md5 = digest.get('md5')
        game.file_sha1 = digest.get('sha1')

    existing = db.session.execute(
        select(Game).filter(
            Game.full_disk_path == full_disk_path,
            Game.library_uuid == library_uuid,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.name = name
        existing.summary = summary
        existing.date_identified = datetime.now(timezone.utc)
        existing.path_status = 'ok'
        _stamp_hashes(existing)
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(existing, full_disk_path or name)
        except Exception:
            pass
        db.session.flush()
        return existing

    game = create_custom_kinded_game(
        name=name,
        full_disk_path=full_disk_path,
        library_uuid=library_uuid,
        item_kind='game',
        summary=summary,
        size=size,
    )
    _stamp_hashes(game)
    db.session.flush()
    return game
