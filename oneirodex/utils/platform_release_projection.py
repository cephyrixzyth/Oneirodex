"""Shared release-size projection for admin library inventories."""
from __future__ import annotations

from oneirodex.utils.platform_release_estimates import PLATFORM_RELEASE_ESTIMATES


def platform_release_totals(session, igdb_release_model, reference_set_model) -> dict[str, int]:
    """Prefer reference data, then fill missing platforms with built-in estimates."""
    from sqlalchemy import func, select

    totals: dict[str, int] = {}
    igdb_rows = session.execute(
        select(
            igdb_release_model.library_platform,
            func.count(func.distinct(igdb_release_model.igdb_game_id)),
        ).group_by(igdb_release_model.library_platform)
    ).all()
    for key, count in igdb_rows:
        count = int(count or 0)
        if key and count > 0:
            totals[str(key)] = count
    dat_rows = session.execute(
        select(
            reference_set_model.library_platform,
            func.max(reference_set_model.entry_count),
        ).group_by(reference_set_model.library_platform)
    ).all()
    for key, count in dat_rows:
        count = int(count or 0)
        if key and count > 0:
            totals[str(key)] = count
    for key, count in PLATFORM_RELEASE_ESTIMATES.items():
        if key not in totals and count > 0:
            totals[key] = int(count)
    return totals
