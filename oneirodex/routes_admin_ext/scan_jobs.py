"""Admin: scan-job management routes.

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1b). These are the
manual-scan entry point and the lifecycle actions (cancel / restart / delete /
clear) for rows in ``scan_jobs``. They render / redirect only -- no JSON
envelope -- and share the ``admin/admin_manage_scanjobs.html`` template with
``admin2.scan_management`` (in ``scan_management.py``).

The blueprint is ``admin2_bp`` (registered with **no** ``url_prefix``), so every
URL rule here is byte-identical to when these lived on the ``main`` blueprint;
only the endpoint names change (``main.*`` -> ``admin2.*``).
"""

import logging
import os

from flask import (
    abort, current_app, flash, redirect, render_template, request, session, url_for,
)
from flask_login import login_required
from sqlalchemy import delete, select

from oneirodex import db
from oneirodex.forms import (
    CsrfProtectForm,
    ReleaseGroupForm,
    ScanFolderForm,
)
from oneirodex.models import AllowedFileType, Library, ReleaseGroup, ScanJob
from oneirodex.utils.auth import admin_required
from oneirodex.utils.functions import load_scanning_filter_patterns
from oneirodex.utils.gamenames import get_game_names_from_folder
from oneirodex.utils.library_roots import resolve_scan_path
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

from . import admin2_bp

logger = logging.getLogger(__name__)


@admin2_bp.route('/scan_manual_folder', methods=['GET', 'POST'])
@login_required
@admin_required
def scan_folder():
    ## to be fixed broken again after update
    form = ScanFolderForm()
    release_group_form = ReleaseGroupForm()

    libraries = db.session.execute(select(Library)).scalars().all()
    form.library_uuid.choices = [(str(lib.uuid), lib.name) for lib in libraries]

    csrf_form = CsrfProtectForm()
    game_names_with_ids = None

    # Data for template consistency with scan_management
    scanning_filters = db.session.execute(select(ReleaseGroup).order_by(ReleaseGroup.filter_pattern.asc())).scalars().all()
    allowed_file_types = db.session.execute(select(AllowedFileType).order_by(AllowedFileType.value.asc())).scalars().all()

    if form.validate_on_submit():
        if form.cancel.data:
            return redirect(url_for('admin2.scan_folder'))

        # Relative to the scan location the folder browser was pointed at, so
        # this legacy entry point resolves paths the same way scan_management
        # does rather than only accepting absolutes.
        folder_path, root_error = resolve_scan_path(
            form.folder_path.data, form.library_root.data, current_app,
        )
        logger.info(f"Scanning folder: {folder_path}")
        if root_error:
            flash(f'Service configuration error: {root_error}', 'error')
            return redirect(url_for('admin2.scan_folder'))

        # Validate folder path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            return render_template('admin/admin_manage_scanjobs.html',
                                  form=form, manual_form=form, csrf_form=csrf_form,
                                  game_names_with_ids=game_names_with_ids,
                                  release_group_form=release_group_form,
                                  scanning_filters=scanning_filters,
                                  allowed_file_types=allowed_file_types)

        # Security validation: ensure the folder path is within allowed directories
        is_safe, error_message = is_safe_path(folder_path, allowed_bases)
        if not is_safe:
            logger.warning(f"Security error: Scan folder path validation failed for {folder_path}: {error_message}")
            flash(f"Access denied: {error_message}", 'error')
            return render_template('admin/admin_manage_scanjobs.html',
                                  form=form, manual_form=form, csrf_form=csrf_form,
                                  game_names_with_ids=game_names_with_ids,
                                  release_group_form=release_group_form,
                                  scanning_filters=scanning_filters,
                                  allowed_file_types=allowed_file_types)

        if os.path.exists(folder_path) and os.access(folder_path, os.R_OK):
            logger.debug("Folder exists and is accessible.")
            insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
            games_with_paths = get_game_names_from_folder(folder_path, insensitive_patterns, sensitive_patterns)
            session['active_tab'] = 'manualScan'
            session['game_paths'] = {game['name']: game['full_path'] for game in games_with_paths}
            game_names_with_ids = [{'name': game['name'], 'id': i} for i, game in enumerate(games_with_paths)]
        else:
            flash("Folder does not exist or cannot be accessed.", "error")
            logger.warning("Folder does not exist or cannot be accessed.")

    return render_template('admin/admin_manage_scanjobs.html',
                          form=form,
                          manual_form=form,
                          csrf_form=csrf_form,
                          game_names_with_ids=game_names_with_ids,
                          release_group_form=release_group_form,
                          scanning_filters=scanning_filters,
                          allowed_file_types=allowed_file_types)


@admin2_bp.route('/cancel_scan_job/<job_id>', methods=['POST'])
@login_required
@admin_required
def cancel_scan_job(job_id):
    job = db.session.get(ScanJob, job_id)
    if job and job.status == 'Running':
        job.is_enabled = False
        job.status = 'Stopping'
        job.error_message = 'Scan is stopping, waiting for threads to complete'
        db.session.commit()
        flash(f"Scan job {job_id} is stopping. Waiting for threads to complete...")
        logger.info(f"Scan job {job_id} is stopping. Waiting for threads to complete...")
    elif job and job.status == 'Queued':
        job.is_enabled = False
        job.status = 'Cancelled'
        job.error_message = 'Queued scan cancelled before start'
        db.session.commit()
        flash(f"Queued scan job {job_id} cancelled.")
        logger.info(f"Queued scan job {job_id} cancelled.")
    else:
        flash('Scan job not found or not in a cancellable state.', 'error')
    return redirect(url_for('admin2.scan_management'))

@admin2_bp.route('/restart_scan_job/<job_id>', methods=['POST'])
@login_required
@admin_required
def restart_scan_job(job_id):
    logger.info(f"Request to restart scan job: {job_id}")
    job = db.session.get(ScanJob, job_id) or abort(404)
    from oneirodex.utils.scan_queue import parse_queue_policy, restart_or_queue_scan

    result = restart_or_queue_scan(
        job.id,
        queue_policy=parse_queue_policy(
            request.form.get('queue_policy'), request.form.get('force_parallel'),
        ),
        allow_force=True,
        app=current_app._get_current_object(),
    )
    flash(result['message'], 'error' if result['status'] == 'rejected' else 'success')
    return redirect(url_for('admin2.scan_management'))


@admin2_bp.route('/delete_scan_job/<job_id>', methods=['POST'])
@login_required
@admin_required
def delete_scan_job(job_id):
    job = db.session.get(ScanJob, job_id) or abort(404)
    db.session.delete(job)
    db.session.commit()
    flash('Scan job deleted successfully.', 'success')
    return redirect(url_for('admin2.scan_management'))

@admin2_bp.route('/clear_all_scan_jobs', methods=['POST'])
@login_required
@admin_required
def clear_all_scan_jobs():
    """Delete terminal jobs only (keeps Running/Stopping/Queued/Scheduled).

    Recurring schedules live as Scheduled/Queued rows; wiping them on
    "clear all" silently disarmed interval/cron arms. Use status-scoped
    clear for Queued/Scheduled if that is intentional.
    """
    terminal = ('Completed', 'Failed', 'Cancelled')
    result = db.session.execute(
        delete(ScanJob).where(ScanJob.status.in_(terminal))
    )
    db.session.commit()
    flash(
        f'Cleared {result.rowcount} completed/failed/cancelled scan jobs '
        '(Running/Stopping/Queued/Scheduled kept).',
        'success',
    )
    return redirect(url_for('admin2.scan_management', active_tab='jobs'))


@admin2_bp.route('/clear_scan_jobs', methods=['POST'])
@login_required
@admin_required
def clear_scan_jobs():
    """Delete jobs matching one terminal status (Completed or Failed)."""
    status = (request.form.get('status') or request.args.get('status') or '').strip()
    allowed = {'Completed', 'Failed', 'Cancelled'}
    if status not in allowed:
        flash('Unknown job status to clear.', 'error')
        return redirect(url_for('admin2.scan_management', active_tab='jobs'))
    result = db.session.execute(delete(ScanJob).where(ScanJob.status == status))
    db.session.commit()
    flash(f'Cleared {result.rowcount} {status} scan jobs.', 'success')
    return redirect(url_for('admin2.scan_management', active_tab='jobs'))
