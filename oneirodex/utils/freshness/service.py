"""Orchestrate local + store freshness check and persist on Game."""

from __future__ import annotations

from datetime import datetime, timezone

from oneirodex.utils.freshness.compare import compare_freshness
from oneirodex.utils.freshness.epic import fetch_epic_remote
from oneirodex.utils.freshness.gog import fetch_gog_remote
from oneirodex.utils.freshness.ids import (
    resolve_epic_identity,
    resolve_gog_identity,
    resolve_steam_app_id,
)
from oneirodex.utils.freshness.local import detect_local_facts
from oneirodex.utils.freshness.steam import fetch_steam_remote


def check_game_freshness(game, *, include_gog=True, include_epic=True, app=None) -> dict:
    """Run sensors + remotes and return comparison payload (does not commit)."""
    local = detect_local_facts(game, app=app)
    remotes = []

    steam_id = resolve_steam_app_id(game)
    if steam_id:
        remotes.append(fetch_steam_remote(steam_id))
    else:
        remotes.append({
            'store': 'steam',
            'ok': False,
            'error': 'missing_app_id',
            'version': None,
            'dlc_count': None,
        })

    if include_gog:
        gog_id = resolve_gog_identity(game)
        if gog_id:
            remotes.append(fetch_gog_remote(**gog_id))
        else:
            remotes.append({
                'store': 'gog',
                'ok': False,
                'error': 'missing_gog_identity',
                'version': None,
            })

    if include_epic:
        epic_id = resolve_epic_identity(game)
        if epic_id:
            remotes.append(fetch_epic_remote(**epic_id))
        else:
            remotes.append({
                'store': 'epic',
                'ok': False,
                'error': 'missing_epic_identity',
                'version': None,
                'note': 'No Epic URL on this game.',
            })

    return compare_freshness(local, remotes)


def apply_freshness_to_game(game, payload: dict) -> dict:
    """Write freshness fields onto the Game instance (caller commits)."""
    now = datetime.now(timezone.utc)
    game.local_version = payload.get('local_version')
    game.remote_version_summary = payload.get('remote_version_summary')
    game.freshness_status = payload.get('status')
    game.freshness_confidence = payload.get('confidence')
    game.freshness_checked_at = now
    game.freshness_payload = payload

    steam = next(
        (r for r in (payload.get('remotes') or []) if r.get('store') == 'steam' and r.get('app_id')),
        None,
    )
    if steam and steam.get('app_id'):
        game.steam_app_id = int(steam['app_id'])
    else:
        resolved = resolve_steam_app_id(game)
        if resolved:
            game.steam_app_id = resolved

    return freshness_public_view(game)


def check_and_store_freshness(game, *, commit=False, db_session=None, app=None) -> dict:
    payload = check_game_freshness(game, app=app)
    public = apply_freshness_to_game(game, payload)
    if commit and db_session is not None:
        db_session.commit()
    return public


def freshness_public_view(game) -> dict:
    """Safe JSON for APIs / browse badges."""
    payload = getattr(game, 'freshness_payload', None) or {}
    return {
        'status': getattr(game, 'freshness_status', None),
        'confidence': getattr(game, 'freshness_confidence', None),
        'checked_at': (
            game.freshness_checked_at.isoformat()
            if getattr(game, 'freshness_checked_at', None)
            else None
        ),
        'local_version': getattr(game, 'local_version', None),
        'remote_version_summary': getattr(game, 'remote_version_summary', None),
        'steam_app_id': getattr(game, 'steam_app_id', None),
        'dlc': payload.get('dlc'),
        'reasons': payload.get('reasons'),
        'remotes': payload.get('remotes'),
        'local': payload.get('local'),
    }


# --- FEAT-D1: freshness as part of a scan ------------------------------------
# Freshness has always been on-demand; a scan never asked. That left a fresh
# library with no version/DLC information until someone pressed the button on
# each title one at a time.
#
# It runs as a capped pass *after* the scan rather than inline per game:
# every check is one or more store HTTP calls, so doing it inside the scan loop
# would slow the scan badly and hammer the stores on a large import.

DEFAULT_SCAN_FRESHNESS_LIMIT = 50


def scan_freshness_enabled(settings=None) -> bool:
    """Opt-in. A scan that silently starts calling stores is a surprise."""
    if settings is None:
        try:
            from flask import current_app

            return bool(current_app.config.get('SCAN_CHECK_FRESHNESS', False))
        except (ImportError, RuntimeError):
            return False
    if isinstance(settings, dict):
        return bool(settings.get('scan_check_freshness'))
    return bool(getattr(settings, 'scan_check_freshness', False))


def check_library_freshness(
    library_uuid: str,
    *,
    limit: int = DEFAULT_SCAN_FRESHNESS_LIMIT,
    only_missing: bool = True,
    app=None,
) -> dict:
    """Check version/updates/DLC across a library, newest titles first.

    ``only_missing`` skips titles already carrying a freshness verdict, so a
    re-scan spends its budget on what it does not yet know rather than
    re-asking the store about everything.

    Per-title failures are counted, never raised — a store being down must not
    fail a scan that already succeeded.
    """
    from sqlalchemy import select

    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import Game

    query = select(Game).filter(Game.library_uuid == library_uuid)
    if only_missing:
        query = query.filter(Game.freshness_status.is_(None))
    query = query.order_by(Game.date_created.desc()).limit(max(1, int(limit)))

    games = db.session.execute(query).scalars().all()

    checked, behind, failed = 0, 0, 0
    for game in games:
        try:
            public = check_and_store_freshness(game, app=app)
            checked += 1
            if (public or {}).get('status') == 'behind':
                behind += 1
        except Exception:  # noqa: BLE001 — a store outage is not a scan failure
            failed += 1

    if checked:
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

    return {
        'library_uuid': library_uuid,
        'considered': len(games),
        'checked': checked,
        'behind': behind,
        'failed': failed,
        'limit': limit,
    }
