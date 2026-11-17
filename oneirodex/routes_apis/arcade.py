"""Arcade launch profile (INSP-43, v11 H4b).

One field on a game: how the cabinet was driven. The desktop companion reads
it to pick a matching RetroArch input remap, so a spinner game does not launch
bound like a stick game. Catalogue data only -- nothing here points at a ROM,
a MAME set or a file on disk.
"""

from __future__ import annotations

from flask import current_app
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.schemas.arcade import InputFamilyBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import librarian_required
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.secondary_scrapers import INPUT_FAMILY_VALUES, game_input_family
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.route('/games/<game_uuid>/input_family', methods=['PATCH'])
@login_required
@librarian_required
@validate_body(InputFamilyBody)
def game_input_family_patch(game_uuid: str, body: InputFamilyBody):
    """joystick / spinner / lightgun / trackball, or null for unknown."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    game.input_family = body.input_family
    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning('input_family save failed for %s: %s', game_uuid, exc)
        return api_error("Couldn't save the control family.", code='internal')
    return api_ok({
        'uuid': game.uuid,
        'input_family': game_input_family(game),
        'families': list(INPUT_FAMILY_VALUES),
    })
