from oneirodex.utils.member_spa import render_member_spa
from flask import redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from oneirodex.forms import CsrfProtectForm
from oneirodex.models import DownloadRequest
from sqlalchemy import select
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.functions import format_size
from oneirodex.utils.event_logging import log_system_event
from . import download_bp
from oneirodex import db

@download_bp.route('/downloads')
@login_required
def downloads():
    return render_member_spa()


@download_bp.route('/delete_download/<int:download_id>', methods=['POST'])
@login_required
def delete_download(download_id):
    # Validate download_id parameter
    try:
        download_id = int(download_id)
    except (ValueError, TypeError):
        log_system_event(f"Invalid download_id parameter: {download_id}",
                        event_type='security', event_level='warning')
        abort(400)

    download_request = db.session.execute(select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)).scalars().first()

    if not download_request:
        log_system_event(f"Unauthorized download deletion attempt: user {current_user.id} tried to delete download {download_id}",
                        event_type='security', event_level='warning')
        abort(404)

    # Delete download request (no physical files to clean up with new streaming approach)
    flash('Download request removed.', 'info')

    db.session.delete(download_request)
    db.session.commit()

    log_system_event(f"User {current_user.id} deleted download request {download_id}",
                   event_type='audit', event_level='information')

    return redirect(url_for('download.downloads'))

@download_bp.route('/check_download_status/<download_id>')
@login_required
def check_download_status(download_id):
    # Validate download_id parameter
    try:
        download_id = int(download_id)
    except (ValueError, TypeError):
        log_system_event(f"Invalid download_id parameter in status check: {download_id}",
                        event_type='security', event_level='warning')
        return api_error(
            'Invalid download ID',
            code='bad_request',
            body_status='invalid',
            downloadId=download_id,
            found=False,
        )

    download_request = db.session.execute(select(DownloadRequest).filter_by(id=download_id, user_id=current_user.id)).scalars().first()

    if download_request:
        return api_ok({
            'status': download_request.status,
            'downloadId': download_request.id,
            'found': True,
        })

    # Log unauthorized access attempt
    log_system_event(f"Unauthorized download status check: user {current_user.id} tried to check download {download_id}",
                    event_type='security', event_level='warning')

    return api_error(
        'Download request not found',
        code='not_found',
        body_status='not_found',
        downloadId=download_id,
        found=False,
    )
