from flask import Blueprint, current_app, jsonify, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.system_stats import format_bytes
from oneirodex.utils.uptime import get_formatted_system_uptime, get_formatted_app_uptime
from oneirodex.utils.status import get_system_info, get_config_values, get_active_users, get_log_info, get_database_info
from oneirodex import app_version, app_start_time
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.ops_summary import build_ops_summary, list_client_devices
from oneirodex.utils.health_probes import build_liveness, build_readiness

info_bp = Blueprint('info', __name__)


@info_bp.route('/pulse', methods=['GET', 'HEAD'])
def pulse():
    """Liveness — process is up (no DB). For Docker/Unraid probes.

    Named `/pulse` rather than the Kubernetes-style `/healthz`: the trailing
    `z` carries no meaning outside that convention, and Oneirodex is deployed
    via Docker/Unraid rather than kube. Any probe that reads the body still
    gets the same contract, so only the path changed.
    """
    # KEEP: probe body is `{status: 'ok'}`. `api_ok` would add envelope keys
    # probes do not read, and `status` is data here, not an envelope field.
    return jsonify(build_liveness()), 200


@info_bp.route('/awake', methods=['GET', 'HEAD'])
def awake():
    """Readiness — DB reachable + startup init complete (or TESTING).

    `/awake` for the same reason as `/pulse` above. Still answers 200 when
    ready and 503 when not, so a healthcheck only needs its URL updated.
    """
    payload, status = build_readiness()
    return jsonify(payload), status


def _theme_asset_panel(root_path=None) -> dict:
    """Theme freshness as flat key/value data for the Ops detail panel."""
    if root_path is None:
        from flask import current_app

        root_path = current_app.root_path
    from oneirodex.utils.ops_projections import theme_asset_panel

    return theme_asset_panel(root_path)


def _log_summary():
    """Project the newest ORM event to plain JSON for the Ops API."""
    from oneirodex.utils.ops_projections import log_summary

    return log_summary(get_log_info())

@info_bp.route('/admin/api/ops/system', methods=['GET'])
@login_required
@admin_required
def ops_system_json():
    """System / database / users detail for the Ops console (GT-B21).

    Server status was a separate page showing facts the Ops dashboard never
    had — OS and uptime, config values, active users, log size, database
    detail — so answering "is this box healthy?" meant reading two screens and
    holding them side by side. Ops already owns host meters, services, scans
    and errors; this is the remainder, exposed as JSON so it can be folded into
    the same pane instead of living in its own template.

    Read-only and admin-gated. Every value comes from the helpers the retired
    status page used, so Ops and the old page could not disagree while it existed.
    """
    try:
        system_info = get_system_info()
        system_info['System Uptime'] = get_formatted_system_uptime()
        system_info['Application Uptime'] = get_formatted_app_uptime(app_start_time)

        return jsonify({
            'system': system_info,
            'database': get_database_info(),
            'active_users': get_active_users(),
            'logs': _log_summary(),
            # The last thing the standalone Server info page showed that Ops did
            # not, so folding the two into one pane (W27-D1) needed it here
            # first — retiring a page that still held the only copy of something
            # is how a merge loses information.
            'config': get_config_values(),
            # Whether the theme being served is the theme we shipped.
            #
            # Theme CSS/JS only reaches static/library/themes when an admin runs
            # Reset Themes, so after any release that touches it the product
            # keeps serving the previous copy — silently. Nothing reported that,
            # and the symptom is always "the fix didn't work", which sends
            # everyone to read the stylesheet instead of the copy step.
            'theme_assets': _theme_asset_panel(),
        }), 200
    except Exception as exc:
        # Soft-fail: the Ops console must still render its other panels when a
        # single stat source (psutil, DB) is unavailable.
        current_app.logger.warning('Ops system snapshot failed: %s', exc)
        return api_error('System snapshot is unavailable', code='unavailable')


@info_bp.route('/admin/api/ops/logs', methods=['GET'])
@login_required
@admin_required
def ops_logs_json():
    """Recent system events for the Ops console (W27-D2).

    Reading the log meant leaving Ops for a separate page, which is the same
    "hold two screens side by side" problem that Server info had. The most
    recent entries belong on the console beside the metrics they explain — an
    error tile is only useful next to the error.

    Ops Recent log uses ``limit=50``; the Full-log popup uses ``limit=200``
    with client-side column filters. Bookmarks to ``/admin/system_logs`` redirect
    to ``/admin/ops?open=full-log``.
    """
    try:
        from oneirodex.models import SystemEvents

        limit = request.args.get('limit', 50, type=int)
        # Clamped: an unbounded limit from the query string is an easy way to
        # ask the console to render the entire event table.
        limit = max(1, min(limit, 200))

        rows = db.session.execute(
            select(SystemEvents)
            .options(db.joinedload(SystemEvents.user))
            .order_by(SystemEvents.timestamp.desc())
            .limit(limit),
        ).scalars().all()

        return jsonify({
            'events': [
                {
                    'id': row.id,
                    'timestamp': row.timestamp.isoformat() if row.timestamp else None,
                    'level': row.event_level,
                    'type': row.event_type,
                    'text': row.event_text,
                    # The relationship is eager-loaded, but an event can predate
                    # the user it names or belong to a deleted account.
                    'user': row.user.name if row.user else None,
                }
                for row in rows
            ],
        }), 200
    except Exception as exc:
        current_app.logger.warning('Ops logs snapshot failed: %s', exc)
        return api_error('Recent events are unavailable', code='unavailable')


@info_bp.route('/admin/server_status_page')
@login_required
@admin_required
def admin_server_status():
    """Retired: the Ops console is the one health surface (W27-D1)."""
    return redirect(url_for('info.admin_ops'))


# /admin/new_server_info retired (W27-D1).
#
# It rendered the same host facts as the Ops console from a second
# template, so "is this box healthy?" meant reading two screens. Ops has
# carried System / Database / Logs since GT-B21; the one thing only this
# page showed — the config values — moved to /admin/api/ops/system first,
# so nothing is lost by removing it.


@info_bp.route('/admin/ops')
@login_required
@admin_required
def admin_ops():
    """Render the administrator operations glance page."""
    log_system_event(
        'Admin accessed ops glance',
        event_type='audit',
        event_level='information',
    )
    return render_admin_spa(title='Ops · Oneirodex Admin')


@info_bp.route('/admin/system/danger')
@login_required
@admin_required
def admin_system_danger():
    """System → Danger zone (scoped factory reset), off the Ops glance."""
    log_system_event(
        'Admin opened system danger zone',
        event_type='audit',
        event_level='information',
    )
    return render_admin_spa(title='Danger zone · Oneirodex Admin')


@info_bp.route('/admin/api/ops/summary')
@login_required
@admin_required
def ops_summary_api():
    """Return the current operations summary snapshot."""
    try:
        return jsonify(build_ops_summary(app_start_time))
    except Exception as exc:
        current_app.logger.warning('Ops summary snapshot failed: %s', exc)
        return api_error('Ops summary is unavailable', code='unavailable')


@info_bp.route('/admin/api/ops/devices')
@login_required
@admin_required
def ops_devices_api():
    """The operator's device list: every companion / thin / browser seat that
    has sent a heartbeat, newest first (TC-4)."""
    try:
        limit = request.args.get('limit', default=200, type=int)
        return api_ok(list_client_devices(limit=limit))
    except Exception as exc:
        current_app.logger.warning('Ops device list failed: %s', exc)
        return api_error('Device list is unavailable', code='unavailable')


@info_bp.route('/admin/api/library/health')
@login_required
@admin_required
def library_health_api():
    """Lightweight library health pulse (same payload as ops ``library.health``)."""
    try:
        from oneirodex.utils.library_health import build_library_health_pulse

        return jsonify(build_library_health_pulse())
    except Exception as exc:
        current_app.logger.warning('Library health pulse failed: %s', exc)
        return api_error('Library health is unavailable', code='unavailable')
