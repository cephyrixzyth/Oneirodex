"""Find and fix games a scan matched to the wrong title.

A wrong match sticks: rescans skip any folder already in the library, so a
folder matched to the wrong product ("Star Trek Deep Space Nine Dominion Wars"
→ "Star Trek: Armada", "Star Wars Battle for Naboo" → "Star Wars") keeps that
title forever, and the real folder for that title is then marked a duplicate.

After each scan, :func:`audit_library_matches` re-checks games whose folder
name disagrees with their title:

1. **Disagreement** (local, no network): the folder's cleaned name scores below
   :data:`SUSPECT_SCORE` against the title (``match_scoring.score_candidate``).
   Games a person chose in manual identify (``match_locked``, or a local
   metadata file marked ``manually_verified``) are never touched, and a game
   re-checked recently (``match_checked_at``) is skipped.
2. **Re-identify**: the same sources a new folder gets (IGDB with the scan's
   confidence gate, then the store cascade including the Meta Quest store),
   via :func:`resolve_folder_identity`. No Game is created.
3. **Re-point** only when the new result is a different product *and* fits the
   folder clearly better (:func:`_better_fit`). The Game row is updated in
   place (title, catalogue id, taxonomy, links, images), so favourites, play
   state and downloads stay attached. Otherwise the match is kept and
   ``match_checked_at`` is stamped.
4. Folders that were marked duplicates of the corrected game are released and
   identified again in the same pass.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, UnmatchedFolder

logger = logging.getLogger(__name__)

# Folder vs title score below which a match is re-checked. A correct match can
# score lower ("GTA V" / "Grand Theft Auto V"); re-checking it costs a search
# and keeps it, because nothing fits the folder better.
SUSPECT_SCORE = 0.9
# A replacement must fit the folder at least this well...
REPLACEMENT_MIN_SCORE = 0.9
# ...and beat the current title by this much.
REPLACEMENT_MARGIN = 0.05
# Meta store matches whose title is the folder title minus words the store page
# backs up ("Golden Gloves Boxing VR" → "Golden Gloves") clear the bar on that
# evidence instead of the score.
_EVIDENCE_MATCH_MODES = frozenset({'meta_search_title_prefix', 'store_link'})
RECHECK_AFTER = timedelta(days=30)
MAX_REIDENTIFY_PER_SCAN = 25


def _now():
    return datetime.now(timezone.utc)


def _naive(value):
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def folder_label(game) -> str:
    return os.path.basename((getattr(game, 'full_disk_path', None) or '').rstrip('\\/'))


def folder_title_forms(label: str, *, peel_profile: str | None = None) -> dict:
    """Cleaned name, VR form and parse result for a folder label."""
    from oneirodex.utils.game_name_parse import parse_game_label

    parsed = parse_game_label(label, peel_profile=peel_profile)
    base = (parsed.get('cleaned_name') or '').strip()
    vr_form = (parsed.get('vr_title_form') or '').strip() if parsed.get('vr_title') else ''
    return {'parsed': parsed, 'base': base, 'vr_form': vr_form}


def folder_fit(forms: dict, title: str | None) -> float:
    """How well ``title`` fits the folder: best score over its cleaned forms."""
    from oneirodex.utils.match_scoring import score_candidate

    best = 0.0
    for name in (forms.get('vr_form'), forms.get('base')):
        if name and title:
            best = max(best, score_candidate(name, title))
    return best


def is_person_chosen(game, *, allowed_bases=None) -> bool:
    if getattr(game, 'match_locked', False):
        return True
    try:
        from oneirodex.utils.local_metadata import read_local_metadata

        meta = read_local_metadata(game.full_disk_path, allowed_bases=allowed_bases)
    except Exception:  # noqa: BLE001 — an unreadable sidecar is not a lock
        return False
    return bool(isinstance(meta, dict) and meta.get('manually_verified'))


def match_disagreement(game, *, peel_profile: str | None = None, now=None) -> dict | None:
    """Folder forms and score when ``game``'s folder disagrees with its title, else None."""
    if not getattr(game, 'full_disk_path', None) or not getattr(game, 'name', None):
        return None
    if getattr(game, 'match_locked', False):
        return None
    checked = _naive(getattr(game, 'match_checked_at', None))
    if checked is not None and _naive(now or _now()) - checked < RECHECK_AFTER:
        return None
    label = folder_label(game)
    if not label:
        return None
    forms = folder_title_forms(label, peel_profile=peel_profile)
    parsed = forms['parsed']
    if not forms['base'] or parsed.get('bare_franchise') or parsed.get('propose_only'):
        return None
    if parsed.get('is_bare_update_package'):
        return None
    score = folder_fit(forms, game.name)
    if score >= SUSPECT_SCORE:
        return None
    forms['score'] = score
    forms['label'] = label
    return forms


def resolve_folder_identity(game, library, forms: dict, *, match_policy: dict | None = None) -> dict | None:
    """What a fresh scan would match this folder to, without creating anything.

    Returns ``{'kind': 'igdb', 'payload': <IGDB game>}``, ``{'kind': 'store',
    'candidate': <Stage D candidate>}`` or None (no confident answer, or IGDB
    could not be asked).
    """
    from oneirodex.utils.clients.igdb import IgdbUnavailable
    from oneirodex.utils.gamenames import generate_goty_variants
    from oneirodex.utils.helpers.platforms import (
        candidate_on_pc_family,
        igdb_platform_id_for,
        is_pc_family_library,
    )
    from oneirodex.utils.match_scoring import select_best_match
    from oneirodex.utils.metadata_providers import stage_d_source_ids
    from oneirodex.utils.services.scan_identify import search_igdb_for_game
    from oneirodex.utils.software_identify import (
        igdb_retry_title_from_store,
        resolve_stage_d_store_candidate,
    )
    from oneirodex.utils.vr_catalog import candidate_is_vr

    policy = match_policy or {}
    parsed = forms['parsed']
    base = forms['base']
    vr_form = forms['vr_form']
    variants = generate_goty_variants(base, policy=policy)
    vr_only: set[str] = set()
    store_variants = None
    if vr_form:
        vr_forms = [vr_form]
        for extra in generate_goty_variants(vr_form, policy=policy):
            if extra not in vr_forms:
                vr_forms.append(extra)
        vr_only = {v for v in variants if v not in vr_forms}
        variants = vr_forms + [v for v in variants if v not in vr_forms]
        store_variants = list(vr_forms)

    platform_id = igdb_platform_id_for(library.platform)
    passes = [(platform_id, None)]
    if platform_id is not None and is_pc_family_library(library.platform):
        passes.append((None, candidate_on_pc_family))

    def _igdb_best(name, candidates):
        best, confidence = select_best_match(
            name,
            candidates,
            high_threshold=policy.get('match_high_threshold'),
            ambiguous_gap=policy.get('match_ambiguous_gap'),
        )
        return best if confidence == 'high' else None

    try:
        for pass_platform, keep in passes:
            for name in variants:
                candidates = search_igdb_for_game(name, pass_platform, limit=10, raise_on_error=True)
                if candidates and keep is not None:
                    candidates = [c for c in candidates if keep(c)]
                if candidates and name in vr_only:
                    candidates = [c for c in candidates if candidate_is_vr(c)]
                if not candidates:
                    continue
                best = _igdb_best(name, candidates)
                if best is not None:
                    return {'kind': 'igdb', 'payload': best}
    except IgdbUnavailable as exc:
        logger.warning('Match check skipped for %r: IGDB unavailable (%s)', game.name, exc)
        return None

    meta_app_id = parsed.get('meta_app_id')
    if not meta_app_id:
        try:
            from oneirodex.utils.meta_store import meta_app_id_from_folder

            meta_app_id = meta_app_id_from_folder(game.full_disk_path)
        except Exception:  # noqa: BLE001
            meta_app_id = None
    try:
        store = resolve_stage_d_store_candidate(
            cleaned_name=vr_form or base,
            search_variants=store_variants if store_variants is not None else variants,
            steam_app_id=parsed.get('steam_app_id'),
            sources=stage_d_source_ids(),
            meta_app_id=meta_app_id,
            meta_search=is_pc_family_library(library.platform),
        )
    except Exception as exc:  # noqa: BLE001 — a store miss must not break the scan
        logger.warning('Match check store lookup failed for %r: %s', game.name, exc)
        store = None
    if not store:
        return None

    retry_title = igdb_retry_title_from_store(store, variants)
    if retry_title:
        try:
            candidates = search_igdb_for_game(retry_title, platform_id, limit=10) or []
        except Exception:  # noqa: BLE001
            candidates = []
        if store.get('source') == 'meta_quest':
            candidates = [c for c in candidates if candidate_is_vr(c)]
        best = _igdb_best(retry_title, candidates) if candidates else None
        if best is not None:
            return {'kind': 'igdb', 'payload': best}
    return {'kind': 'store', 'candidate': store}


def _same_identity(game, result: dict) -> bool:
    if result['kind'] == 'igdb':
        return result['payload'].get('id') == game.igdb_id
    candidate = result['candidate']
    if candidate.get('steam_app_id') and candidate.get('steam_app_id') == getattr(game, 'steam_app_id', None):
        return True
    url = (candidate.get('url') or '').strip().lower()
    if url and any((row.url or '').strip().lower() == url for row in (game.urls or [])):
        return True
    from oneirodex.utils.software_identify import titles_identify_agree

    return titles_identify_agree(candidate.get('name'), game.name)


def _result_name(result: dict) -> str:
    if result['kind'] == 'igdb':
        return (result['payload'].get('name') or '').strip()
    return (result['candidate'].get('name') or '').strip()


def _better_fit(forms: dict, game, result: dict) -> bool:
    new_score = folder_fit(forms, _result_name(result))
    if result['kind'] == 'store' and result['candidate'].get('match_mode') in _EVIDENCE_MATCH_MODES:
        return new_score > forms['score']
    return new_score >= REPLACEMENT_MIN_SCORE and new_score >= forms['score'] + REPLACEMENT_MARGIN


def apply_igdb_identity(game, payload: dict) -> bool:
    """Re-point ``game`` at an IGDB product in place. False when another game holds it."""
    from oneirodex.utils.services.igdb_maps import category_mapping, status_mapping
    from oneirodex.utils.services.scan_identify import (
        attach_igdb_taxonomy_to_game,
        enumerate_companies,
    )
    from oneirodex.utils.software_identify_custom_game import clear_catalog_identity

    igdb_id = payload.get('id')
    if igdb_id is None:
        return False
    holder = db.session.execute(
        select(Game).where(Game.igdb_id == igdb_id, Game.id != game.id)
    ).scalars().first()
    if holder is not None:
        logger.info(
            'Match check: %r fits %r better, but %r already holds IGDB %s',
            folder_label(game), payload.get('name'), holder.full_disk_path, igdb_id,
        )
        return False
    slug = payload.get('slug')
    if slug and db.session.execute(
        select(Game.id).where(Game.slug == slug, Game.id != game.id)
    ).first():
        slug = None

    clear_catalog_identity(game)
    released = payload.get('first_release_date')
    game.igdb_id = igdb_id
    game.slug = slug
    game.name = payload['name']
    game.summary = payload.get('summary')
    game.storyline = payload.get('storyline')
    game.url = payload.get('url')
    game.first_release_date = datetime.fromtimestamp(released, timezone.utc) if released else None
    game.aggregated_rating = payload.get('aggregated_rating')
    game.aggregated_rating_count = payload.get('aggregated_rating_count')
    game.rating = payload.get('rating')
    game.rating_count = payload.get('rating_count')
    game.total_rating = payload.get('total_rating')
    game.total_rating_count = payload.get('total_rating_count')
    game.status = status_mapping.get(payload.get('status'))
    game.category = category_mapping.get(payload.get('category'))
    game.steam_app_id = None
    game.steam_url = ''
    game.cover = None
    game.video_urls = ','.join(
        f"https://www.youtube.com/embed/{video['video_id']}"
        for video in payload.get('videos') or []
        if isinstance(video, dict) and video.get('video_id')
    )
    db.session.flush()
    attach_igdb_taxonomy_to_game(game, payload)
    if payload.get('involved_companies'):
        try:
            enumerate_companies(game, igdb_id, payload['involved_companies'])
        except Exception as exc:  # noqa: BLE001 — companies are optional detail
            logger.warning('Match check: companies for %r not loaded: %s', game.name, exc)
    return True


def _release_duplicates_of(game_uuid: str, library_uuid: str) -> list[str]:
    """Drop Duplicate rows that pointed at a game we just re-matched; return their paths."""
    rows = db.session.execute(
        select(UnmatchedFolder).where(
            UnmatchedFolder.matched_game_uuid == game_uuid,
            UnmatchedFolder.library_uuid == library_uuid,
            UnmatchedFolder.status == 'Duplicate',
            UnmatchedFolder.review_decision.is_(None),
            UnmatchedFolder.bad_match_reason.is_(None),
        )
    ).scalars().all()
    paths = [row.folder_path for row in rows if row.folder_path]
    if rows:
        db.session.execute(
            delete(UnmatchedFolder).where(UnmatchedFolder.id.in_([row.id for row in rows]))
        )
    return paths


def recheck_game_match(game, library, *, match_policy=None, allowed_bases=None, now=None) -> dict | None:
    """Re-check one game. Returns ``{'old', 'new', 'released'}`` when it was re-matched."""
    forms = match_disagreement(game, peel_profile=(match_policy or {}).get('peel_profile'), now=now)
    if forms is None:
        return None
    if is_person_chosen(game, allowed_bases=allowed_bases):
        return None
    result = resolve_folder_identity(game, library, forms, match_policy=match_policy)
    stamp = now or _now()
    if result is None or _same_identity(game, result) or not _better_fit(forms, game, result):
        game.match_checked_at = _naive(stamp)
        db.session.commit()
        return None

    old_name = game.name
    old_uuid = game.uuid
    try:
        if result['kind'] == 'igdb':
            if not apply_igdb_identity(game, result['payload']):
                game.match_checked_at = _naive(stamp)
                db.session.commit()
                return None
        else:
            from oneirodex.utils.software_identify import upsert_stage_d_custom_game

            upsert_stage_d_custom_game(
                candidate=result['candidate'],
                full_disk_path=game.full_disk_path,
                library_uuid=game.library_uuid,
                size=game.size or 0,
                replace_game=game,
            )
        game.date_identified = _naive(stamp)
        game.match_checked_at = _naive(stamp)
        released = _release_duplicates_of(old_uuid, game.library_uuid)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Match check could not re-match %r', old_name)
        return None

    from oneirodex.utils.event_logging import log_system_event

    log_system_event(
        f"Scan re-matched '{folder_label(game)}': '{old_name}' → '{game.name}'",
        event_type='game',
        event_level='information',
    )
    return {'old': old_name, 'new': game.name, 'game_uuid': game.uuid, 'released': released, 'result': result}


def audit_library_matches(
    games,
    library,
    *,
    match_policy: dict | None = None,
    allowed_bases=None,
    on_rematched=None,
    limit: int = MAX_REIDENTIFY_PER_SCAN,
) -> list[dict]:
    """Re-check up to ``limit`` disagreeing games of one PC-family library.

    ``on_rematched(change)`` runs after each re-match (the scan uses it to queue
    images and to identify the released duplicate folders).
    """
    from oneirodex.utils.helpers.platforms import is_pc_family_library

    if library is None or not is_pc_family_library(library.platform):
        return []
    changes: list[dict] = []
    checked = 0
    now = _now()
    for game in games:
        if checked >= limit:
            break
        if match_disagreement(game, peel_profile=(match_policy or {}).get('peel_profile'), now=now) is None:
            continue
        checked += 1
        try:
            change = recheck_game_match(
                game, library, match_policy=match_policy, allowed_bases=allowed_bases, now=now,
            )
        except Exception:  # noqa: BLE001 — one bad folder must not stop the pass
            db.session.rollback()
            logger.exception('Match check failed for %r', getattr(game, 'name', '?'))
            continue
        if change is None:
            continue
        changes.append(change)
        if on_rematched is not None:
            try:
                on_rematched(change)
            except Exception:  # noqa: BLE001
                logger.exception('Follow-up after re-matching %r failed', change.get('new'))
    if changes:
        logger.info('Match check re-matched %d game(s) in %s', len(changes), library.name)
    return changes


__all__ = [
    'SUSPECT_SCORE',
    'apply_igdb_identity',
    'audit_library_matches',
    'match_disagreement',
    'recheck_game_match',
    'resolve_folder_identity',
]
