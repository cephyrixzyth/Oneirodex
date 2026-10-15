"""Framework-independent projections for update and DLC freshness payloads."""
from __future__ import annotations

import os


def _basename_label(path: str, fallback: str) -> str:
    name = os.path.basename(path.rstrip('\\/')) if path else ''
    return name or fallback


def _pack_row(kind: str, game_uuid: str, version_uuid: str, label: str) -> dict:
    return {
        'kind': kind,
        'uuid': version_uuid,
        'label': label,
        'download_url': f'/download_other/{kind}/{game_uuid}/{version_uuid}',
    }


def batch_local_packs(session, game_update_model, game_extra_model, game_uuids: list[str]) -> dict[str, list[dict]]:
    """Load update/extra packs for many games in two queries."""
    from sqlalchemy import select

    packs_by_game: dict[str, list[dict]] = {uuid: [] for uuid in game_uuids}
    if not game_uuids:
        return packs_by_game

    updates = session.execute(
        select(game_update_model)
        .filter(game_update_model.game_uuid.in_(game_uuids))
        .order_by(game_update_model.created_at.desc())
    ).scalars().all()
    for update in updates:
        packs_by_game.setdefault(update.game_uuid, []).append(
            _pack_row(
                'update', update.game_uuid, update.uuid,
                f'Update: {_basename_label(update.file_path, update.uuid[:8])}',
            )
        )

    extras = session.execute(
        select(game_extra_model)
        .filter(game_extra_model.game_uuid.in_(game_uuids))
        .order_by(game_extra_model.created_at.desc())
    ).scalars().all()
    for extra in extras:
        packs_by_game.setdefault(extra.game_uuid, []).append(
            _pack_row(
                'extra', extra.game_uuid, extra.uuid,
                f'Extra: {_basename_label(extra.file_path, extra.uuid[:8])}',
            )
        )
    return packs_by_game


def dlc_summary(game) -> dict | None:
    payload = getattr(game, 'freshness_payload', None) or {}
    dlc = payload.get('dlc')
    if isinstance(dlc, dict) and dlc:
        missing = dlc.get('missing_dlc_count_estimate')
        if missing is None:
            missing = dlc.get('missing_count')
        store_count = dlc.get('store_dlc_count')
        if store_count is None:
            store_count = dlc.get('store_count')
        return {
            'store_count': store_count,
            'local_hint': dlc.get('local_dlc_count_hint') or dlc.get('local_hint'),
            'missing_count': missing,
            'store': dlc.get('store'),
        }
    remotes = payload.get('remotes') if isinstance(payload, dict) else None
    if isinstance(remotes, list):
        for remote in remotes:
            if isinstance(remote, dict) and remote.get('dlc_count') is not None:
                return {
                    'store_count': remote.get('dlc_count'),
                    'local_hint': (payload.get('local') or {}).get('dlc_count_hint'),
                    'missing_count': None,
                    'store': remote.get('store'),
                }
    return None
