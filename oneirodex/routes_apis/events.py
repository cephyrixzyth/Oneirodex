"""Server-Sent Events stream for scan/download realtime updates."""

from __future__ import annotations

from flask import jsonify
from flask_login import current_user, login_required

from oneirodex.utils.api_response import api_error
from oneirodex.utils.event_bus import event_bus

from . import apis_bp
from oneirodex.utils.rbac import is_admin


@apis_bp.route('/events/stream', methods=['GET'])
@login_required
def events_stream():
    """WSGI fallback — real SSE is native ASGI (`asgi.py`) to avoid worker starvation."""
    return api_error(
        'SSE requires ASGI',
        code='unavailable',
        detail=(
            'Serve Oneirodex with uvicorn asgi:asgi_app. '
            '/api/events/stream is handled natively outside WsgiToAsgi.'
        ),
    )


@apis_bp.route('/events/publish_test', methods=['POST'])
@login_required
def events_publish_test():
    """Admin-only test event for verifying the bus."""
    if not is_admin(current_user):
        return api_error('Admin required', code='forbidden')
    event = event_bus.publish('test', message='ping', user=current_user.name)
    return jsonify(event.to_dict())
