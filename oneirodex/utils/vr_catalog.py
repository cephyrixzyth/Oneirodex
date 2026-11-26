"""Reusable VR catalogue predicates and cover projection."""
from __future__ import annotations

import re

# "Green Hell VR", "VR Live …", "cyubeVR", "Crisis VRigade" — VR as its own
# word, or glued onto the end of a product name. Mid-word "VR" stays a word.
_VR_TOKEN_RE = re.compile(r'(?:\bVR\b|(?<=[A-Za-z0-9])VR\b)', re.IGNORECASE)

# IGDB platform names that only run VR software.
_VR_PLATFORM_MARKERS = (
    'steamvr', 'oculus', 'meta quest', 'playstation vr', 'windows mixed reality',
    'pico', 'daydream', 'gear vr', 'htc vive', 'valve index',
)


def has_vr_token(name: str | None) -> bool:
    """True when a title names VR as a word or as a glued suffix."""
    return bool(_VR_TOKEN_RE.search(name or ''))


def _names(values) -> list[str]:
    out = []
    for value in values or ():
        name = value.get('name') if isinstance(value, dict) else value
        if name:
            out.append(str(name).casefold())
    return out


def candidate_is_vr(candidate: dict | None) -> bool:
    """True when a catalogue hit is a VR product.

    Used when a folder says "VR" but the catalogue lists the game without it
    ("A Fishermans Tale VR" → "A Fisherman's Tale"): the flat title is only
    accepted for a VR product, so "Green Hell VR" can never become "Green Hell".
    """
    if not isinstance(candidate, dict):
        return False
    if candidate.get('is_vr') is True or has_vr_token(candidate.get('name')):
        return True
    if 'virtual reality' in _names(candidate.get('player_perspectives')):
        return True
    return any(
        name.startswith(marker)
        for name in _names(candidate.get('platforms'))
        for marker in _VR_PLATFORM_MARKERS
    )


def vr_profile_link(game_model, profile_model, kinds: tuple[str, ...]):
    from sqlalchemy import select

    return (
        select(profile_model.id)
        .where(profile_model.game_uuid == game_model.uuid, profile_model.kind.in_(kinds))
        .correlate(game_model)
    )


def vr_perspective_link(game_model, perspective_model, association, perspective_names):
    from sqlalchemy import func, select

    return (
        select(1)
        .select_from(
            association.join(
                perspective_model,
                perspective_model.id == association.c.player_perspective_id,
            )
        )
        .where(
            association.c.game_id == game_model.id,
            func.lower(perspective_model.name).in_(perspective_names),
        )
    )


def game_in_vr_hub(game, compatibility_for_game) -> bool:
    return compatibility_for_game(game) in ('native_vr', 'injector_profile')


def cover_url_for_game(game, session, game_model, image_model) -> str | None:
    from sqlalchemy import select

    from oneirodex.utils.cover_url import resolve_cover_url, resolve_game_cover_url

    cover = session.execute(
        select(image_model).filter_by(game_uuid=game.uuid, image_type='cover').limit(1),
    ).scalars().first()
    if not cover:
        cover = session.execute(
            select(image_model).filter(
                image_model.game_uuid == game.uuid,
                image_model.url.ilike('%cover%'),
            ).limit(1),
        ).scalars().first()
    image_urls = (
        str(getattr(cover, 'url', '') or '').replace('\\', '/').lower(),
        str(getattr(cover, 'download_url', '') or '').replace('\\', '/').lower(),
    )
    if any(url.endswith('default_cover.jpg') for url in image_urls):
        cover = None
    if not cover:
        box_art = session.execute(
            select(image_model).filter_by(game_uuid=game.uuid, image_type='box').limit(1),
        ).scalars().first()
        box_url = str(getattr(box_art, 'url', '') or '').replace('\\', '/').lower()
        if box_art and not box_url.endswith('default_cover.jpg'):
            cover = box_art
    resolved = resolve_game_cover_url(game, cover)
    if str(resolved or '').replace('\\', '/').lower().endswith('default_cover.jpg'):
        resolved = resolve_cover_url(None, title=game.name)
    return resolved
