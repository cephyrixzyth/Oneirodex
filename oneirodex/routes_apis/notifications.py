"""Notification center API (Wave 14c)."""

from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required

from oneirodex.utils.auth import admin_required

from oneirodex import db
from oneirodex.models import UserPreference
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.notifications import list_notifications, mark_read, unread_count

from oneirodex.utils.api_tokens import require_api_scope, user_has_scope

from . import apis_bp


@apis_bp.route('/notifications', methods=['GET'])
@login_required
@require_api_scope('read:social')
def notifications_list():
    unread_only = str(request.args.get('unread') or '').lower() in ('1', 'true', 'yes')
    try:
        limit = int(request.args.get('limit') or 40)
    except (TypeError, ValueError):
        limit = 40
    limit = min(100, max(1, limit))
    rows = list_notifications(
        current_user.id, limit=limit, unread_only=unread_only,
    )
    return jsonify({
        'notifications': rows,
        'unread_count': unread_count(current_user.id),
        'empty': len(rows) == 0,
    })


@apis_bp.route('/notifications/read', methods=['POST'])
@login_required
@require_api_scope('write:social')
def notifications_read():
    data = request.get_json(silent=True) or {}
    all_read = bool(data.get('all'))
    ids = data.get('ids') if isinstance(data.get('ids'), list) else []
    cleaned = []
    for value in ids:
        try:
            cleaned.append(int(value))
        except (TypeError, ValueError):
            continue
    count = mark_read(current_user.id, cleaned, all_read=all_read)
    return api_ok({
        'marked': count,
        'unread_count': unread_count(current_user.id),
    })


@apis_bp.route('/notifications/preferences', methods=['GET', 'POST'])
@login_required
@require_api_scope('read:social')
def notifications_preferences():
    if request.method == 'POST' and not user_has_scope('write:social'):
        return api_error(
            'Missing scope: write:social',
            code='forbidden',
            detail={'required_scope': 'write:social'},
        )
    prefs = current_user.preferences
    if prefs is None:
        prefs = UserPreference(user_id=current_user.id)
        db.session.add(prefs)
        db.session.commit()
    if request.method == 'GET':
        return jsonify({
            'notify_friend_requests': bool(getattr(prefs, 'notify_friend_requests', True)),
            'notify_activity': bool(getattr(prefs, 'notify_activity', True)),
            'notify_mentions': bool(getattr(prefs, 'notify_mentions', True)),
            'notify_chat': bool(getattr(prefs, 'notify_chat', True)),
            'notify_free_games': bool(getattr(prefs, 'notify_free_games', True)),
            'email_notify_social': bool(getattr(prefs, 'email_notify_social', True)),
            'email_digest_daily': bool(getattr(prefs, 'email_digest_daily', False)),
            # Not an alert: whether accepted friends see what this member is
            # playing on their Discover feed. Lives here because this is the
            # endpoint that owns member preference toggles.
            'share_activity': bool(getattr(prefs, 'share_activity', True)),
        })
    data = request.get_json(silent=True) or {}
    for key in (
        'notify_friend_requests',
        'notify_activity',
        'notify_mentions',
        'notify_chat',
        'notify_free_games',
        'email_notify_social',
        'email_digest_daily',
        'share_activity',
    ):
        if key in data:
            setattr(prefs, key, bool(data[key]))
    db.session.commit()
    return api_ok()


@apis_bp.route('/admin/notify-bus/test', methods=['POST'])
@login_required
@admin_required
def notify_bus_test():
    """Send one test event to the configured Apprise API / ntfy endpoints
    (INSP-6) and say what was delivered. No body; nothing is stored."""
    from oneirodex.utils.notification_bus import emit, status_summary

    status = status_summary()
    if not status['configured']:
        return api_error(
            'No notification endpoint configured (NOTIFY_APPRISE_URLS / NOTIFY_NTFY_URL).',
            code='bad_request',
            **status,
        )
    sent = emit(kind='test', title='Oneirodex test notification', body='If you can read this, the notification bus reaches your device.')
    return api_ok({'sent': sent, **status})
