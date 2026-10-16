"""Game details section layout (order + visibility)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings

DEFAULT_SECTIONS: list[str] = [
    'hero',
    'actions',
    'summary',
    'metadata',
    'screenshots',
    'videos',
    'downloads',
    'updates',
    'extras',
    'playtime',
    'related',
]


def _default_layout() -> dict[str, Any]:
    return {
        'sections': [{'id': sid, 'visible': True} for sid in DEFAULT_SECTIONS],
    }


def merge_with_defaults(raw: dict | None) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in (raw or {}).get('sections') or []:
        if not isinstance(item, dict):
            continue
        sid = item.get('id')
        if sid in DEFAULT_SECTIONS and sid not in seen:
            sections.append({'id': sid, 'visible': bool(item.get('visible', True))})
            seen.add(sid)
    for sid in DEFAULT_SECTIONS:
        if sid not in seen:
            sections.append({'id': sid, 'visible': True})
    return {'sections': sections}


def validate_layout_payload(payload: dict | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError('Layout payload must be an object')
    raw_sections = payload.get('sections')
    if raw_sections is None or raw_sections == []:
        return _default_layout()
    if not isinstance(raw_sections, list):
        raise ValueError('sections must be a list')
    for item in raw_sections:
        if not isinstance(item, dict) or item.get('id') not in DEFAULT_SECTIONS:
            raise ValueError(f"Unknown or invalid section id: {item!r}")
    return merge_with_defaults(payload)


def get_detail_layout() -> dict[str, Any]:
    row = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    raw = getattr(row, 'detail_layout', None) if row else None
    return merge_with_defaults(raw if isinstance(raw, dict) else None)


def save_detail_layout(payload: dict | None) -> dict[str, Any]:
    validated = validate_layout_payload(payload)
    row = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if not row:
        row = GlobalSettings()
        db.session.add(row)
    row.detail_layout = validated
    db.session.commit()
    return validated


def get_user_detail_layout(user_id: int | None) -> dict[str, Any]:
    """The layout this member should see.

    Resolution is member → install → defaults, and the distinction that matters
    is between "no preference" and "an empty one". A member who has never opened
    the editor stores NULL and keeps tracking whatever the admin sets; a member
    who has arranged their own page keeps it even when the admin changes theirs.
    Treating NULL as an empty layout would silently freeze everyone at whatever
    the install default happened to be on their first visit.
    """
    if user_id is None:
        return get_detail_layout()

    from oneirodex.models import UserPreference

    row = db.session.execute(
        select(UserPreference).filter(UserPreference.user_id == user_id),
    ).scalars().first()
    raw = getattr(row, 'detail_layout', None) if row else None
    if isinstance(raw, dict) and raw.get('sections'):
        return merge_with_defaults(raw)
    return get_detail_layout()


def user_has_detail_override(user_id: int | None) -> bool:
    """Whether this member has an arrangement of their own.

    Not derivable from the layout itself: a member's arrangement can happen to
    match the install's exactly, and the editor still needs to know whether
    "Reset to default" would do anything.
    """
    if user_id is None:
        return False

    from oneirodex.models import UserPreference

    row = db.session.execute(
        select(UserPreference).filter(UserPreference.user_id == user_id),
    ).scalars().first()
    raw = getattr(row, 'detail_layout', None) if row else None
    return isinstance(raw, dict) and bool(raw.get('sections'))


def save_user_detail_layout(user_id: int, payload: dict | None) -> dict[str, Any]:
    """Persist one member's arrangement. Callers own nothing else."""
    from oneirodex.models import UserPreference

    validated = validate_layout_payload(payload)
    row = db.session.execute(
        select(UserPreference).filter(UserPreference.user_id == user_id),
    ).scalars().first()
    if row is None:
        row = UserPreference(user_id=user_id)
        db.session.add(row)
    row.detail_layout = validated
    db.session.commit()
    return validated


def clear_user_detail_layout(user_id: int) -> dict[str, Any]:
    """Drop the override and go back to following the install default.

    Deliberately not "save the current install default as mine" — the point of
    clearing is to start tracking the admin's layout again, and copying it would
    leave the member pinned to today's version of it forever.
    """
    from oneirodex.models import UserPreference

    row = db.session.execute(
        select(UserPreference).filter(UserPreference.user_id == user_id),
    ).scalars().first()
    if row is not None:
        row.detail_layout = None
        db.session.commit()
    return get_detail_layout()


def list_layout_presets(user_id: int) -> list[dict[str, Any]]:
    from oneirodex.models import DetailLayoutPreset

    rows = db.session.execute(
        select(DetailLayoutPreset)
        .filter(DetailLayoutPreset.user_id == user_id)
        .order_by(DetailLayoutPreset.name),
    ).scalars().all()
    return [
        {'id': row.id, 'name': row.name, 'layout': merge_with_defaults(row.layout)}
        for row in rows
    ]


def save_layout_preset(user_id: int, name: str, payload: dict | None) -> dict[str, Any]:
    """Create or overwrite a named arrangement for this member.

    Overwrites by name rather than erroring: "save as Couch" when Couch exists
    is an update in every editor anyone has used, and the unique constraint
    would otherwise surface as a 500 on a perfectly reasonable action.
    """
    from oneirodex.models import DetailLayoutPreset

    clean = (name or '').strip()
    if not clean:
        raise ValueError('Preset name is required')
    if len(clean) > 64:
        raise ValueError('Preset name is too long (64 characters max)')

    validated = validate_layout_payload(payload)
    row = db.session.execute(
        select(DetailLayoutPreset).filter(
            DetailLayoutPreset.user_id == user_id,
            DetailLayoutPreset.name == clean,
        ),
    ).scalars().first()
    if row is None:
        row = DetailLayoutPreset(user_id=user_id, name=clean, layout=validated)
        db.session.add(row)
    else:
        row.layout = validated
    db.session.commit()
    return {'id': row.id, 'name': row.name, 'layout': validated}


def delete_layout_preset(user_id: int, preset_id: int) -> bool:
    """Delete one of this member's presets.

    Scoped by user_id as well as id on purpose — a preset id alone must never
    be enough to delete across accounts, the same rule the PC cheat delete
    follows.
    """
    from oneirodex.models import DetailLayoutPreset

    row = db.session.execute(
        select(DetailLayoutPreset).filter(
            DetailLayoutPreset.id == preset_id,
            DetailLayoutPreset.user_id == user_id,
        ),
    ).scalars().first()
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def layout_helpers(layout: dict[str, Any] | None = None) -> dict[str, Any]:
    """Template helpers: order index and visibility map."""
    data = layout or get_detail_layout()
    order: dict[str, int] = {}
    visible: dict[str, bool] = {}
    for index, item in enumerate(data.get('sections') or []):
        sid = item['id']
        order[sid] = index
        visible[sid] = bool(item.get('visible', True))
    return {'layout_order': order, 'layout_visible': visible, 'detail_layout': data}
