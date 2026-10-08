"""RetroAchievements — community achievement sets matched by ROM hash (R1/R2).

Opt-in like every keyed provider: ``RETROACHIEVEMENTS_API_KEY`` (a web API
key from retroachievements.org → Settings → Keys) and the account's
``RETROACHIEVEMENTS_USERNAME``. Unset means honest *no data*: nothing is
matched, no badge is promised, the plugin reports ``available``.

What this is and is not:

* It **matches** each ROM to a set the community has published, by the hash
  RetroAchievements itself uses — which is *not* the file MD5 for several
  systems (iNES header stripped, SNES copier header stripped, N64 normalised to
  big-endian, …). The rules mirror rcheevos' ``rc_hash`` for the cartridge
  systems below; disc systems are deliberately unsupported here rather than
  matched wrongly.
* It **reports** a member's progress on a matched set when they have entered
  their RetroAchievements username, read from the public API. It does **not**
  unlock anything: browser play has no rcheevos runtime, so nothing played
  here ever counts, hardcore or softcore. The member surface says so.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import Game, Library, RetroAchievementsIndexEntry
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.platform import LibraryPlatform

log = logging.getLogger(__name__)

API_BASE = 'https://retroachievements.org/API'
SITE_GAME_URL = 'https://retroachievements.org/game/{id}'
MEDIA_BASE = 'https://media.retroachievements.org'
BADGE_URL = MEDIA_BASE + '/Badge/{badge}.png'

# Library platform key -> RetroAchievements console id. Only systems whose
# hash we can compute honestly (see ra_hash_bytes). Disc systems (PSX, Saturn,
# Sega CD, NDS, 3DO, Neo Geo CD, …) are absent on purpose.
RA_CONSOLE_IDS: dict[str, int] = {
    'SEGA_MD': 1,
    'N64': 2,
    'SNES': 3,
    'GB': 4,
    'GBA': 5,
    'GBC': 6,
    'NES': 7,
    'PCE': 8,
    'SEGA_32X': 10,
    'SEGA_MS': 11,
    'LYNX': 13,
    'NGP': 14,
    'NGPC': 14,
    'SEGA_GG': 15,
    'JAGUAR': 17,
    'O2EM': 23,
    'ATARI_2600': 25,
    'VB': 28,
    'SEGA_SG1000': 33,
    'COLECO': 44,
    'INTV': 45,
    'VECTREX': 46,
    'ATARI_5200': 50,
    'ATARI_7800': 51,
    'WS': 53,
    'CHAF': 57,
}

# Largest cartridge we will read into memory to hash (N64 tops out at 64 MiB).
MAX_ROM_BYTES = 96 * 1024 * 1024
INDEX_TTL = timedelta(hours=24)
HTTP_TIMEOUT = 30
PROGRESS_CACHE_TTL = timedelta(minutes=10)


# --- configuration -----------------------------------------------------------


def credentials() -> tuple[str, str]:
    """(username, API key), with environment values taking precedence over admin settings."""
    settings = None
    try:
        settings = global_settings_row()
    except RuntimeError:
        # Hash helpers can be used without an application context in tooling.
        pass
    return (
        (
            os.getenv('RETROACHIEVEMENTS_USERNAME')
            or getattr(settings, 'retroachievements_username', None)
            or ''
        ).strip(),
        (
            os.getenv('RETROACHIEVEMENTS_API_KEY')
            or getattr(settings, 'retroachievements_api_key', None)
            or ''
        ).strip(),
    )


def settings_summary() -> dict[str, Any]:
    """Admin-safe credential state. Never return the API key itself."""
    settings = global_settings_row()
    env_username = (os.getenv('RETROACHIEVEMENTS_USERNAME') or '').strip()
    env_key = (os.getenv('RETROACHIEVEMENTS_API_KEY') or '').strip()
    db_username = (getattr(settings, 'retroachievements_username', None) or '').strip()
    db_key = (getattr(settings, 'retroachievements_api_key', None) or '').strip()
    username, key = credentials()
    return {
        'username': username or None,
        'has_key': bool(key),
        'username_source': 'environment' if env_username else ('admin' if db_username else None),
        'key_source': 'environment' if env_key else ('admin' if db_key else None),
        'environment_username': bool(env_username),
        'environment_key': bool(env_key),
    }


def save_settings(
    *,
    username: str | None,
    api_key: str | None,
    clear_api_key: bool = False,
) -> dict[str, Any]:
    """Persist admin-provided credentials without returning the API key."""
    from oneirodex.utils.global_settings import global_settings_row_or_create

    settings = global_settings_row_or_create()
    if username is not None:
        settings.retroachievements_username = username.strip() or None
    if clear_api_key:
        settings.retroachievements_api_key = None
    elif api_key:
        settings.retroachievements_api_key = api_key.strip()
    db.session.commit()
    return settings_summary()


def configured() -> bool:
    user, key = credentials()
    return bool(user and key)


def console_id_for_platform(platform_key: str | None) -> int | None:
    key = str(platform_key or '').strip().upper()
    return RA_CONSOLE_IDS.get(key)


def supported_platforms() -> list[str]:
    return sorted(RA_CONSOLE_IDS)


# --- hashing -----------------------------------------------------------------


def _nes_hash(data: bytes) -> str:
    """iNES / NES 2.0: skip the header (and any trainer), hash PRG+CHR.

    The trainer matters. Flags6 bit 2 means a 512-byte trainer sits between the
    header and PRG, and rcheevos skips it before hashing. Hashing from offset 16
    regardless swallowed the trainer as if it were the first 512 bytes of PRG
    and then truncated 512 bytes off the real end — producing a digest that is
    neither the trainer-inclusive nor the trainer-exclusive one, so every
    trainer ROM in a library silently matched nothing at all.
    """
    if data[:4] == b'NES\x1a' and len(data) > 16:
        prg = data[4] * 16384
        chr_ = data[5] * 8192
        if (data[7] & 0x0C) == 0x08:  # NES 2.0 size high nibbles
            prg += ((data[9] & 0x0F) << 8) * 16384
            chr_ += ((data[9] >> 4) << 8) * 8192
        size = prg + chr_
        start = 16 + (512 if data[6] & 0x04 else 0)
        body = data[start:]
        if 0 < size <= len(body):
            body = body[:size]
        return hashlib.md5(body).hexdigest()
    if data[:4] == b'FDS\x1a' and len(data) > 16:
        return hashlib.md5(data[16:]).hexdigest()
    return hashlib.md5(data).hexdigest()


def _snes_hash(data: bytes) -> str:
    """Copier header: 512 bytes when the size is 512 past a multiple of 8 KiB."""
    if len(data) % 8192 == 512:
        data = data[512:]
    return hashlib.md5(data).hexdigest()


def _lynx_hash(data: bytes) -> str:
    if data[:4] == b'LYNX' and len(data) > 64:
        data = data[64:]
    return hashlib.md5(data).hexdigest()


def _pce_hash(data: bytes) -> str:
    """ROM data is a multiple of 128 KiB; a 512-byte remainder is a header."""
    calc = (len(data) // 0x20000) * 0x20000
    if len(data) - calc == 512:
        data = data[512:]
    return hashlib.md5(data).hexdigest()


def _a7800_hash(data: bytes) -> str:
    if data[:10] == b'\x01ATARI7800' and len(data) > 128:
        data = data[128:]
    return hashlib.md5(data).hexdigest()


def _n64_hash(data: bytes) -> str:
    """Normalise to z64 (big-endian) byte order, then hash.

    The swaps are whole-word operations, so a dump whose length is not a
    multiple of the word size cannot be swapped wholesale: the strided slices
    come out different lengths and the assignment raises ValueError. A
    truncated or corrupt ROM is exactly the kind of file a real library
    contains, and one of them must not abort the platform's entire match run —
    so only the complete words are swapped and any short tail is left as-is.
    """
    if len(data) < 4:
        return hashlib.md5(data).hexdigest()
    magic = data[:4]
    if magic == b'\x37\x80\x40\x12':  # v64: 16-bit byteswapped
        end = len(data) - (len(data) % 2)
        body = bytearray(data[:end])
        body[0::2], body[1::2] = data[1:end:2], data[0:end:2]
        data = bytes(body) + data[end:]
    elif magic == b'\x40\x12\x37\x80':  # n64: 32-bit little-endian words
        end = len(data) - (len(data) % 4)
        body = bytearray(data[:end])
        body[0::4], body[1::4], body[2::4], body[3::4] = (
            data[3:end:4],
            data[2:end:4],
            data[1:end:4],
            data[0:end:4],
        )
        data = bytes(body) + data[end:]
    return hashlib.md5(data).hexdigest()


_HASHERS = {
    'NES': _nes_hash,
    'SNES': _snes_hash,
    'LYNX': _lynx_hash,
    'PCE': _pce_hash,
    'ATARI_7800': _a7800_hash,
    'N64': _n64_hash,
}


def ra_hash_bytes(data: bytes, platform_key: str | None) -> str | None:
    """The hash RetroAchievements would compute for this ROM image, or None."""
    key = str(platform_key or '').strip().upper()
    if key not in RA_CONSOLE_IDS or not data:
        return None
    hasher = _HASHERS.get(key)
    return hasher(data) if hasher else hashlib.md5(data).hexdigest()


def _read_rom_bytes(path: str | Path, platform_key: str | None) -> bytes | None:
    """Bytes of the primary ROM: the file itself, or the one dump inside an archive."""
    from oneirodex.utils.rom_archive import (
        ArchiveRomError,
        choose_rom_member,
        extract_rom_from_7z,
        extract_rom_from_rar,
        list_roms_in_archive,
        path_is_supported_archive,
    )
    from oneirodex.utils.rom_hash import resolve_hashable_file

    target = resolve_hashable_file(path)
    if target is None:
        return None
    try:
        if not path_is_supported_archive(target):
            if target.stat().st_size > MAX_ROM_BYTES:
                return None
            return target.read_bytes()
        members = list_roms_in_archive(str(target))
        if not members:
            return None
        member = choose_rom_member(members, platform=platform_key)
        size = next((s for name, s in members if name == member), 0)
        if size > MAX_ROM_BYTES:
            return None
        ext = target.suffix.lower()
        if ext == '.zip':
            with zipfile.ZipFile(target, 'r') as archive:
                with archive.open(member) as handle:
                    return handle.read(MAX_ROM_BYTES + 1)[:MAX_ROM_BYTES]
        with tempfile.TemporaryDirectory(prefix='od-ra-') as tmp:
            if ext == '.7z':
                dest = extract_rom_from_7z(str(target), tmp, member=member, platform=platform_key)
            elif ext == '.rar':
                dest = extract_rom_from_rar(str(target), tmp, member=member, platform=platform_key)
            else:
                return None
            return Path(dest).read_bytes()
    except (OSError, KeyError, zipfile.BadZipFile, ArchiveRomError):
        return None


def ra_hash_for_game(game: Game) -> str | None:
    """Compute (never cached here) the RetroAchievements hash for a game's ROM."""
    key = _platform_key(game)
    if not key or key not in RA_CONSOLE_IDS:
        return None
    data = _read_rom_bytes(getattr(game, 'full_disk_path', None) or '', key)
    if data is None:
        return None
    return ra_hash_bytes(data, key)


def _platform_key(game: Game) -> str | None:
    library = getattr(game, 'library', None)
    platform = getattr(library, 'platform', None) if library is not None else None
    if platform is None:
        return None
    return getattr(platform, 'name', None) or str(platform)


# --- the hash index ----------------------------------------------------------


def _api_get(endpoint: str, params: dict[str, Any]) -> Any:
    user, key = credentials()
    if not (user and key):
        raise RuntimeError('RetroAchievements is not configured')
    query = {'z': user, 'y': key, **params}
    response = requests.get(
        f'{API_BASE}/{endpoint}',
        params=query,
        timeout=HTTP_TIMEOUT,
        headers={'User-Agent': 'Oneirodex (household game library)'},
    )
    response.raise_for_status()
    return response.json()


def fetch_console_index(console_id: int) -> list[dict[str, Any]]:
    """Games with achievements for one console, with their hashes (`h=1`, `f=1`)."""
    rows = _api_get('API_GetGameList.php', {'i': int(console_id), 'h': 1, 'f': 1})
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            game_id = int(row.get('ID') or 0)
        except (TypeError, ValueError):
            continue
        if not game_id:
            continue
        out.append({
            'ra_game_id': game_id,
            'title': str(row.get('Title') or '')[:255],
            'image_icon': str(row.get('ImageIcon') or '')[:255],
            'num_achievements': int(row.get('NumAchievements') or 0),
            'points': int(row.get('Points') or 0),
            'hashes': [str(h).lower() for h in (row.get('Hashes') or []) if h],
        })
    return out


def index_age(console_id: int) -> datetime | None:
    stamp = db.session.execute(
        select(func.max(RetroAchievementsIndexEntry.fetched_at)).where(
            RetroAchievementsIndexEntry.console_id == int(console_id),
        ),
    ).scalar()
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def refresh_console_index(console_id: int, *, force: bool = False) -> int:
    """Replace the stored index for one console when stale. Returns rows stored."""
    age = index_age(console_id)
    if not force and age is not None and datetime.now(timezone.utc) - age < INDEX_TTL:
        return db.session.execute(
            select(func.count(RetroAchievementsIndexEntry.id)).where(
                RetroAchievementsIndexEntry.console_id == int(console_id),
            ),
        ).scalar() or 0
    games = fetch_console_index(console_id)
    now = datetime.now(timezone.utc)
    db.session.query(RetroAchievementsIndexEntry).filter_by(console_id=int(console_id)).delete()
    stored = 0
    for game in games:
        for digest in game['hashes']:
            db.session.add(RetroAchievementsIndexEntry(
                console_id=int(console_id),
                ra_game_id=game['ra_game_id'],
                title=game['title'],
                image_icon=game['image_icon'],
                num_achievements=game['num_achievements'],
                points=game['points'],
                md5=digest[:32],
                fetched_at=now,
            ))
            stored += 1
    db.session.commit()
    return stored


def lookup_hash(console_id: int, digest: str) -> RetroAchievementsIndexEntry | None:
    if not digest:
        return None
    return db.session.execute(
        select(RetroAchievementsIndexEntry).where(
            RetroAchievementsIndexEntry.console_id == int(console_id),
            RetroAchievementsIndexEntry.md5 == digest.lower(),
        ).limit(1),
    ).scalars().first()


# --- matching ----------------------------------------------------------------


def match_game(game: Game, *, rehash: bool = False) -> dict[str, Any]:
    """Hash (if needed) and look the game up in the index; persist the result.

    Returns ``{'hashed', 'matched', 'ra_game_id', 'achievements'}``. Does not
    commit — callers batch.
    """
    key = _platform_key(game)
    console_id = console_id_for_platform(key)
    result = {'hashed': False, 'matched': False, 'ra_game_id': None, 'achievements': 0}
    if console_id is None:
        return result
    digest = getattr(game, 'ra_hash', None)
    if rehash or not digest:
        digest = ra_hash_for_game(game)
        game.ra_hash = digest
        result['hashed'] = bool(digest)
    if not digest:
        game.ra_game_id = None
        game.ra_achievements = None
        return result
    hit = lookup_hash(console_id, digest)
    if hit is None:
        game.ra_game_id = None
        game.ra_achievements = None
        return result
    game.ra_game_id = hit.ra_game_id
    game.ra_achievements = hit.num_achievements
    result.update({'matched': True, 'ra_game_id': hit.ra_game_id, 'achievements': hit.num_achievements})
    return result


def match_platform(platform_key: str, *, limit: int = 5000, rehash: bool = False) -> dict[str, Any]:
    """Refresh the console's index if stale, then match every game on the platform."""
    key = str(platform_key or '').strip().upper()
    console_id = console_id_for_platform(key)
    if console_id is None:
        raise ValueError(f'{key or "(none)"} is not a RetroAchievements-hashable system here')
    if not configured():
        raise RuntimeError('RetroAchievements is not configured (RETROACHIEVEMENTS_USERNAME / _API_KEY)')
    indexed = refresh_console_index(console_id)
    games = list(
        db.session.execute(
            select(Game)
            .join(Library, Game.library_uuid == Library.uuid)
            .filter(Library.platform == LibraryPlatform[key])
            .filter(Game.full_disk_path.isnot(None))
            .limit(limit)
        ).scalars().all()
    )
    hashed = matched = 0
    for game in games:
        outcome = match_game(game, rehash=rehash)
        hashed += int(outcome['hashed'])
        matched += int(outcome['matched'])
    db.session.commit()
    return {
        'platform': key,
        'console_id': console_id,
        'indexed_hashes': indexed,
        'considered': len(games),
        'hashed': hashed,
        'matched': matched,
    }


def supports_achievements(game: Game) -> bool:
    """R2: true only for a matched set that actually carries achievements."""
    return bool(getattr(game, 'ra_game_id', None)) and int(getattr(game, 'ra_achievements', 0) or 0) > 0


def achievement_fields(game: Game) -> dict[str, Any]:
    """Browse / details fields. Never promises what is not there."""
    supported = supports_achievements(game)
    return {
        'supports_achievements': supported,
        'ra_game_id': int(game.ra_game_id) if supported else None,
        'ra_achievements': int(game.ra_achievements or 0) if supported else 0,
        'ra_url': SITE_GAME_URL.format(id=int(game.ra_game_id)) if supported else None,
    }


def status_summary() -> dict[str, Any]:
    """Admin status: configured, per-console index age/size, matched counts."""
    user, key = credentials()
    per_console: list[dict[str, Any]] = []
    if configured():
        counts = dict(
            db.session.execute(
                select(RetroAchievementsIndexEntry.console_id, func.count(RetroAchievementsIndexEntry.id))
                .group_by(RetroAchievementsIndexEntry.console_id),
            ).all(),
        )
        matched = dict(
            db.session.execute(
                select(Library.platform, func.count(Game.id))
                .join(Library, Game.library_uuid == Library.uuid)
                .where(Game.ra_game_id.isnot(None), Game.ra_achievements > 0)
                .group_by(Library.platform),
            ).all(),
        )
        matched_by_key = {getattr(p, 'name', str(p)): n for p, n in matched.items()}
        for platform_key in supported_platforms():
            console_id = RA_CONSOLE_IDS[platform_key]
            age = index_age(console_id)
            per_console.append({
                'platform': platform_key,
                'console_id': console_id,
                'indexed_hashes': int(counts.get(console_id, 0)),
                'index_fetched_at': age.isoformat() if age else None,
                'matched_games': int(matched_by_key.get(platform_key, 0)),
            })
    return {
        'configured': configured(),
        'username': user or None,
        'has_key': bool(key),
        'supported_platforms': supported_platforms(),
        'consoles': per_console,
    }


# --- member progress ---------------------------------------------------------

_progress_cache: dict[tuple[str, int], tuple[datetime, dict[str, Any]]] = {}


def clear_progress_cache() -> None:
    _progress_cache.clear()


def fetch_member_progress(ra_username: str, ra_game_id: int) -> dict[str, Any] | None:
    """Achievements of a set with this member's unlocks. Cached 10 minutes.

    Read-only against the public API; the member's own username is public
    information on the site. Returns None when unconfigured or on any error —
    the surface then shows the set without a personal column.
    """
    name = str(ra_username or '').strip()
    if not name or not configured():
        return None
    cache_key = (name.lower(), int(ra_game_id))
    now = datetime.now(timezone.utc)
    hit = _progress_cache.get(cache_key)
    if hit and now - hit[0] < PROGRESS_CACHE_TTL:
        return hit[1]
    try:
        raw = _api_get('API_GetGameInfoAndUserProgress.php', {'g': int(ra_game_id), 'u': name})
    except Exception as exc:  # noqa: BLE001 — a provider outage is "no personal data", not a 500
        log.info('RetroAchievements progress unavailable for %s/%s: %s', name, ra_game_id, exc)
        return None
    achievements = raw.get('Achievements') if isinstance(raw, dict) else None
    rows: list[dict[str, Any]] = []
    if isinstance(achievements, dict):
        for entry in achievements.values():
            if not isinstance(entry, dict):
                continue
            rows.append({
                'id': int(entry.get('ID') or 0),
                'title': str(entry.get('Title') or ''),
                'description': str(entry.get('Description') or ''),
                'points': int(entry.get('Points') or 0),
                'badge_url': BADGE_URL.format(badge=str(entry.get('BadgeName') or '00000')),
                'earned': bool(entry.get('DateEarned')),
                'earned_hardcore': bool(entry.get('DateEarnedHardcore')),
                'display_order': int(entry.get('DisplayOrder') or 0),
            })
    rows.sort(key=lambda r: (r['display_order'], r['id']))
    payload = {
        'username': name,
        'total': int(raw.get('NumAchievements') or len(rows)) if isinstance(raw, dict) else len(rows),
        'earned': int(raw.get('NumAwardedToUser') or 0) if isinstance(raw, dict) else 0,
        'earned_hardcore': int(raw.get('NumAwardedToUserHardcore') or 0) if isinstance(raw, dict) else 0,
        'completion': str(raw.get('UserCompletion') or '') if isinstance(raw, dict) else '',
        'completion_hardcore': str(raw.get('UserCompletionHardcore') or '') if isinstance(raw, dict) else '',
        'achievements': rows,
    }
    _progress_cache[cache_key] = (now, payload)
    return payload
