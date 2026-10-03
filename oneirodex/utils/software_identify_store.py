"""Stage D store-candidate builders: Steam / GOG / Epic hits to candidate rows,
the DRM-field scrub, source enable list and title corroboration.

Split out of ``software_identify`` in the v11 cycle (H-D.4) as a pure move.
Pure functions only -- the orchestration that calls the store searches (and
that tests patch) stays in ``software_identify``.
"""
from __future__ import annotations

import re



from oneirodex.utils.item_kind import (
    DEFAULT_ITEM_KIND,
    infer_item_kind_from_steam_type,
    is_denied_auto_game_match,
    normalize_item_kind,
)

STAGE_D_SOURCE_ORDER = ('steam', 'gog', 'epic')


def _casefold_title(value: str | None) -> str:
    return (value or '').casefold().strip()


_TITLE_KEY_STRIP = re.compile(r"[\u2122\u00ae\u00a9\u2120'\u2019\u2018`]")
_TITLE_KEY_NON_ALNUM = re.compile(r'[^a-z0-9]+')


def title_match_key(value: str | None) -> str:
    """Store-title key for exact matching that survives how stores print titles.

    Folder names lose punctuation that store listings keep, so plain casefold
    equality missed most real pairs: ``Assassins Creed Rogue`` vs Steam's
    ``Assassin's Creed Rogue``; ``Star Wars Knights of the Old Republic`` vs
    ``STAR WARS\u2122 - Knights of the Old Republic\u2122``; ``Death Horizon
    Cyberfusion`` vs ``Death Horizon: Cyberfusion``. Equal *after* this
    normalisation is still an exact title -- no edit distance, no prefix -- so the
    unique-hit rule that guards auto-import is unchanged.
    """
    import unicodedata

    # Strip the trademark marks first: NFKD would turn the TM sign into "TM".
    text = _TITLE_KEY_STRIP.sub('', (value or '').casefold().replace('&', ' and '))
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = _TITLE_KEY_NON_ALNUM.sub(' ', text).strip()
    words = text.split()
    if len(words) > 1 and words[0] == 'the':
        words = words[1:]
    return ' '.join(words)


# Ownership / identify payloads must never carry install or download queue fields.
_FORBIDDEN_DRM_URL_KEYS = frozenset({
    'download_url',
    'install_url',
    'installer_url',
    'direct_download',
    'magnet',
    'torrent_url',
    'depot_url',
    'manifest_url',
})


def scrub_stage_d_payload(payload: dict) -> dict:
    """Drop install/download queue fields — register-only ownership/metadata."""
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if k not in _FORBIDDEN_DRM_URL_KEYS}


def _candidate_from_steam_details(
    details: dict,
    *,
    steam_app_id: int,
    fallback_name: str,
) -> dict:
    name = (details.get('name') or fallback_name or '').strip() or fallback_name
    steam_type = details.get('steam_type')
    kind = infer_item_kind_from_steam_type(steam_type, name=name)
    if is_denied_auto_game_match(name) and kind == DEFAULT_ITEM_KIND:
        kind = 'tool'
    return scrub_stage_d_payload({
        'source': 'steam',
        'name': name,
        'summary': details.get('short_description'),
        'cover_url': details.get('header_image'),
        'steam_app_id': int(steam_app_id),
        'steam_type': steam_type,
        'item_kind': kind,
        'url': f'https://store.steampowered.com/app/{int(steam_app_id)}/',
        'identify_path': 'stage_d',
        'match_mode': 'app_id',
    })


def _candidate_from_steam_hit(hit: dict, *, match_mode: str) -> dict:
    app_id = hit.get('steam_app_id') or hit.get('id')
    try:
        app_id_int = int(app_id) if app_id is not None else None
    except (TypeError, ValueError):
        app_id_int = None
    name = (hit.get('name') or '').strip()
    steam_type = hit.get('steam_type')
    kind = hit.get('item_kind') or infer_item_kind_from_steam_type(
        steam_type, name=name,
    )
    if is_denied_auto_game_match(name) and normalize_item_kind(kind) == DEFAULT_ITEM_KIND:
        kind = 'tool'
    return scrub_stage_d_payload({
        'source': 'steam',
        'name': name,
        'summary': hit.get('summary'),
        'cover_url': hit.get('cover_url'),
        'steam_app_id': app_id_int,
        'steam_type': steam_type,
        'item_kind': normalize_item_kind(kind),
        'url': hit.get('url') or (
            f'https://store.steampowered.com/app/{app_id_int}/' if app_id_int else None
        ),
        'identify_path': 'stage_d',
        'match_mode': match_mode,
    })


def _candidate_from_gog_hit(hit: dict) -> dict:
    gog_id = hit.get('gog_id') or hit.get('id')
    try:
        gog_id_int = int(gog_id) if gog_id is not None else None
    except (TypeError, ValueError):
        gog_id_int = None
    name = (hit.get('name') or '').strip()
    kind = DEFAULT_ITEM_KIND
    if is_denied_auto_game_match(name):
        kind = 'tool'
    # Store page only — never install/download URLs.
    store_url = hit.get('url')
    if store_url and any(
        token in str(store_url).lower()
        for token in ('download', 'install', 'checkout', 'cart')
    ):
        store_url = None
    return scrub_stage_d_payload({
        'source': 'gog',
        'name': name,
        'summary': hit.get('summary'),
        'cover_url': hit.get('cover_url'),
        'gog_id': gog_id_int,
        'slug': hit.get('slug'),
        'item_kind': kind,
        'url': store_url,
        'identify_path': 'stage_d',
        'match_mode': 'exact_title',
    })


def _candidate_from_epic_hit(hit: dict) -> dict:
    epic_id = hit.get('epic_id') or hit.get('id')
    name = (hit.get('name') or '').strip()
    kind = DEFAULT_ITEM_KIND
    if is_denied_auto_game_match(name):
        kind = 'tool'
    store_url = hit.get('url')
    if store_url and any(
        token in str(store_url).lower()
        for token in ('download', 'install', 'checkout', 'cart')
    ):
        store_url = None
    return scrub_stage_d_payload({
        'source': 'epic',
        'name': name,
        'summary': hit.get('summary'),
        'cover_url': hit.get('cover_url'),
        'epic_id': epic_id,
        'slug': hit.get('slug'),
        'item_kind': kind,
        'url': store_url,
        'identify_path': 'stage_d',
        'match_mode': 'exact_title',
        'ownership_only': True,
    })


def igdb_retry_title_from_store(
    candidate: dict | None,
    already: list[str] | tuple[str, ...] | set[str] | None = None,
) -> str | None:
    """Store canonical title we have not already searched on IGDB.

    Used after an IGDB miss: exact Steam/GOG/Epic title → one more IGDB pass
    before creating a custom-range Stage D game. Improves hit-rate for messy
    folder names without fuzzy auto-import.
    """
    if not isinstance(candidate, dict):
        return None
    name = (candidate.get('name') or '').strip()
    if not name:
        return None
    seen = {
        (item or '').casefold().strip()
        for item in (already or [])
        if (item or '').strip()
    }
    if name.casefold().strip() in seen:
        return None
    return name


def _enabled_stage_d_sources(sources=None) -> tuple[str, ...]:
    if sources is None:
        try:
            from oneirodex.utils.metadata_providers import stage_d_source_ids

            sources = stage_d_source_ids()
        except Exception:
            sources = STAGE_D_SOURCE_ORDER
    enabled = {str(item).strip().lower() for item in (sources or ()) if item}
    return tuple(item for item in STAGE_D_SOURCE_ORDER if item in enabled)


def _stage_d_titles_corroborate(folder_title: str | None, store_title: str | None) -> bool:
    """
    Conservative App-ID title gate: folder label must match or be a clear
    primary-title prefix of the store title (remaster / subtitle tails OK).

    Rejects wrong-namespace paren digits that resolve to an unrelated Steam app.
    """
    folder = _casefold_title(folder_title or '')
    store = _casefold_title(store_title or '')
    if not folder or not store:
        return False
    if folder == store:
        return True
    # "Broken Sword 2" vs "Broken Sword 2 - the Smoking Mirror: Remastered"
    for sep in (' - ', ': ', ' — ', ' – '):
        head = store.split(sep, 1)[0].strip()
        if head and folder == head:
            return True
    if store.startswith(folder + ' ') or store.startswith(folder + ':'):
        return True
    if store.startswith(folder + '-'):
        return True
    return False
