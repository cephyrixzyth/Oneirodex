"""No-key hash-identify source (INSP-31, v11 cycle H1a).

Oneirodex already hashes every ROM it scans (``rom_hash.py``: CRC32 / MD5 /
SHA1, inner-archive dumps too) and matches those digests against reference
DATs the operator uploaded (``set_completion.try_dat_hash_identify``). This
module is the *network* half of that idea: when no local DAT knows the file,
ask a community hash-lookup service that aggregates the signature sets
(No-Intro / Redump / TOSEC / MAME / WHDLoad class) and proxies an IGDB id.

Design rules, in order of importance:

* **No account, no key.** The default service is a public, keyless lookup.
  ``HASH_IDENTIFY_BASE_URL`` points somewhere else if the operator prefers.
* **No data, never a silent miss.** Every failure -- disabled, offline, 4xx,
  5xx, unparseable body, no name in the answer -- returns ``None``. Callers
  treat ``None`` as "the service had nothing", exactly like a DAT miss.
* **Off under pytest** unless a test says otherwise (same guard as the store
  catalogue signals), so no suite ever reaches the network by accident.
* **Every request goes through** :func:`oneirodex.utils.http_safe.safe_request`
  with the outbound-URL validator, like every other source.
* **Identify, not enrichment.** A hash answer is *identity* (this file is
  that game), which the enrichment cascade deliberately never writes. So this
  plugs into the DAT short-circuit, not into ``metadata_cascade``.

The response parser is deliberately generous about shape: it looks for a game
name (and, when present, a platform and an IGDB id) under the field names the
service documents today and a few obvious variants, and gives up cleanly
otherwise. A schema change on their side is a *miss*, not a crash.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlparse

from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import validate_user_outbound_http_url

SOURCE_ID = 'hash_identify'
DEFAULT_BASE_URL = 'https://hasheous.org'
# Path template of the keyless lookup. ``{kind}`` is md5 | sha1 | crc.
LOOKUP_PATH = '/api/v1/Lookup/ByHash/{kind}/{digest}'
# Order of preference: the stronger digest first; CRC alone is weak.
HASH_KINDS = ('md5', 'sha1', 'crc')
TIMEOUT_SECONDS = 8


def base_url() -> str:
    raw = (os.environ.get('HASH_IDENTIFY_BASE_URL') or DEFAULT_BASE_URL).strip()
    return raw.rstrip('/')


def _testing() -> bool:
    try:
        from flask import current_app, has_app_context

        return bool(has_app_context() and current_app.config.get('TESTING'))
    except Exception:  # noqa: BLE001
        return False


def is_enabled() -> bool:
    """On by default; ``ENABLE_HASH_IDENTIFY=false`` turns it off; off under pytest
    unless the test sets ``HASH_IDENTIFY_IN_TESTS=1`` (so a mocked transport can
    be exercised)."""
    flag = (os.environ.get('ENABLE_HASH_IDENTIFY') or '1').strip().lower()
    if flag in ('0', 'false', 'no', 'off'):
        return False
    if _testing() and (os.environ.get('HASH_IDENTIFY_IN_TESTS') or '').strip().lower() not in ('1', 'true', 'yes'):
        return False
    try:
        from oneirodex.utils.metadata_providers import resolve_metadata_providers

        if resolve_metadata_providers().get(SOURCE_ID) is False:
            return False
    except Exception:  # noqa: BLE001 -- a settings hiccup must not disable identify
        pass
    return bool(base_url())


def service_host() -> str:
    try:
        return urlparse(base_url()).hostname or base_url()
    except Exception:  # noqa: BLE001
        return base_url()


def _dig(data: Any, *paths: tuple[str, ...]) -> Any:
    """First non-empty value found at any of the dotted paths."""
    for path in paths:
        node = data
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and node not in (None, '', [], {}):
            return node
    return None


def _parse_lookup(body: Any) -> dict | None:
    """Reduce a service answer to ``{name, platform, igdb_id, source_url}`` or None."""
    if not isinstance(body, dict):
        return None
    name = _dig(
        body,
        ('signature', 'game', 'name'),
        ('signature', 'rom', 'name'),
        ('game', 'name'),
        ('name',),
        ('title',),
    )
    if not isinstance(name, str) or not name.strip():
        return None
    platform = _dig(
        body,
        ('signature', 'game', 'system'),
        ('signature', 'game', 'platform'),
        ('platform', 'name'),
        ('platform',),
        ('system',),
    )
    igdb_id = None
    # Metadata links come either as a flat id or as a list of {source, id} rows.
    flat = _dig(body, ('metadata', 'igdb', 'id'), ('igdb_id',), ('igdbId',))
    if flat is not None:
        try:
            igdb_id = int(flat)
        except (TypeError, ValueError):
            igdb_id = None
    else:
        rows = _dig(body, ('metadata',), ('signature', 'metadata'))
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                src = str(row.get('source') or row.get('provider') or '').strip().lower()
                if src == 'igdb':
                    try:
                        igdb_id = int(row.get('id') or row.get('immutableId') or 0) or None
                    except (TypeError, ValueError):
                        igdb_id = None
                    if igdb_id:
                        break
    return {
        'name': name.strip(),
        'platform': str(platform).strip() if isinstance(platform, str) else None,
        'igdb_id': igdb_id,
        'source_url': _dig(body, ('signature', 'game', 'url'), ('url',)),
    }


def lookup_by_hashes(hashes: dict | None, *, library_platform: str | None = None) -> dict | None:
    """Ask the service about a file's digests. ``None`` on any miss or failure.

    Tries MD5, then SHA1, then CRC. The first answer that names a game wins;
    the result also says which digest matched (``match_method``) and where it
    came from (``source``, ``service``).
    """
    if not hashes or not is_enabled():
        return None
    for kind in HASH_KINDS:
        digest = (hashes.get(kind) or '').strip().lower()
        if not digest:
            continue
        url = base_url() + LOOKUP_PATH.format(kind=kind, digest=quote(digest, safe=''))
        try:
            response = safe_request(
                'GET',
                url,
                validator=validate_user_outbound_http_url,
                timeout=TIMEOUT_SECONDS,
                headers={'Accept': 'application/json', 'User-Agent': 'Oneirodex hash-identify'},
            )
        except Exception:  # noqa: BLE001 -- blocked URL, DNS, timeout: all a miss
            return None
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            return None
        try:
            parsed = _parse_lookup(response.json())
        except ValueError:
            return None
        if parsed:
            parsed.update({
                'match_method': kind,
                'source': SOURCE_ID,
                'service': service_host(),
                'library_platform': library_platform,
            })
            return parsed
    return None


def hash_identify_hit(hashes: dict | None, *, library_platform: str | None = None) -> dict | None:
    """The DAT-hit shape ``try_dat_hash_identify`` already consumes, or None.

    ``set_name`` names the service so the game summary says where the identity
    came from, the same way a DAT hit names its set.
    """
    found = lookup_by_hashes(hashes, library_platform=library_platform)
    if not found:
        return None
    return {
        'name': found['name'],
        'match_method': found['match_method'],
        'source': SOURCE_ID,
        'set_name': found['service'],
        'igdb_id': found.get('igdb_id'),
        'platform': found.get('platform'),
    }
