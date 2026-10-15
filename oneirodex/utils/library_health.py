"""Library health scoring — per-game detail + lightweight Ops pulse.

Per-game ``score_game`` may filesystem-stat paths (detail endpoint only).
Ops / Dashboard pulse uses SQL counts only — no re-scan, no path.exists.
Scan/identify persist ``Game.path_status`` so broken paths count without
live exists on every Ops poll.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Image, UnmatchedFolder
from oneirodex.utils.software_identify import CUSTOM_IGDB_BASE

# Persisted on Game.path_status by scan/identify (nullable = never checked).
PATH_STATUS_OK = 'ok'
PATH_STATUS_MISSING = 'missing'
PATH_STATUS_EMPTY = 'empty'

# Aggregate Ops pulse — weights sum to 100 (deterministic fixture → known score).
HEALTH_FACTOR_SPECS = (
    {'id': 'missing_cover', 'label': 'Missing cover', 'weight': 25},
    {
        'id': 'missing_path',
        'label': 'Missing path (empty or scan-flagged)',
        'weight': 20,
    },
    {
        'id': 'no_igdb',
        'label': 'No IGDB / custom-range id',
        'weight': 20,
    },
    {
        'id': 'stale_freshness',
        'label': 'Stale freshness (OUT/~)',
        'weight': 15,
    },
    {'id': 'unmatched', 'label': 'Unmatched folders', 'weight': 20},
)

_GRADE_GOOD = 80
_GRADE_FAIR = 50

_STALE_FRESHNESS = ('behind', 'heuristic_behind')


def refresh_game_path_status(game: Game) -> str:
    """Stat ``full_disk_path`` once and persist ``path_status`` (scan-time only).

    Returns the new status. Does not commit — caller owns the transaction.
    """
    path = (getattr(game, 'full_disk_path', None) or '').strip()
    if not path:
        game.path_status = PATH_STATUS_EMPTY
        return PATH_STATUS_EMPTY
    if os.path.exists(path):
        game.path_status = PATH_STATUS_OK
        return PATH_STATUS_OK
    game.path_status = PATH_STATUS_MISSING
    return PATH_STATUS_MISSING


def mark_game_path_ok(game: Game) -> None:
    """Caller verified the path exists (identify / link / create)."""
    path = (getattr(game, 'full_disk_path', None) or '').strip()
    game.path_status = PATH_STATUS_OK if path else PATH_STATUS_EMPTY


def path_health_fields(game) -> dict:
    """Browse / favorites / discover card fields for disk presence honesty.

    ``path_status`` is the persisted scan signal (``ok``|``missing``|``empty``|null).
    ``path_missing`` is True only when status is explicitly ``missing`` (files gone,
    remove-missing off) — UI badge hook for Library tiles.
    """
    status = getattr(game, 'path_status', None)
    if status is not None:
        status = str(status).strip().lower() or None
        if status not in (PATH_STATUS_OK, PATH_STATUS_MISSING, PATH_STATUS_EMPTY):
            status = None
    return {
        'path_status': status,
        'path_missing': status == PATH_STATUS_MISSING,
    }


def _normalize_disk_path(path: str | None) -> str:
    if not path:
        return ''
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def clear_restored_missing_path_status(
    paths,
    *,
    library_uuid: str | None = None,
) -> int:
    """Clear ``path_status`` missing→ok when restored folders match library games.

    Used by library watch (add/restore) and scan when an existing path is seen
    again — no separate full-library rescan required. Re-stats each candidate
    via ``refresh_game_path_status``. Does not commit. Returns games updated.

    Lean path: SQL ``IN`` on exact ``full_disk_path`` first (watch/scan callers
    pass exact paths). Falls back to a bounded missing-row walk only for
    restored paths that did not match exactly (normcase / abspath variants).
    """
    raw_paths = [(p or '').strip() for p in (paths or []) if (p or '').strip()]
    if not raw_paths:
        return 0
    restored_norm = {_normalize_disk_path(p) for p in raw_paths}
    restored_raw = set(raw_paths)

    # Fast path — exact path match (common for watch/scan events).
    exact_q = select(Game).where(
        Game.path_status == PATH_STATUS_MISSING,
        Game.full_disk_path.in_(list(restored_raw)),
    )
    if library_uuid:
        exact_q = exact_q.where(Game.library_uuid == library_uuid)
    candidates = list(db.session.execute(exact_q).scalars().all())
    matched_raw = {
        (getattr(g, 'full_disk_path', None) or '').strip()
        for g in candidates
    }
    unmatched_restored = restored_raw - matched_raw

    # Fallback only when some restored paths still need normcase/abspath match.
    if unmatched_restored:
        fallback_q = select(Game).where(Game.path_status == PATH_STATUS_MISSING)
        if library_uuid:
            fallback_q = fallback_q.where(Game.library_uuid == library_uuid)
        for game in db.session.execute(fallback_q).scalars().all():
            path = (getattr(game, 'full_disk_path', None) or '').strip()
            if not path or path in matched_raw:
                continue
            if path in unmatched_restored or _normalize_disk_path(path) in restored_norm:
                candidates.append(game)

    updated = 0
    seen_uuids: set[str] = set()
    for game in candidates:
        uid = getattr(game, 'uuid', None)
        if uid and uid in seen_uuids:
            continue
        if uid:
            seen_uuids.add(uid)
        path = (getattr(game, 'full_disk_path', None) or '').strip()
        if not path:
            continue
        if path not in restored_raw and _normalize_disk_path(path) not in restored_norm:
            continue
        if refresh_game_path_status(game) == PATH_STATUS_OK:
            updated += 1
    return updated


def score_game(game: Game) -> dict:
    """Return a 0–100 health score and issue list for one game."""
    issues = []
    deductions = 0

    path = getattr(game, 'full_disk_path', None) or ''
    path_status = getattr(game, 'path_status', None)
    if not path or path_status == PATH_STATUS_EMPTY:
        issues.append({'code': 'missing_path', 'severity': 25})
        deductions += 25
    elif path_status == PATH_STATUS_MISSING:
        # Prefer tracked scan signal — no live exists on pulse; detail may still
        # fall through to exists when status is unknown.
        issues.append({'code': 'broken_path', 'severity': 30})
        deductions += 30
    elif not os.path.exists(path):
        issues.append({'code': 'broken_path', 'severity': 30})
        deductions += 30

    has_cover = False
    if getattr(game, 'cover', None):
        has_cover = True
    else:
        cover = db.session.execute(
            select(Image).filter_by(game_uuid=game.uuid, image_type='cover').limit(1)
        ).scalars().first()
        has_cover = cover is not None
    if not has_cover:
        issues.append({'code': 'missing_cover', 'severity': 15})
        deductions += 15

    igdb_id = getattr(game, 'igdb_id', None)
    if not igdb_id:
        issues.append({'code': 'missing_igdb', 'severity': 10})
        deductions += 10

    if not (getattr(game, 'summary', None) or '').strip():
        issues.append({'code': 'missing_summary', 'severity': 5})
        deductions += 5

    freshness = getattr(game, 'freshness_status', None)
    if freshness in _STALE_FRESHNESS:
        issues.append({'code': 'stale_freshness', 'severity': 10, 'status': freshness})
        deductions += 10
    elif not getattr(game, 'freshness_checked_at', None):
        issues.append({'code': 'never_freshness_checked', 'severity': 5})
        deductions += 5

    score = max(0, 100 - deductions)
    grade = (
        'A' if score >= 90 else
        'B' if score >= 75 else
        'C' if score >= 60 else
        'D' if score >= 40 else
        'F'
    )
    return {
        'uuid': game.uuid,
        'name': game.name,
        'score': score,
        'grade': grade,
        'issues': issues,
    }


def summarize_library_health(limit: int = 200, library_uuid: str | None = None) -> dict:
    query = select(Game).order_by(Game.name.asc())
    if library_uuid:
        query = query.filter(Game.library_uuid == library_uuid)
    games = db.session.execute(query.limit(limit)).scalars().all()

    scored = [score_game(g) for g in games]
    if not scored:
        return {
            'count': 0,
            'average_score': 100,
            'grade_counts': {},
            'top_issues': [],
            'worst': [],
            'checked_at': datetime.now(timezone.utc).isoformat(),
        }

    avg = sum(s['score'] for s in scored) / len(scored)
    grade_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for s in scored:
        grade_counts[s['grade']] = grade_counts.get(s['grade'], 0) + 1
        for issue in s['issues']:
            code = issue['code']
            issue_counts[code] = issue_counts.get(code, 0) + 1

    worst = sorted(scored, key=lambda s: s['score'])[:25]
    top_issues = sorted(
        ({'code': k, 'count': v} for k, v in issue_counts.items()),
        key=lambda x: -x['count'],
    )
    return {
        'count': len(scored),
        'average_score': round(avg, 1),
        'grade_counts': grade_counts,
        'top_issues': top_issues,
        'worst': worst,
        'library_uuid': library_uuid,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


def grade_from_score(score: int | None) -> str | None:
    """Map 0–100 score → good|fair|poor; None when score withheld."""
    if score is None:
        return None
    if score >= _GRADE_GOOD:
        return 'good'
    if score >= _GRADE_FAIR:
        return 'fair'
    return 'poor'


def score_library_health_from_counts(
    *,
    games: int,
    missing_cover: int = 0,
    missing_path: int = 0,
    no_igdb: int = 0,
    stale_freshness: int = 0,
    unmatched: int = 0,
) -> dict:
    """Deterministic aggregate health from fixture-friendly counts (no I/O).

    Game-relative factors deduct ``weight * (count / games)``.
    Unmatched deducts ``weight * unmatched / (games + unmatched)``.
    When ``games == 0``, score/grade are withheld (``thin=True``) — empty
    libraries must not look perfectly healthy.
    """
    games = max(0, int(games or 0))
    counts = {
        'missing_cover': max(0, int(missing_cover or 0)),
        'missing_path': max(0, int(missing_path or 0)),
        'no_igdb': max(0, int(no_igdb or 0)),
        'stale_freshness': max(0, int(stale_freshness or 0)),
        'unmatched': max(0, int(unmatched or 0)),
    }

    factors = []
    deduction = 0.0
    for spec in HEALTH_FACTOR_SPECS:
        fid = spec['id']
        weight = spec['weight']
        count = counts[fid]
        if fid == 'unmatched':
            denom = games + counts['unmatched']
            ratio = (count / denom) if denom > 0 else 0.0
        elif games > 0:
            ratio = min(1.0, count / games)
        else:
            ratio = 0.0
        part = weight * ratio
        deduction += part
        factors.append({
            'id': fid,
            'label': spec['label'],
            'count': count,
            'weight': weight,
            'ratio': round(ratio, 4),
            'deduction': round(part, 2),
        })

    thin = games == 0
    if thin:
        score = None
        note = (
            'No games cataloged — score withheld (unmatched may still show).'
            if counts['unmatched']
            else 'No games cataloged — score withheld.'
        )
    else:
        score = max(0, min(100, round(100 - deduction)))
        note = None

    return {
        'score': score,
        'grade': grade_from_score(score),
        'factors': factors,
        'games': games,
        'thin': thin,
        'note': note,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


def collect_library_health_counts() -> dict:
    """Cheap SQL counts for the Ops pulse (no filesystem stats)."""
    games = int(db.session.execute(select(func.count(Game.id))).scalar() or 0)

    has_downloaded_cover = (
        select(Image.id)
        .where(
            Image.game_uuid == Game.uuid,
            Image.image_type == 'cover',
            Image.is_downloaded.is_(True),
        )
        .correlate(Game)
        .exists()
    )
    # Missing cover: no Game.cover string and no downloaded cover Image.
    missing_cover = int(
        db.session.execute(
            select(func.count(Game.id)).where(
                or_(Game.cover.is_(None), Game.cover == ''),
                ~has_downloaded_cover,
            )
        ).scalar()
        or 0
    )

    # Empty path OR scan-flagged missing — no path.exists on Ops poll.
    missing_path = int(
        db.session.execute(
            select(func.count(Game.id)).where(
                or_(
                    Game.full_disk_path.is_(None),
                    Game.full_disk_path == '',
                    Game.path_status == PATH_STATUS_EMPTY,
                    Game.path_status == PATH_STATUS_MISSING,
                )
            )
        ).scalar()
        or 0
    )

    no_igdb = int(
        db.session.execute(
            select(func.count(Game.id)).where(
                or_(
                    Game.igdb_id.is_(None),
                    Game.igdb_id >= CUSTOM_IGDB_BASE,
                )
            )
        ).scalar()
        or 0
    )

    stale_freshness = int(
        db.session.execute(
            select(func.count(Game.id)).where(
                Game.freshness_status.in_(_STALE_FRESHNESS)
            )
        ).scalar()
        or 0
    )

    unmatched = int(
        db.session.execute(select(func.count(UnmatchedFolder.id))).scalar() or 0
    )

    return {
        'games': games,
        'missing_cover': missing_cover,
        'missing_path': missing_path,
        'no_igdb': no_igdb,
        'stale_freshness': stale_freshness,
        'unmatched': unmatched,
    }


def build_library_health_pulse() -> dict:
    """Lightweight library.health payload for Ops / Dashboard (~15s poll-safe)."""
    counts = collect_library_health_counts()
    return score_library_health_from_counts(**counts)
