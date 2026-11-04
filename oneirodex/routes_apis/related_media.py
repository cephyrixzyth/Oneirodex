"""Related media attached to a game — adaptations, tie-ins, soundtracks.

Scope guard (human 2026-08-04): Oneirodex is **not** becoming a media tracker.
A film, book or album exists here only as context on a game's page. Nothing is
tracked, rated or progressed, and no route here downloads anything — the only
outward action is a link to where the thing legitimately lives.
"""

from __future__ import annotations

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GameRelatedMedia
from oneirodex.schemas.related_media import CreateRelatedMediaBody
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.rbac import librarian_required
from oneirodex.utils.validation import validate_body
from oneirodex.utils.api_tokens import require_api_token_scope

from . import apis_bp

MEDIA_KINDS = {
    'film': 'Film',
    'series': 'TV series',
    'anime': 'Anime',
    'book': 'Book',
    'comic': 'Comic',
    'music': 'Soundtrack / music',
    'podcast': 'Podcast',
}

RELATIONS = {
    'adaptation': 'Adaptation of this game',
    'tie_in': 'Tie-in',
    'soundtrack': 'Soundtrack',
    'novelisation': 'Novelisation',
    'documentary': 'Documentary',
    'inspired_by': 'Inspired by this game',
}

# Store/stream pages only. A link that looks like a download is refused: this
# feature points at where media legitimately lives, nothing more.
_DOWNLOADISH = ('download', 'torrent', 'magnet:', '.iso', '.mkv', '.mp4', 'warez')


def _clean_url(raw: str | None) -> str | None:
    url = (raw or '').strip()
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        raise ValueError('Link must be an http(s) URL')
    if any(token in url.lower() for token in _DOWNLOADISH):
        raise ValueError('Link must point at a store or stream page, not a download')
    return url[:500]


@apis_bp.route('/games/<game_uuid>/related_media', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def related_media_list(game_uuid: str):
    """Media attached to this game, plus the vocabularies for the editor."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')

    rows = db.session.execute(
        select(GameRelatedMedia)
        .filter_by(game_uuid=game_uuid)
        .order_by(GameRelatedMedia.display_order.asc(), GameRelatedMedia.id.asc())
    ).scalars().all()

    items = [row.to_dict() for row in rows]
    counts: dict[str, int] = {}
    for item in items:
        counts[item['media_kind']] = counts.get(item['media_kind'], 0) + 1

    return api_ok({
                'game_uuid': game_uuid,
        'items': items,
        # Which facets exist at all — lets the UI show only the kinds present
        # rather than a row of empty categories.
        'available_kinds': [k for k in MEDIA_KINDS if counts.get(k)],
        'counts': counts,
        'kinds': [{'id': k, 'label': v} for k, v in MEDIA_KINDS.items()],
        'relations': [{'id': k, 'label': v} for k, v in RELATIONS.items()],
    })


@apis_bp.route('/games/<game_uuid>/related_media', methods=['POST'])
@login_required
@librarian_required
@validate_body(CreateRelatedMediaBody)
def related_media_create(game_uuid: str, body: CreateRelatedMediaBody):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')

    title = body.title
    kind = (body.media_kind or '').strip().lower()
    if kind not in MEDIA_KINDS:
        return api_error(f"media_kind must be one of: {', '.join(sorted(MEDIA_KINDS))}", code='bad_request')

    relation = (body.relation or 'tie_in').strip().lower()
    if relation not in RELATIONS:
        return api_error(f"relation must be one of: {', '.join(sorted(RELATIONS))}", code='bad_request')

    try:
        external_url = _clean_url(body.external_url)
        cover_url = _clean_url(body.cover_url)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')

    year = body.year
    if year not in (None, ''):
        try:
            year = int(year)
        except (TypeError, ValueError):
            return api_error('year must be a number', code='bad_request')
    else:
        year = None

    row = GameRelatedMedia(
        game_uuid=game_uuid,
        media_kind=kind,
        relation=relation,
        title=title[:240],
        creator=(body.creator or '').strip()[:160] or None,
        year=year,
        summary=(body.summary or '').strip()[:1000] or None,
        external_url=external_url,
        cover_url=cover_url,
        display_order=int(body.display_order or 0),
        created_by_user_id=getattr(current_user, 'id', None),
    )
    db.session.add(row)
    db.session.commit()
    return api_ok({'item': row.to_dict()}, status=201)


@apis_bp.route('/games/<game_uuid>/related_media/<int:item_id>', methods=['DELETE'])
@login_required
@librarian_required
def related_media_delete(game_uuid: str, item_id: int):
    row = db.session.get(GameRelatedMedia, item_id)
    # Require the matching game, so an id alone cannot delete across games.
    if row is None or row.game_uuid != game_uuid:
        return api_error('Item not found', code='not_found')
    db.session.delete(row)
    db.session.commit()
    return api_ok({'removed': item_id})
