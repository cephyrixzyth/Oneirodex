"""Named mod profiles and the shareable export code (INSP-37, v11 cycle H2d).

A *profile* is a named set of tracked-mod ids on one game's pack. Activating
it is the one-click enable set: rows in the profile turn on, every other row
turns off, and the companion's next *Apply mods* stages exactly that set in
load order (it already reads ``enabled`` + ``load_order``; nothing new to
teach it).

The *export code* is ``od-mod:`` + base64url of a small JSON document -- the
profile name and, for each mod, the fields another household needs to
recreate the row (name, version, loader, ``source_url``). Import validates
the code against the receiving pack: a mod already tracked there (by id, or
by ``source_url``) joins the profile; one that is not is **reported as
missing**, never invented -- a librarian adds it by hand or from the
catalogue, then imports again. No file moves in either direction.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from oneirodex.utils.game_mods import load_mods, loader_conflicts, save_mods

EXPORT_PREFIX = 'od-mod:'
EXPORT_VERSION = 1
MAX_CODE_BYTES = 64 * 1024
_SLUG = re.compile(r'[^a-z0-9]+')


class ProfileConflict(ValueError):
    """A shared profile no longer matches its receiving pack."""


def _profile_id(name: str, taken: set[str]) -> str:
    base = _SLUG.sub('-', (name or '').lower()).strip('-')[:40] or 'profile'
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f'{base}-{n}'
        n += 1
    return candidate


def list_profiles(game_uuid: str) -> dict[str, Any]:
    pack = load_mods(game_uuid)
    return {'profiles': pack['profiles'], 'active_profile': pack['active_profile']}


def create_profile(game_uuid: str, *, name: str, mod_ids: list[str] | None = None,
                   requirements: list[dict] | None = None, unresolved: list[str] | None = None,
                   import_order: list[str] | None = None) -> dict[str, Any]:
    """A new profile. ``mod_ids`` ``None`` means "the rows enabled right now"."""
    pack = load_mods(game_uuid)
    name = (name or '').strip()[:120]
    if not name:
        raise ValueError('Profile name required')
    if len(pack['profiles']) >= 32:
        raise ValueError('Too many profiles for one game (32)')
    known = {row['id'] for row in pack['mods']}
    if mod_ids is None:
        ids = [row['id'] for row in pack['mods'] if row.get('enabled')]
    else:
        ids = [str(m) for m in mod_ids if str(m) in known]
    profile = {'id': _profile_id(name, {p['id'] for p in pack['profiles']}), 'name': name, 'mod_ids': ids}
    if requirements:
        profile['requirements'] = requirements
    if import_order:
        profile['import_order'] = import_order
    if unresolved:
        profile['unresolved'] = unresolved
    saved = save_mods(game_uuid, pack['mods'], profiles=[*pack['profiles'], profile])
    return next(p for p in saved['profiles'] if p['id'] == profile['id'])


def delete_profile(game_uuid: str, profile_id: str) -> bool:
    pack = load_mods(game_uuid)
    rest = [p for p in pack['profiles'] if p['id'] != profile_id]
    if len(rest) == len(pack['profiles']):
        return False
    active = '' if pack['active_profile'] == profile_id else None
    save_mods(game_uuid, pack['mods'], profiles=rest, active_profile=active)
    return True


def _check_import_receipt(profile: dict, mods: list[dict]) -> None:
    tracked = {row['id']: row for row in mods}
    if profile.get('unresolved'):
        raise ProfileConflict('Resolve the missing mods and import the profile again.')
    for req in profile.get('requirements', []):
        row = tracked.get(req['id'])
        if row is None or any(req.get(key) and req[key] != row.get(key)
                              for key in ('version', 'loader', 'source_url')):
            raise ProfileConflict('The tracked mods have changed. Check versions, loaders and sources.')
        if 'requires' in req and set(req['requires']) != set(row.get('requires', [])):
            raise ProfileConflict('The tracked dependencies have changed. Review the requirements.')
    expected_order = profile.get('import_order', [])
    if expected_order:
        selected = set(expected_order)
        # load_mods supplies the exact ordered list used by the companion.
        if [row['id'] for row in mods if row['id'] in selected] != expected_order:
            raise ProfileConflict('The tracked load order differs from the shared profile.')


def activate_profile(game_uuid: str, profile_id: str) -> dict[str, Any]:
    """Enable exactly the profile's rows and remember which profile is on."""
    pack = load_mods(game_uuid)
    profile = next((p for p in pack['profiles'] if p['id'] == profile_id), None)
    if profile is None:
        raise LookupError('Profile not found')
    wanted = set(profile['mod_ids'])
    mods = [{**row, 'enabled': row['id'] in wanted} for row in pack['mods']]
    _check_import_receipt(profile, mods)
    if loader_conflicts({**pack, 'mods': mods}) or any(
        row['enabled'] and not set(row['requires']).issubset(wanted) for row in mods
    ):
        raise ValueError('Resolve the profile loader or dependency conflicts before activating.')
    return save_mods(game_uuid, mods, active_profile=profile_id)


def export_profile(game_uuid: str, profile_id: str) -> str:
    pack = load_mods(game_uuid)
    profile = next((p for p in pack['profiles'] if p['id'] == profile_id), None)
    if profile is None:
        raise LookupError('Profile not found')
    _check_import_receipt(profile, pack['mods'])
    by_id = {row['id']: row for row in pack['mods']}
    doc = {
        'v': EXPORT_VERSION,
        'name': profile['name'],
        'default_loader': pack['default_loader'],
        'mods': [
            {
                'id': mid,
                'name': by_id[mid]['name'],
                'version': by_id[mid]['version'],
                'loader': by_id[mid]['loader'],
                'source_url': by_id[mid]['source_url'],
                'load_order': by_id[mid]['load_order'],
                'requires': by_id[mid].get('requires', []),
            }
            for mid in profile['mod_ids']
            if mid in by_id
        ],
    }
    raw = json.dumps(doc, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    body = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(body) > MAX_CODE_BYTES:
        raise ValueError('Profile is too large for a share code. Split it into smaller profiles.')
    return EXPORT_PREFIX + body


def decode_export(code: str) -> dict[str, Any]:
    """The JSON document inside an export code, or ``ValueError``."""
    text = (code or '').strip()
    if not text.startswith(EXPORT_PREFIX):
        raise ValueError('Not an Oneirodex mod profile code (expected od-mod:…)')
    body = text[len(EXPORT_PREFIX):].strip()
    if not body or len(body) > MAX_CODE_BYTES:
        raise ValueError('Profile code is empty or too long')
    try:
        raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        doc = json.loads(raw.decode('utf-8'))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError('Profile code is not readable') from exc
    if not isinstance(doc, dict) or doc.get('v') != EXPORT_VERSION or not isinstance(doc.get('mods'), list):
        raise ValueError('Profile code has an unknown shape or version')
    return doc


def import_profile(game_uuid: str, code: str, *, name: str | None = None) -> dict[str, Any]:
    """Create a profile from a code, matched against *this* pack.

    A mod in the code joins the profile when the pack already tracks it (same
    id, else same ``source_url``). The rest come back as ``missing`` rows --
    everything a librarian needs to add them -- and are **not** created.
    """
    doc = decode_export(code)
    pack = load_mods(game_uuid)
    requirements = []
    source_ids = {}
    entries = []
    if len(doc['mods']) > 256:
        raise ValueError('A shared profile supports at most 256 entries')
    matched: list[str] = []
    missing: list[dict[str, Any]] = []
    for entry in doc['mods']:
        if not isinstance(entry, dict):
            raise ValueError('A shared profile entry is invalid')
        mid = str(entry.get('id') or '').strip()
        url = str(entry.get('source_url') or '').strip()
        expected = {key: str(entry.get(key) or '').strip() for key in ('version', 'loader', 'source_url')}
        candidates = [row for row in pack['mods'] if row['id'] == mid or (url and row['source_url'] == url)]
        compatible = [row for row in candidates if all(not value or row.get(key) == value
                                                       for key, value in expected.items())]
        row = next((row for row in compatible if row['id'] == mid), None)
        if row is None and len(compatible) == 1:
            row = compatible[0]
        if row is not None:
            if row['id'] in matched or (mid and mid in source_ids):
                raise ValueError('Two shared entries identify the same mod')
            if mid:
                source_ids[mid] = row['id']
            matched.append(row['id'])
            receipt = {'id': row['id'], **expected}
            requirements.append(receipt)
            entries.append((entry, receipt))
        else:
            missing.append({
                'name': str(entry.get('name') or mid or url)[:256],
                'version': str(entry.get('version') or '')[:64],
                'loader': str(entry.get('loader') or '')[:64],
                'source_url': url[:2048],
                'load_order': entry.get('load_order'),
                'requires': entry.get('requires', []),
            })
    unresolved = [item['name'] or 'Unknown mod' for item in missing]
    ordered = []
    for entry, receipt in entries:
        if 'requires' in entry:
            deps = entry['requires']
            if not isinstance(deps, list) or len(deps) > 64 or any(not isinstance(dep, str) for dep in deps):
                raise ValueError('Invalid dependency list in the shared profile')
            receipt['requires'] = [source_ids[dep] for dep in deps if dep in source_ids]
            for dep in deps:
                if dep not in source_ids:
                    unresolved.append(f"{entry.get('name') or receipt['id']} requires {dep}"[:256])
        if type(entry.get('load_order')) is int:
            ordered.append((entry['load_order'], str(entry.get('name') or '').lower(), receipt['id']))
    import_order = [mid for _, _, mid in sorted(ordered, key=lambda item: item[:2])] if len(ordered) == len(entries) else []
    profile = create_profile(game_uuid, name=(name or str(doc.get('name') or 'Imported profile')),
                             mod_ids=matched, requirements=requirements, unresolved=unresolved, import_order=import_order)
    return {
        'profile': profile,
        'matched': len(matched),
        'missing': missing,
        'suggested_default_loader': str(doc.get('default_loader') or ''),
    }

