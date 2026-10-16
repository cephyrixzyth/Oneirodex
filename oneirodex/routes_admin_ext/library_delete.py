"""Admin: full-library deletion (routes + background worker).

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1e): the SSE progress
stream (``delete_library_progress``), the background worker
(``delete_library_background``), the deletion entry point
(``delete_full_library``), the poll fallback (``check_deletion_progress``), and
the module-level ``deletion_progress`` dict they share.

The blueprint is ``admin2_bp`` (registered with **no** ``url_prefix``), so every
URL rule here is byte-identical to when these lived on the ``main`` blueprint;
only the endpoint names change (``main.*`` -> ``admin2.*``).

Route/worker bodies moved verbatim; the ``print()`` calls become module-level
``logger.{info,warning,error}``.

Note on the SSE route: ``asgi.py``'s ``_SSE_ROUTES`` does **not** list
``/delete_library_progress`` -- it runs through the WSGI bridge fallback
(``tests/test_sse_wsgi_fallback.py``). The path is unchanged by this move, so no
``asgi.py`` edit is required.
"""

import json
import logging
import uuid

from flask import Response, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, Library, ScanJob
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.library_deletion import delete_library_background, deletion_progress
from oneirodex.routes_admin_ext import admin2_bp

logger = logging.getLogger(__name__)


@admin2_bp.route('/delete_library_progress/<job_id>')
@login_required
@admin_required
def delete_library_progress(job_id):
    """SSE endpoint for library deletion progress"""
    logger.info(f"SSE endpoint accessed for job_id: {job_id} by user: {current_user.name if current_user.is_authenticated else 'Anonymous'}")
    def event_stream():
        import time

        # Initial delay to ensure EventSource connection is established
        time.sleep(0.2)

        # Send initial connection confirmation
        yield f"data: {json.dumps({'status': 'connected', 'message': 'Progress tracking connected'})}\n\n"

        # Wait for progress data to appear (up to 10 seconds)
        wait_count = 0
        while job_id not in deletion_progress and wait_count < 20:
            time.sleep(0.5)
            wait_count += 1

        if job_id not in deletion_progress:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Progress data not found'})}\n\n"
            return

        # Stream progress updates
        while job_id in deletion_progress:
            progress_data = deletion_progress[job_id]
            yield f"data: {json.dumps(progress_data)}\n\n"

            if progress_data.get('status') == 'completed' or progress_data.get('status') == 'error':
                # Keep data for a moment to ensure client receives it
                time.sleep(1)
                # Clean up after completion
                if job_id in deletion_progress:
                    del deletion_progress[job_id]
                break

            # Wait before checking again
            time.sleep(0.3)

    # Create response with proper SSE headers
    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response


@admin2_bp.route('/delete_full_library/<library_uuid>', methods=['POST'])
@login_required
@admin_required
def delete_full_library(library_uuid=None):
    logger.info(f"Route: /delete_full_library - {current_user.name} - {current_user.role} method: {request.method} UUID: {library_uuid}")

    if not library_uuid:
        return api_error('No library specified', code='bad_request', body_status='error')

    # Get library info immediately for progress tracking
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library:
        return api_error('Library not found', code='not_found', body_status='error')

    # Optional server-side typed confirm (W22-1). Legacy Jinja clients omit these
    # and keep client-only typing. When confirm_name/force are present, enforce.
    data = request.get_json(silent=True) or {}
    force_raw = (
        data.get('force') if 'force' in data
        else (data.get('force_delete') if 'force_delete' in data
              else (request.form.get('force') or request.form.get('force_delete')
                    or request.args.get('force') or request.args.get('force_delete')))
    )
    confirm_raw = (
        data.get('confirm_name') if 'confirm_name' in data
        else (request.form.get('confirm_name') or request.args.get('confirm_name'))
    )
    if force_raw is not None or confirm_raw is not None:
        from oneirodex.utils.library_batch import (
            parse_bool_flag,
            parse_confirm_names,
            require_confirm_or_force,
        )
        force = parse_bool_flag(force_raw, default=False)
        confirm_names = parse_confirm_names(data)
        confirm_err = require_confirm_or_force(
            library_uuid=library.uuid,
            library_name=library.name,
            force=force,
            confirm_names=confirm_names,
            single_confirm_name=str(confirm_raw) if confirm_raw is not None else None,
        )
        if confirm_err:
            confirm_message = (
                'Type the exact library name to confirm, or pass force=true '
                '(admin + CSRF still required).'
                if confirm_err == 'confirm_name_required'
                else 'confirm_name does not match library name.'
            )
            return api_error(
                confirm_message,
                code='bad_request',
                body_status='error',
                body_error=confirm_err,
                expected_name=library.name if confirm_err == 'confirm_name_mismatch' else None,
            )

    # Generate a unique job ID
    job_id = str(uuid.uuid4())

    # Create initial progress data immediately in main thread to prevent race condition
    deletion_progress[job_id] = {
        'status': 'initializing',
        'message': f'Preparing to delete library "{library.name}"...',
        'current': 0,
        'total': 0,
        'library_name': library.name
    }

    # Start background deletion
    delete_library_background(library_uuid, job_id)

    # Return job ID for progress tracking. admin_manage_libs.js reads
    # `data.status === 'started'` (job state, kept as data on api_ok).
    return api_ok({'status': 'started', 'job_id': job_id})

@admin2_bp.route('/check_deletion_progress/<job_id>')
@login_required
@admin_required
def check_deletion_progress(job_id):
    """Simple progress check endpoint as fallback for SSE"""
    # `status` on the live dict is job progress (`initializing` / `connected` /
    # `completed` / `error`), not an envelope marker. Wrapping with api_ok
    # would stamp ok=True onto a failed delete. admin_manage_libs.js branches
    # on it. Recorded in the envelope baseline on purpose.
    if job_id in deletion_progress:
        return jsonify(deletion_progress[job_id])
    return api_error('Job not found', code='not_found', body_status='not_found')
