"""Software / experience identify helpers (non-IGDB Main Game path).

When IGDB has no high-confidence game match, enrich Unmatched proposals with
Steam software hits and suggested item_kind. Stage D (W20-5a) may auto-create a
custom-range Game from an exact Steam App ID / storesearch title, GOG exact
title, or Epic exact title before logging Unmatched (operator toggles under
Integrations → Metadata). Stage E (W21-BE-2) may attach propose-only
MobyGames / TheGamesDB exact-title hints after Stage D miss — never creates a
Game from those catalogs in W21. Never invents DRM download queues.

The v11 cycle (H-D.4) moved the leaf helpers out as pure moves --
``software_identify_store`` (Stage D candidate rows), ``software_identify_custom_game``
(custom kinded ``Game`` rows) and ``tgdb_platform_match`` (Stage E platform
matching). The orchestration, and every name callers import, stays here.
"""

from __future__ import annotations

import re

from flask import current_app, has_app_context

from oneirodex import db
from oneirodex.models import Game, GameURL, UnmatchedFolder
from oneirodex.platform import NATIVE_PC_PLATFORMS
from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.item_kind import (
    DEFAULT_ITEM_KIND,
    is_denied_auto_game_match,
    normalize_item_kind,
    suggest_item_kind,
)
from oneirodex.utils.match_scoring import score_candidate
from oneirodex.utils.secondary_scrapers import (
    search_epic_games,
    search_gog_games,
    search_mobygames_games,
    search_steam_games,
    search_thegamesdb_games,
)
# H-D.4 split: leaf helpers moved out; the public ones are re-exported here
# because callers and tests import them from this module.
from oneirodex.utils.software_identify_custom_game import (  # noqa: F401
    CUSTOM_IGDB_BASE,
    create_custom_kinded_game,
    upsert_stage_d_custom_game,
)
from oneirodex.utils.software_identify_store import (  # noqa: F401
    STAGE_D_SOURCE_ORDER,
    igdb_retry_title_from_store,
    scrub_stage_d_payload,
    _casefold_title,
    title_match_key,
    _candidate_from_epic_hit,
    _candidate_from_gog_hit,
    _candidate_from_steam_details,
    _candidate_from_steam_hit,
    _enabled_stage_d_sources,
    _stage_d_titles_corroborate,
)
from oneirodex.utils.tgdb_platform_match import (  # noqa: F401
    filter_tgdb_hits_for_platform,
    tgdb_platform_matches,
    _stage_e_candidate_row,
)


def build_software_search_queries(raw_label: str) -> list[str]:
    """Ordered unique queries for Steam software identify (incl. VR re-attach)."""
    parsed = parse_game_label(raw_label)
    cleaned = (parsed.get('cleaned_name') or '').strip()
    queries: list[str] = []
    if cleaned:
        queries.append(cleaned)
        if parsed.get('had_vr_suffix'):
            vr_form = f'{cleaned} VR'
            if vr_form not in queries:
                queries.append(vr_form)
    # Raw basename (light) as last resort when peel emptied the label oddly
    basename = (raw_label or '').replace('\\', '/').rstrip('/').split('/')[-1].strip()
    if basename and basename not in queries and basename.casefold() != cleaned.casefold():
        queries.append(basename)
    # Dedupe case-insensitively while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def collect_software_identify_candidates(
    raw_label: str,
    *,
    limit: int = 10,
) -> list[dict]:
    """
    Search Steam (games + software) for identify candidates.

    Scores by cleaned name; tags item_kind / is_software. Does not call IGDB.
    """
    queries = build_software_search_queries(raw_label)
    if not queries:
        return []
    primary = queries[0]
    seen_ids: set[int] = set()
    ranked: list[dict] = []

    for query in queries:
        hits = search_steam_games(query, limit=limit, include_software=True)
        for hit in hits:
            app_id = hit.get('steam_app_id') or hit.get('id')
            try:
                app_id_int = int(app_id) if app_id is not None else None
            except (TypeError, ValueError):
                app_id_int = None
            if app_id_int is not None and app_id_int in seen_ids:
                continue
            if app_id_int is not None:
                seen_ids.add(app_id_int)
            name = hit.get('name') or ''
            score = float(score_candidate(primary, name) or 0.0)
            # Prefer exact/near matches against VR-reattached query as well
            for q in queries[1:]:
                score = max(score, float(score_candidate(q, name) or 0.0))
            kind = hit.get('item_kind') or suggest_item_kind(
                name, steam_type=hit.get('steam_type'),
            )
            if is_denied_auto_game_match(name) or is_denied_auto_game_match(primary):
                kind = 'tool'
            ranked.append({
                **hit,
                'steam_app_id': app_id_int,
                'match_score': round(score, 4),
                'item_kind': kind,
                'suggested_kind': kind,
                'deny_auto_game': is_denied_auto_game_match(name)
                or is_denied_auto_game_match(primary),
            })

    ranked.sort(key=lambda c: float(c.get('match_score') or 0), reverse=True)
    return ranked[:limit]


def enrich_proposal_with_software(proposal: dict, raw_label: str) -> dict:
    """Attach Steam software candidates + suggested_kind onto a match proposal."""
    if not isinstance(proposal, dict):
        proposal = {'proposal': {}}
    body = proposal.setdefault('proposal', {})
    software = collect_software_identify_candidates(raw_label, limit=10)
    body['software_candidates'] = [
        {
            'source': c.get('source') or 'steam',
            'steam_app_id': c.get('steam_app_id'),
            'name': c.get('name'),
            'steam_type': c.get('steam_type'),
            'item_kind': c.get('item_kind'),
            'score': c.get('match_score'),
            'url': c.get('url'),
            'cover_url': c.get('cover_url'),
            'is_software': bool(c.get('is_software')),
            'deny_auto_game': bool(c.get('deny_auto_game')),
        }
        for c in software
    ]
    suggested = DEFAULT_ITEM_KIND
    if software:
        top = software[0]
        suggested = normalize_item_kind(top.get('item_kind'))
        if top.get('deny_auto_game'):
            suggested = 'tool'
        elif top.get('is_software') and suggested == 'game':
            suggested = 'tool'
    elif is_denied_auto_game_match(raw_label) or is_denied_auto_game_match(
        body.get('cleaned_name')
    ):
        suggested = 'tool'
    body['suggested_kind'] = suggested
    body['identify_path'] = 'software' if software else 'unmatched'
    return proposal


def exact_title_hits(query: str, hits: list[dict] | None) -> list[dict]:
    """Return store hits whose name equals the query after title normalisation
    (case, \u2122/\u00ae, apostrophes, punctuation, accents, a leading "The").
    Exact only: no prefix, no edit distance."""
    needle = title_match_key(query)
    if not needle:
        return []
    out: list[dict] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        if title_match_key(hit.get('name')) == needle:
            out.append(hit)
    return out


_IDENTITY_NON_ALNUM = re.compile(r'[^a-z0-9]+')


def _identity_key(value: str | None) -> str:
    """Punctuation-tolerant title key: 'Half-Life 2' and 'Half Life 2' agree."""
    text = _IDENTITY_NON_ALNUM.sub(' ', (value or '').casefold()).strip()
    return ' '.join(text.split())


def titles_identify_agree(left: str | None, right: str | None) -> bool:
    key = _identity_key(left)
    return bool(key) and key == _identity_key(right)


def _catalog_http_allowed() -> bool:
    """Skip live Steam/GOG/Moby/TGDB in pytest. Production still consults them."""
    try:
        if has_app_context() and current_app.config.get('TESTING'):
            return False
    except Exception:
        pass
    return True


def gather_catalog_identify_signals(
    cleaned_name: str,
    library_platform: str | None = None,
) -> dict:
    """Exact-title rows from Steam / GOG / unique-exact Moby / TGDB.

    Unique-exact only for MobyGames and TheGamesDB (ambiguous exact is skipped,
    not a veto). Empty when keys are unset or pytest has TESTING=True.
    """
    query = (cleaned_name or '').strip()
    empty = {'rows': [], 'skipped': [], 'stage_e': {}}
    if not query:
        return empty
    if not _catalog_http_allowed():
        return {**empty, 'skipped': ['testing']}

    rows: list[dict] = []
    skipped: list[str] = []
    platform_key = (library_platform or '').strip() or None
    is_console = bool(platform_key) and platform_key not in NATIVE_PC_PLATFORMS

    try:
        steam_hits = search_steam_games(query, limit=10, include_software=False)
    except Exception as err:
        print(f'⚠️ [W34] Steam search failed: {err}')
        steam_hits = []
        skipped.append('steam')
    exact_steam = exact_title_hits(query, steam_hits)
    if len(exact_steam) == 1:
        rows.append(_candidate_from_steam_hit(exact_steam[0], match_mode='exact_title'))

    try:
        gog_hits = search_gog_games(query, limit=10)
    except Exception as err:
        print(f'⚠️ [W34] GOG search failed: {err}')
        gog_hits = []
        skipped.append('gog')
    exact_gog = exact_title_hits(query, gog_hits)
    if len(exact_gog) == 1:
        rows.append(_candidate_from_gog_hit(exact_gog[0]))

    try:
        from oneirodex.utils.providers.mobygames import get_mobygames_api_key

        moby_key = (get_mobygames_api_key() or '').strip()
    except Exception:
        moby_key = ''
    if not moby_key:
        skipped.append('mobygames_key_unset')
    else:
        try:
            moby_hits = search_mobygames_games(query, api_key=moby_key, limit=10)
        except Exception as err:
            print(f'⚠️ [W34] MobyGames search failed: {err}')
            moby_hits = []
        exact_moby = exact_title_hits(query, moby_hits)
        if len(exact_moby) == 1:
            hit = exact_moby[0]
            rows.append({
                'source': 'mobygames',
                'name': (hit.get('name') or '').strip(),
                'match_mode': 'moby_exact',
                'url': (hit.get('url') or '').strip() or None,
                'mobygames_id': hit.get('mobygames_id') or hit.get('id'),
            })

    if is_console:
        try:
            from oneirodex.utils.providers.thegamesdb import get_thegamesdb_api_key

            tgdb_key = (get_thegamesdb_api_key() or '').strip()
        except Exception:
            tgdb_key = ''
        if not tgdb_key:
            skipped.append('thegamesdb_key_unset')
        else:
            try:
                tgdb_hits = search_thegamesdb_games(query, limit=10)
            except Exception as err:
                print(f'⚠️ [W34] TheGamesDB search failed: {err}')
                tgdb_hits = []
            exact_tgdb = exact_title_hits(query, tgdb_hits)
            if len(exact_tgdb) == 1:
                hit = exact_tgdb[0]
                rows.append({
                    'source': 'thegamesdb',
                    'name': (hit.get('name') or '').strip(),
                    'match_mode': 'tgdb_exact',
                    'url': (hit.get('url') or '').strip() or None,
                    'thegamesdb_id': hit.get('thegamesdb_id') or hit.get('id'),
                })

    return {'rows': rows, 'skipped': skipped, 'stage_e': {}}


def corroborate_igdb_with_catalogs(
    *,
    igdb_name: str | None,
    cleaned_name: str | None,
    library_platform: str | None = None,
) -> dict:
    """Compare a high-confidence IGDB title to unique-exact catalog hits.

    ``disagree``: a catalog unique-exact title identity-matches the folder but
    not IGDB (folder Doom / IGDB Doom 3 / Moby Doom). ``agree``: a catalog
    title identity-matches IGDB. Remaster/subtitle tails that match neither
    identity are ``no_signal``, not a veto.
    """
    gathered = gather_catalog_identify_signals(
        cleaned_name or '',
        library_platform,
    )
    agreed: list[dict] = []
    disagreed: list[dict] = []
    for row in gathered.get('rows') or []:
        if not isinstance(row, dict):
            continue
        catalog_name = row.get('name')
        if titles_identify_agree(igdb_name, catalog_name):
            agreed.append(row)
        elif titles_identify_agree(cleaned_name, catalog_name):
            disagreed.append(row)
    if disagreed:
        verdict = 'disagree'
    elif agreed:
        verdict = 'agree'
    else:
        verdict = 'no_signal'
    return {
        'verdict': verdict,
        'agreed': agreed,
        'disagreed': disagreed,
        'skipped': list(gathered.get('skipped') or []),
    }


def identify_agreement_min() -> int:
    """How many independent sources must name the same title before a scan
    auto-imports it (H1d, pass-8 finding). ``IDENTIFY_AGREEMENT_MIN``: 1 is
    today's behaviour (a high-confidence IGDB match imports on its own); 2
    requires one catalogue (Steam / GOG / Moby / TGDB unique-exact) to agree,
    else the title goes to review. Never below 1."""
    import os

    raw = (os.environ.get('IDENTIFY_AGREEMENT_MIN') or '1').strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def agreement_count(catalog: dict | None, *, extra_signals: int = 0) -> int:
    """Sources naming the IGDB title: IGDB itself, each agreeing catalogue row,
    plus any extra signal the caller already has (a DAT / hash match)."""
    agreed = (catalog or {}).get('agreed') or []
    return 1 + len([row for row in agreed if isinstance(row, dict)]) + max(0, int(extra_signals or 0))


def agreement_satisfied(catalog: dict | None, *, extra_signals: int = 0, minimum: int | None = None) -> bool:
    """True when enough sources agree for an auto-import (see identify_agreement_min)."""
    need = identify_agreement_min() if minimum is None else max(1, int(minimum))
    return agreement_count(catalog, extra_signals=extra_signals) >= need


def apply_catalog_identity_to_game(game, rows: list[dict] | None) -> None:
    """Fill-only Steam / Moby identity from agreeing catalog rows. Never a download URL."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source = (row.get('source') or '').strip().lower()
        if source == 'steam' and not getattr(game, 'steam_app_id', None):
            app_id = row.get('steam_app_id') or row.get('id')
            try:
                app_id_int = int(app_id) if app_id is not None else None
            except (TypeError, ValueError):
                app_id_int = None
            if app_id_int:
                game.steam_app_id = app_id_int
                game.steam_url = f'https://store.steampowered.com/app/{app_id_int}/'
        elif source == 'mobygames':
            url = (row.get('url') or '').strip()
            if not url:
                continue
            lowered = url.lower()
            if any(token in lowered for token in ('download', 'install', 'magnet', 'torrent')):
                continue
            db.session.add(GameURL(
                game_uuid=game.uuid,
                url_type='mobygames',
                url=url,
            ))


def resolve_stage_d_store_candidate(
    *,
    cleaned_name: str,
    steam_app_id: int | None = None,
    steam_title: str | None = None,
    sources=None,
) -> dict | None:
    """
    Stage D confidence gate: App ID or exact (casefold) store title only.

    Ambiguous multi-hit exact titles → None (caller keeps proposal / Unmatched).
    Fuzzy / near matches are never auto-imported.
    Order: Steam App ID (verified details + title corroboration) → Steam exact
    title → GOG exact title → Epic exact title.

    ``sources`` limits which stores run (operator Integrations toggles). Default
    is all three when the settings module is available.

    Paren digits that fail Steam details (wrong namespace) do **not** stamp a
    bogus steam_app_id — fall through to exact-title search instead.
    """
    enabled = _enabled_stage_d_sources(sources)
    if not enabled:
        return None

    fallback_name = (cleaned_name or steam_title or '').strip()
    app_id = None
    if 'steam' in enabled and steam_app_id is not None:
        try:
            app_id = int(steam_app_id)
        except (TypeError, ValueError):
            app_id = None
    if 'steam' in enabled and app_id and app_id > 0:
        from oneirodex.utils.steam_lookup import fetch_steam_app_details

        details = fetch_steam_app_details(app_id)
        if details:
            store_name = (details.get('name') or '').strip()
            # Prefer folder cleaned name; steam_title hint is already store-sourced.
            corroborate_against = fallback_name or store_name
            if _stage_d_titles_corroborate(corroborate_against, store_name):
                return _candidate_from_steam_details(
                    details, steam_app_id=app_id, fallback_name=fallback_name,
                )
            # Live Steam hit but title mismatch → ignore App ID, try exact title.
        # Details miss or title mismatch: do not invent steam_app_id identity.

    queries: list[str] = []
    for q in (cleaned_name, steam_title):
        text = (q or '').strip()
        if not text:
            continue
        if _casefold_title(text) in {_casefold_title(x) for x in queries}:
            continue
        queries.append(text)

    if 'steam' in enabled:
        for query in queries:
            hits = search_steam_games(query, limit=10, include_software=True)
            exact = exact_title_hits(query, hits)
            if len(exact) == 1:
                return _candidate_from_steam_hit(exact[0], match_mode='exact_title')
            if len(exact) > 1:
                return None  # ambiguous — do not auto-import

    if 'gog' in enabled:
        for query in queries:
            hits = search_gog_games(query, limit=10)
            exact = exact_title_hits(query, hits)
            if len(exact) == 1:
                return _candidate_from_gog_hit(exact[0])
            if len(exact) > 1:
                return None

    if 'epic' in enabled:
        for query in queries:
            hits = search_epic_games(query, limit=10)
            exact = exact_title_hits(query, hits)
            if len(exact) == 1:
                return _candidate_from_epic_hit(exact[0])
            if len(exact) > 1:
                return None

    # Deliberately stops here. TheGamesDB / MobyGames are *not* part of the
    # Stage D auto-cascade — they run in Stage E as propose-only, because a
    # catalogue title match has no store identity to corroborate it and the
    # score gates for auto-import have not been proven. Adding them here would
    # auto-create games from a single fuzzy-adjacent title match.
    return None


def try_stage_d_store_identify(
    *,
    raw_label: str,
    cleaned_name: str,
    full_disk_path: str,
    library_uuid: str,
    steam_app_id: int | None = None,
    steam_title: str | None = None,
    size: int = 0,
    candidate: dict | None = None,
    sources=None,
) -> Game | None:
    """
    IGDB-miss Stage D entry: resolve exact/App-ID store hit and commit custom Game.

    Returns Game on success, None on miss/ambiguous (caller logs Unmatched).
    Flushes the session; caller is responsible for commit.

    Pass ``candidate`` when the caller already resolved a store hit (e.g. for an
    IGDB retry with the store's canonical title) so Stage D does not re-query.
    """
    if candidate is None:
        candidate = resolve_stage_d_store_candidate(
            cleaned_name=cleaned_name or raw_label,
            steam_app_id=steam_app_id,
            steam_title=steam_title,
            sources=sources,
        )
    if not candidate:
        return None
    game = upsert_stage_d_custom_game(
        candidate=candidate,
        full_disk_path=full_disk_path,
        library_uuid=library_uuid,
        size=size,
    )
    db.session.flush()
    return game


def resolve_stage_e_catalog_hints(
    *,
    cleaned_name: str,
    library_platform: str | None = None,
) -> dict:
    """
    Stage E propose-only after Stage D miss.

    - MobyGames: exact title (casefold) when API key configured; skip silently if unset.
    - TheGamesDB: exact title + platform filter for console leaves when key configured.
    - Never creates a Game (W21: Moby always propose-only; TGDB propose-only too).

    Returns a hint dict with ``candidates``, optional ``suggested_candidate_name``,
    and ``match_reason`` / ``identify_path`` for proposal sidecar enrichment.
    """
    query = (cleaned_name or '').strip()
    empty = {
        'candidates': [],
        'suggested_candidate_name': None,
        'match_reason': None,
        'identify_path': None,
        'skipped': [],
    }
    if not query:
        return empty

    platform_key = (library_platform or '').strip() or None
    is_pc = (not platform_key) or platform_key in NATIVE_PC_PLATFORMS
    is_console = bool(platform_key) and platform_key not in NATIVE_PC_PLATFORMS

    candidates: list[dict] = []
    skipped: list[str] = []
    preferred_name: str | None = None
    match_reason: str | None = None

    # --- MobyGames (PC preferred; also OK as propose hint on any leaf) ---
    try:
        from oneirodex.utils.providers.mobygames import get_mobygames_api_key

        moby_key = (get_mobygames_api_key() or '').strip()
    except Exception:
        moby_key = ''
    if not moby_key:
        skipped.append('mobygames_key_unset')
    else:
        try:
            moby_hits = search_mobygames_games(query, api_key=moby_key, limit=10)
        except Exception as err:
            print(f'⚠️ [Stage E] MobyGames search failed: {err}')
            moby_hits = []
        exact_moby = exact_title_hits(query, moby_hits)
        if len(exact_moby) == 1:
            row = _stage_e_candidate_row(exact_moby[0], match_mode='moby_exact')
            candidates.append(row)
            if preferred_name is None:
                preferred_name = (row.get('name') or '').strip() or None
                match_reason = 'stage_e_moby_exact'
        elif len(exact_moby) > 1:
            # Ambiguous exact titles — attach all for UI, no preferred auto name.
            for hit in exact_moby[:5]:
                candidates.append(
                    _stage_e_candidate_row(hit, match_mode='moby_exact_ambiguous'),
                )
            if match_reason is None:
                match_reason = 'stage_e_moby_ambiguous'

    # --- TheGamesDB (console leaves; platform-filtered exact) ---
    if is_console:
        try:
            from oneirodex.utils.providers.thegamesdb import get_thegamesdb_api_key

            tgdb_key = (get_thegamesdb_api_key() or '').strip()
        except Exception:
            tgdb_key = ''
        if not tgdb_key:
            skipped.append('thegamesdb_key_unset')
        else:
            try:
                tgdb_hits = search_thegamesdb_games(query, api_key=tgdb_key, limit=10)
            except Exception as err:
                print(f'⚠️ [Stage E] TheGamesDB search failed: {err}')
                tgdb_hits = []
            filtered = filter_tgdb_hits_for_platform(tgdb_hits, platform_key)
            exact_tgdb = exact_title_hits(query, filtered)
            if len(exact_tgdb) == 1:
                row = _stage_e_candidate_row(exact_tgdb[0], match_mode='tgdb_exact')
                candidates.append(row)
                preferred_name = (row.get('name') or '').strip() or preferred_name
                match_reason = 'stage_e_tgdb_exact'
            elif len(exact_tgdb) > 1:
                for hit in exact_tgdb[:5]:
                    candidates.append(
                        _stage_e_candidate_row(hit, match_mode='tgdb_exact_ambiguous'),
                    )
                if match_reason is None:
                    match_reason = 'stage_e_tgdb_ambiguous'
    elif is_pc:
        # PC leaves skip TGDB scan cascade (manual Identify chip remains).
        skipped.append('tgdb_pc_skipped')

    if not candidates:
        return {
            **empty,
            'skipped': skipped,
        }

    # Preferred name only when all non-ambiguous exact hits share one title.
    unique_exact_names = {
        _casefold_title(c.get('name'))
        for c in candidates
        if c.get('match_mode') in ('moby_exact', 'tgdb_exact')
        and (c.get('name') or '').strip()
    }
    if len(unique_exact_names) == 1:
        for c in candidates:
            if c.get('match_mode') in ('moby_exact', 'tgdb_exact'):
                preferred_name = (c.get('name') or '').strip() or preferred_name
                break
        if match_reason is None:
            match_reason = 'stage_e_exact'
    else:
        preferred_name = None
        if len(unique_exact_names) > 1:
            match_reason = 'stage_e_multi_source'

    return {
        'candidates': candidates,
        'suggested_candidate_name': preferred_name,
        'match_reason': match_reason,
        'identify_path': 'stage_e' if candidates else None,
        'skipped': skipped,
    }


def enrich_proposal_with_stage_e(
    proposal: dict,
    *,
    cleaned_name: str,
    library_platform: str | None = None,
) -> dict:
    """Attach Stage E propose-only catalog hints onto a match proposal.

    Does not create Games. Safe when API keys are unset (silent skip).
    """
    if not isinstance(proposal, dict):
        proposal = {'proposal': {}}
    body = proposal.setdefault('proposal', {})
    hints = resolve_stage_e_catalog_hints(
        cleaned_name=cleaned_name or body.get('cleaned_name') or '',
        library_platform=library_platform,
    )
    body['stage_e_candidates'] = hints.get('candidates') or []
    body['stage_e'] = {
        'match_reason': hints.get('match_reason'),
        'identify_path': hints.get('identify_path'),
        'skipped': list(hints.get('skipped') or []),
        'propose_only': True,
    }
    if hints.get('match_reason'):
        # Soft hint for UI filters — does not overwrite dupe match_reason codes
        # already on UnmatchedFolder; proposal-only unless caller denormalizes.
        body.setdefault('stage_e_match_reason', hints['match_reason'])
    # Prefer Stage E name when software path left no candidate name.
    stage_name = (hints.get('suggested_candidate_name') or '').strip() or None
    if stage_name:
        soft = body.get('software_candidates') or []
        has_soft_name = False
        if isinstance(soft, list) and soft and isinstance(soft[0], dict):
            has_soft_name = bool((soft[0].get('name') or '').strip())
        if not has_soft_name:
            body['suggested_candidate_name'] = stage_name
        if body.get('identify_path') in (None, 'unmatched', 'igdb'):
            body['identify_path'] = 'stage_e'
    return proposal


def mark_unmatched_as_kind(
    folder: UnmatchedFolder,
    *,
    item_kind: str,
    name: str | None = None,
    steam_app_id: int | None = None,
    summary: str | None = None,
) -> Game:
    """Create a kinded custom Game from an UnmatchedFolder and clear the row."""
    if not folder or not folder.folder_path:
        raise ValueError('Unmatched folder path required')
    if not folder.library_uuid:
        raise ValueError('Unmatched folder has no library_uuid')

    path = folder.folder_path
    parsed = parse_game_label(path)
    soft_search = (getattr(folder, 'search_name', None) or '').strip()
    display = (
        (name or '').strip()
        or soft_search
        or parsed.get('cleaned_name')
        or path.replace('\\', '/').rstrip('/').split('/')[-1]
    )
    kind = normalize_item_kind(item_kind)
    if steam_app_id is None and parsed.get('steam_app_id'):
        steam_app_id = parsed['steam_app_id']

    # Prefer Steam title when software app id known
    if steam_app_id and not name:
        from oneirodex.utils.steam_lookup import fetch_steam_app_details

        details = fetch_steam_app_details(int(steam_app_id))
        if details:
            display = details.get('name') or display
            if not summary:
                summary = details.get('short_description')
            kind = normalize_item_kind(
                suggest_item_kind(display, steam_type=details.get('steam_type'))
                if kind == DEFAULT_ITEM_KIND
                else kind
            )

    game = create_custom_kinded_game(
        name=display,
        full_disk_path=path,
        library_uuid=folder.library_uuid,
        item_kind=kind,
        steam_app_id=int(steam_app_id) if steam_app_id else None,
        summary=summary,
    )
    # A hand-picked Steam match used to bring over only the name (and a summary
    # when the fetch above happened to work): the game was created and nothing
    # mapped Steam's genres, developer, publisher, release date, modes, cover or
    # store specs onto it, because only the automatic Stage D path hydrated.
    # Steam is the one source with an App ID to ask for, so this is one fast call.
    if steam_app_id:
        from oneirodex.utils.software_identify_custom_game import hydrate_steam_for_game

        hydrate_steam_for_game(game, int(steam_app_id))
    db.session.delete(folder)
    return game
