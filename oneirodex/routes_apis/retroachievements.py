"""RetroAchievements (R1/R2) — admin match + status, member progress.

Read-only against the provider. Nothing here unlocks an achievement: browser
play has no rcheevos runtime, so a set is *shown*, never *played for*, here.
"""

from __future__ import annotations

from flask import current_app
from flask_login import current_user, login_required
from pydantic import BaseModel, Field
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, UserPreference
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.validation import validate_body
from oneirodex.utils.retroachievements import (
    achievement_fields,
    configured,
    fetch_member_progress,
    match_platform,
    save_settings,
    settings_summary,
    status_summary,
    supported_platforms,
)
from oneirodex.utils.auth import admin_required

from . import apis_bp


class RetroAchievementsSettingsBody(BaseModel, extra='forbid'):
    username: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False


@apis_bp.route('/admin/integrations/retroachievements', methods=['GET'])
@login_required
@admin_required
def retroachievements_settings_get():
    """Read household credential state without returning the API key."""
    return api_ok(settings_summary())


@apis_bp.route('/admin/integrations/retroachievements', methods=['PUT'])
@login_required
@admin_required
@validate_body(RetroAchievementsSettingsBody)
def retroachievements_settings_put(body: RetroAchievementsSettingsBody):
    """Save household credentials without returning the API key."""
    username = body.username
    if username is not None:
        username = username.strip()
        if username and not all(ch.isalnum() or ch in '_-.' for ch in username):
            return api_error('Username may only contain letters, digits, _ - .', code='bad_request')
    api_key = body.api_key
    if api_key is not None:
        api_key = api_key.strip()
    return api_ok(
        save_settings(
            username=username,
            api_key=api_key,
            clear_api_key=body.clear_api_key,
        ),
    )


@apis_bp.route('/retroachievements/status', methods=['GET'])
@login_required
@admin_required
def retroachievements_status():
    return api_ok(status_summary())


class MatchBody(BaseModel, extra='forbid'):
    platform: str = Field(min_length=1, max_length=32)
    rehash: bool = False


@apis_bp.route('/retroachievements/match', methods=['POST'])
@login_required
@admin_required
@validate_body(MatchBody)
def retroachievements_match(body: MatchBody):
    """Refresh the console index (if stale) and match every game on a platform."""
    if not configured():
        return api_error(
            'RetroAchievements is not configured — save the household username and web API key '
            'under Admin → Integrations.',
            code='forbidden',
        )
    key = body.platform.strip().upper()
    if key not in supported_platforms():
        return api_error(
            f'{key} is not a system this build can hash for RetroAchievements',
            code='bad_request',
            supported=supported_platforms(),
        )
    try:
        summary = match_platform(key, rehash=body.rehash)
    except RuntimeError as exc:
        return api_error(str(exc), code='forbidden')
    except Exception as exc:  # noqa: BLE001 — a provider outage is a 502-class answer, not a trace
        db.session.rollback()
        # Not the exception text: the request URL carries the API key.
        current_app.logger.warning('RetroAchievements lookup failed: %s', type(exc).__name__)
        return api_error('RetroAchievements lookup failed. Try again later.', code='upstream')
    return api_ok(summary)


@apis_bp.route('/games/<game_uuid>/achievements', methods=['GET'])
@login_required
def game_achievements(game_uuid):
    """The matched set for a game, plus this member's progress when they gave a username."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    fields = achievement_fields(game)
    prefs = getattr(current_user, 'preferences', None)
    ra_username = (getattr(prefs, 'ra_username', None) or '').strip()
    me = None
    if fields['supports_achievements'] and ra_username:
        me = fetch_member_progress(ra_username, fields['ra_game_id'])
    return api_ok({
        **fields,
        'configured': configured(),
        'ra_username': ra_username or None,
        # Honesty (R2): nothing played in the browser unlocks anything.
        'unlocks_here': False,
        'me': me,
    })


class RaUsernameBody(BaseModel, extra='forbid'):
    ra_username: str = Field(default='', max_length=64)


@apis_bp.route('/me/retroachievements', methods=['GET'])
@login_required
def me_retroachievements_get():
    """This member's RetroAchievements username (public handle, never a key)."""
    prefs = getattr(current_user, 'preferences', None)
    return api_ok({
        'ra_username': (getattr(prefs, 'ra_username', None) or '') or None,
        'configured': configured(),
    })


@apis_bp.route('/me/retroachievements', methods=['PUT'])
@login_required
@validate_body(RaUsernameBody)
def me_retroachievements_put(body: RaUsernameBody):
    name = body.ra_username.strip()
    if name and not all(ch.isalnum() or ch in '_-.' for ch in name):
        return api_error('Username may only contain letters, digits, _ - .', code='bad_request')
    prefs = getattr(current_user, 'preferences', None)
    if prefs is None:
        prefs = UserPreference(user_id=current_user.id)
        db.session.add(prefs)
    prefs.ra_username = name or None
    db.session.commit()
    return api_ok({'ra_username': prefs.ra_username, 'configured': configured()})
