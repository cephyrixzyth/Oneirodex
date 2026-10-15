"""Reusable VR catalogue predicates and cover projection."""
from __future__ import annotations


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
