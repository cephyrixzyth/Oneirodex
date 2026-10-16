"""Framework-neutral social response projections shared by Flask and FastAPI."""
from __future__ import annotations

from oneirodex.utils.role_catalog import normalize_role


def community_settings() -> dict:
    from sqlalchemy import select

    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import GlobalSettings

    row = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()
    url = (getattr(row, 'community_chat_url', None) or '').strip() if row else ''
    label = (getattr(row, 'community_chat_label', None) or '').strip() if row else ''
    return {
        'community_chat_url': url or None,
        'community_chat_label': label or ('Open community' if url else None),
    }


def user_public(user, *, viewer=None) -> dict:
    from oneirodex.utils.presence import presence_for_user

    presence = presence_for_user(user.id, viewer=viewer)
    return {
        'id': user.id,
        'name': user.name,
        'role': normalize_role(getattr(user, 'role', None) or 'user'),
        'presence': {
            'status': presence['status'],
            'game_uuid': presence.get('game_uuid'),
            'game_name': presence.get('game_name'),
        },
    }
