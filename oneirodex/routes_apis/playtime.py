"""Playtime session APIs."""

from flask import jsonify
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, PlaySession, UserGameProgress
from oneirodex.schemas.playtime import StartPlaytimeSessionBody
from oneirodex.utils.api_response import api_error
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.playtime import end_session, heartbeat_session, start_session
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.route('/playtime/sessions', methods=['POST'])
@login_required
@validate_body(StartPlaytimeSessionBody)
def playtime_start(body: StartPlaytimeSessionBody):
    try:
        session = start_session(current_user.id, body.game_uuid, client=body.client)
    except PermissionError:
        return api_error('Forbidden', code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='not_found')
    return jsonify(session.to_dict()), 201


@apis_bp.route('/playtime/sessions/<int:session_id>/heartbeat', methods=['POST'])
@login_required
def playtime_heartbeat(session_id: int):
    session = db.session.get(PlaySession, session_id)
    if not session or session.user_id != current_user.id:
        return api_error('Session not found', code='not_found')
    try:
        session = heartbeat_session(session)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(session.to_dict())


@apis_bp.route('/playtime/sessions/<int:session_id>/stop', methods=['POST'])
@login_required
def playtime_stop(session_id: int):
    session = db.session.get(PlaySession, session_id)
    if not session or session.user_id != current_user.id:
        return api_error('Session not found', code='not_found')
    session = end_session(session)
    return jsonify(session.to_dict())


@apis_bp.route('/playtime/me', methods=['GET'])
@login_required
def playtime_me():
    rows = db.session.execute(
        select(UserGameProgress)
        .filter_by(user_id=current_user.id)
        .order_by(UserGameProgress.last_played_at.desc())
        .limit(100)
    ).scalars().all()
    game_uuids = [r.game_uuid for r in rows]
    games_by_uuid = {}
    if game_uuids:
        for game in db.session.execute(select(Game).filter(Game.uuid.in_(game_uuids))).scalars().all():
            games_by_uuid[game.uuid] = game
    visible_rows = [
        row for row in rows
        if row.game_uuid in games_by_uuid
        and user_can_access_game(current_user, games_by_uuid[row.game_uuid])
    ]
    total = sum(int(row.total_seconds or 0) for row in visible_rows)
    games = []
    for row in visible_rows:
        payload = row.to_dict()
        payload['game_name'] = games_by_uuid[row.game_uuid].name
        games.append(payload)
    return jsonify({
        'total_seconds': total,
        'games': games,
    })


@apis_bp.route('/playtime/games/<game_uuid>', methods=['GET'])
@login_required
def playtime_for_game(game_uuid: str):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game or not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    row = db.session.execute(
        select(UserGameProgress).filter_by(user_id=current_user.id, game_uuid=game_uuid)
    ).scalars().first()
    if not row:
        return jsonify({
            'user_id': current_user.id,
            'game_uuid': game_uuid,
            'total_seconds': 0,
            'session_count': 0,
            'last_played_at': None,
        })
    return jsonify(row.to_dict())
