"""VR / headset browse APIs (catalog + detail, no downloads)."""

from __future__ import annotations

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import and_, exists, func, or_, select

from oneirodex import db
from oneirodex.models import Game, GameVrProfile, Image, PlayerPerspective, game_player_perspective_association
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import librarian_required
from oneirodex.utils.validation import validate_body
from oneirodex.schemas.vr import VrCompatBody, VrProfileBody
from oneirodex.utils.cover_url import resolve_cover_url, resolve_game_cover_url
from oneirodex.utils.functions import format_size
from oneirodex.utils.library_acl import apply_game_access_filters, user_can_access_game
from oneirodex.utils.secondary_scrapers import VR_PERSPECTIVE_NAME, game_indicates_vr, game_vr_compat

from . import apis_bp

_VR_PERSPECTIVE_NAMES = (
    VR_PERSPECTIVE_NAME.lower(),
    'vr',
    'vr / virtual reality',
)


def _vr_games_query():
    """Games that play in a headset -- not the whole library.

    A title belongs here when its perspectives say Virtual Reality, or when a
    librarian stored ``vr_compat`` as ``native_vr`` / ``injector_profile``
    (rider R3). A stored ``flat`` removes a perspective-tagged title -- the
    librarian's word wins over the scrape.

    Uses EXISTS (not DISTINCT on Game) so Postgres JSON columns on ``games``
    do not break equality for DISTINCT.
    """
    return select(Game).where(
        or_(
            Game.vr_compat.in_(('native_vr', 'injector_profile')),
            and_(Game.vr_compat.is_(None), exists(_vr_perspective_link())),
            # INSP-40: a headset record (native / injector) is evidence too
            and_(Game.vr_compat.is_(None), exists(_vr_profile_link(('native', 'injector')))),
        )
    )


def _vr_profile_link(kinds: tuple[str, ...]):
    return (
        select(GameVrProfile.id)
        .where(GameVrProfile.game_uuid == Game.uuid, GameVrProfile.kind.in_(kinds))
        .correlate(Game)
    )


def _vr_perspective_link():
    """EXISTS body: this game has a Virtual Reality player perspective."""
    assoc = game_player_perspective_association
    return (
        select(1)
        .select_from(
            assoc.join(
                PlayerPerspective,
                PlayerPerspective.id == assoc.c.player_perspective_id,
            )
        )
        .where(
            assoc.c.game_id == Game.id,
            func.lower(PlayerPerspective.name).in_(_VR_PERSPECTIVE_NAMES),
        )
    )


def _game_in_vr_hub(game) -> bool:
    return game_vr_compat(game) in ('native_vr', 'injector_profile')


def _vr_enabled() -> bool:
    return str(current_app.config.get('ENABLE_VR_BROWSE', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def _cover_url_for_game(game: Game) -> str | None:
    cover = db.session.execute(
        select(Image).filter_by(game_uuid=game.uuid, image_type='cover').limit(1),
    ).scalars().first()
    if not cover:
        cover = db.session.execute(
            select(Image).filter(Image.game_uuid == game.uuid, Image.url.ilike('%cover%')).limit(1),
        ).scalars().first()
    image_urls = (
        str(getattr(cover, 'url', '') or '').replace('\\', '/').lower(),
        str(getattr(cover, 'download_url', '') or '').replace('\\', '/').lower(),
    )
    if any(url.endswith('default_cover.jpg') for url in image_urls):
        # Old catalog rows can still point at the retired GameTheca placeholder.
        # Ignore it so a real box scan, legacy Game.cover, or per-title fallback
        # can be used instead.
        cover = None
    if not cover:
        box_art = db.session.execute(
            select(Image).filter_by(game_uuid=game.uuid, image_type='box').limit(1),
        ).scalars().first()
        box_url = str(getattr(box_art, 'url', '') or '').replace('\\', '/').lower()
        if box_art and not box_url.endswith('default_cover.jpg'):
            cover = box_art
    resolved = resolve_game_cover_url(game, cover)
    if str(resolved or '').replace('\\', '/').lower().endswith('default_cover.jpg'):
        resolved = resolve_cover_url(None, title=game.name)
    return resolved


@apis_bp.route('/vr/catalog', methods=['GET'])
@login_required
def vr_catalog():
    if not _vr_enabled():
        return api_error('VR browse is disabled', code='forbidden')
    try:
        page = max(1, int(request.args.get('page') or 1))
        per_page = min(100, max(1, int(request.args.get('per_page') or 24)))
    except (TypeError, ValueError):
        return api_error('Invalid pagination', code='bad_request')

    query = apply_game_access_filters(_vr_games_query(), current_user)
    # `?vr_compat=native_vr|injector_profile` narrows the hub to one way to play.
    wanted = str(request.args.get('vr_compat') or '').strip().lower()
    if wanted == 'native_vr':
        query = query.where(
            or_(
                Game.vr_compat == 'native_vr',
                and_(Game.vr_compat.is_(None), exists(_vr_profile_link(('native',)))),
                and_(
                    Game.vr_compat.is_(None),
                    ~exists(_vr_profile_link(('injector',))),
                    exists(_vr_perspective_link()),
                ),
            )
        )
    elif wanted == 'injector_profile':
        query = query.where(
            or_(
                Game.vr_compat == 'injector_profile',
                and_(
                    Game.vr_compat.is_(None),
                    ~exists(_vr_profile_link(('native',))),
                    exists(_vr_profile_link(('injector',))),
                ),
            )
        )
    query = query.order_by(Game.name.asc())

    total = db.session.execute(
        select(func.count()).select_from(query.order_by(None).subquery()),
    ).scalar() or 0
    pages = max(1, (total + per_page - 1) // per_page)
    rows = db.session.execute(
        query.offset((page - 1) * per_page).limit(per_page),
    ).scalars().all()

    return jsonify({
        'page': page,
        'pages': pages,
        'total': total,
        'games': [
            {
                'uuid': g.uuid,
                'name': g.name,
                'cover_url': _cover_url_for_game(g),
                'vr_compat': game_vr_compat(g),
            }
            for g in rows
        ],
    })


@apis_bp.route('/vr/games/<game_uuid>', methods=['GET'])
@login_required
def vr_game_detail(game_uuid: str):
    if not _vr_enabled():
        return api_error('VR browse is disabled', code='forbidden')
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    # Detail matches the catalog: titles outside the hub are not part of it.
    if not _game_in_vr_hub(game):
        return api_error('Game not found', code='not_found')
    size = format_size(game.size) if game.size is not None else None
    return jsonify({
        'uuid': game.uuid,
        'name': game.name,
        'cover_url': _cover_url_for_game(game),
        'summary': game.summary,
        'size': size,
        'vr_compat': game_vr_compat(game),
        'vr_profiles': [row.to_dict() for row in (game.vr_profiles or [])],
    })


VR_PROFILE_KINDS = ('native', 'injector', 'flat')


def _game_for_user(game_uuid: str):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return None, api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return None, api_error('Forbidden', code='forbidden')
    return game, None


def _vr_profiles_payload(game) -> dict:
    return {
        'uuid': game.uuid,
        'vr_profiles': [row.to_dict() for row in (game.vr_profiles or [])],
        'vr_compat': game_vr_compat(game),
        'vr_compat_stored': game.vr_compat,
        'kinds': list(VR_PROFILE_KINDS),
    }


@apis_bp.route('/games/<game_uuid>/vr_profiles', methods=['GET'])
@login_required
def game_vr_profiles(game_uuid: str):
    """The headset records for a title (INSP-40): kind, runtime, the profile
    *page*, notes. Read by any member who can read the game."""
    game, denied = _game_for_user(game_uuid)
    if denied:
        return denied
    return api_ok(_vr_profiles_payload(game))


@apis_bp.route('/games/<game_uuid>/vr_profiles/<kind>', methods=['PUT'])
@login_required
@librarian_required
@validate_body(VrProfileBody)
def game_vr_profile_put(game_uuid: str, kind: str, body: VrProfileBody):
    """Create or replace the record for one kind. Deep link only -- the URL
    is a page; Oneirodex never ships, installs or points at a shim."""
    kind = (kind or '').strip().lower()
    if kind not in VR_PROFILE_KINDS:
        return api_error('kind must be native, injector or flat', code='bad_request', kinds=list(VR_PROFILE_KINDS))
    game, denied = _game_for_user(game_uuid)
    if denied:
        return denied
    row = next((r for r in (game.vr_profiles or []) if r.kind == kind), None)
    if row is None:
        row = GameVrProfile(game_uuid=game.uuid, kind=kind)
        db.session.add(row)
    row.runtime = body.runtime
    row.profile_url = body.profile_url
    row.notes = body.notes
    row.source = body.source
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('vr_profile save failed for %s/%s: %s', game_uuid, kind, exc)
        return api_error("Couldn't save the VR profile.", code='internal')
    db.session.refresh(game)
    return api_ok({**_vr_profiles_payload(game), 'profile': row.to_dict()})


@apis_bp.route('/games/<game_uuid>/vr_profiles/<kind>', methods=['DELETE'])
@login_required
@librarian_required
def game_vr_profile_delete(game_uuid: str, kind: str):
    game, denied = _game_for_user(game_uuid)
    if denied:
        return denied
    row = next((r for r in (game.vr_profiles or []) if r.kind == (kind or '').strip().lower()), None)
    if row is None:
        return api_error('Profile not found', code='not_found')
    db.session.delete(row)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('vr_profile delete failed for %s/%s: %s', game_uuid, kind, exc)
        return api_error("Couldn't remove the VR profile.", code='internal')
    db.session.refresh(game)
    return api_ok(_vr_profiles_payload(game))


@apis_bp.route('/games/<game_uuid>/vr_compat', methods=['PATCH'])
@login_required
@librarian_required
@validate_body(VrCompatBody)
def game_vr_compat_patch(game_uuid: str, body: VrCompatBody):
    """Set how a title is played in VR (rider R3): ``native_vr``,
    ``injector_profile`` or ``flat``; ``null`` clears it back to the derived
    answer. Not gated on ``ENABLE_VR_BROWSE`` -- the row is catalogue data the
    details page reads whether or not the headset hub is on.
    """
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    game.vr_compat = body.vr_compat
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('vr_compat save failed for %s: %s', game_uuid, exc)
        return api_error("Couldn't save the VR row.", code='internal')
    return api_ok({
        'uuid': game.uuid,
        'vr_compat': game_vr_compat(game),
        'vr_compat_stored': game.vr_compat,
        'is_vr': game_indicates_vr(game),
    })
