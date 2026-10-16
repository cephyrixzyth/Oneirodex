"""Attach catalog guide metadata to a game (GameURL + optional GameExtra notes)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameExtra, GameURL

GUIDE_URL_TYPE = 'translation_guide'


def attach_patch_guide(
    game: Game,
    *,
    source_url: str,
    notes: str | None = None,
    target_language: str | None = None,
    patch_format: str | None = None,
) -> dict[str, Any]:
    """Create/update a translation_guide GameURL and annotate matching extras."""
    url = (source_url or '').strip()
    if not url:
        raise ValueError('source_url is required')
    if not (url.startswith('http://') or url.startswith('https://')):
        raise ValueError('source_url must be an http(s) URL')

    existing = db.session.execute(
        select(GameURL).filter_by(game_uuid=game.uuid, url_type=GUIDE_URL_TYPE, url=url)
    ).scalars().first()
    if existing is None:
        db.session.add(
            GameURL(game_uuid=game.uuid, url_type=GUIDE_URL_TYPE, url=url)
        )

    extras = db.session.execute(
        select(GameExtra).filter_by(game_uuid=game.uuid, extra_kind='translation_patch')
    ).scalars().all()
    annotated = 0
    for extra in extras:
        if not getattr(extra, 'source_url', None):
            extra.source_url = url
            annotated += 1
        if notes and not getattr(extra, 'nfo_content', None):
            extra.nfo_content = notes
        if target_language and not getattr(extra, 'target_language', None):
            extra.target_language = target_language[:16]
        if patch_format and not getattr(extra, 'patch_format', None):
            extra.patch_format = patch_format[:8]

    db.session.commit()
    return {
        'ok': True,
        'game_uuid': game.uuid,
        'source_url': url,
        'url_type': GUIDE_URL_TYPE,
        'extras_annotated': annotated,
        'notes': notes,
        'target_language': target_language,
        'patch_format': patch_format,
    }
