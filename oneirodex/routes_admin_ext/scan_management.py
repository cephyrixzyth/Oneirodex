"""Admin: the scan-management page and its ``/admin/`` alias.

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1f, which retired the
``'main'`` blueprint). The view renders / redirects only -- no JSON envelope --
and shares the ``admin/admin_manage_scanjobs.html`` template with the scan-job
lifecycle routes in ``scan_jobs.py``.

The blueprint is ``admin2_bp`` (registered with **no** ``url_prefix``), so the
URL rules (``/scan_management`` GET/POST, ``/admin/scan_management`` GET) are
byte-identical to when they lived on the ``main`` blueprint; only the endpoint
names change (``main.scan_management`` -> ``admin2.scan_management``,
``main.scan_management_admin_alias`` -> ``admin2.scan_management_admin_alias``).
"""

from flask import (
    flash, redirect, request, session, url_for,
)
from flask_login import login_required
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.forms import (
    AutoScanForm,
    CsrfProtectForm,
    ReleaseGroupForm,
    ScanFolderForm,
    UpdateUnmatchedFolderForm,
)
from oneirodex.models import (
    AllowedFileType,
    Game,
    Library,
    ReleaseGroup,
    ScanJob,
)
from oneirodex.utils.auth import admin_required
from oneirodex.utils.functions import (
    normalize_case_sensitive,
)
from oneirodex.utils.services.scan_orchestration import (
    handle_auto_scan,
    handle_manual_scan,
)
from oneirodex.utils.unmatched import handle_delete_unmatched

from oneirodex.utils.admin_spa import render_admin_spa

from . import admin2_bp


@admin2_bp.route('/admin/scan_management', methods=['GET'])
@login_required
@admin_required
def scan_management_admin_alias():
    """`/admin/scan_management` -> `/scan_management`, query string intact.

    Every other admin destination lives under `/admin/*`, but the rail links
    the image queue at `/scan_management?active_tab=image_queue`, so an
    operator who reasons from the pattern (or edits a URL) lands on a 404. The
    view itself is unchanged and already carries `@admin_required`, so this is
    a naming inconsistency rather than an access one -- the alias just makes the
    namespace hold. `request.args` is forwarded so `?active_tab=` survives.
    """
    return redirect(url_for('admin2.scan_management', **request.args.to_dict(flat=True)))


@admin2_bp.route('/admin/scan-controls', methods=['GET'])
@login_required
@admin_required
def scan_controls_classic_alias():
    """Keep the native Auto Scan destination useful when the pilot is off."""
    return redirect(url_for('admin2.scan_management', active_tab='auto'))


@admin2_bp.route('/admin/unmatched', methods=['GET'])
@login_required
@admin_required
def unmatched_admin_alias():
    """Keep the old server-rendered route usable while the native pilot is off."""
    return redirect(url_for('admin2.scan_management', active_tab='unmatched'))


@admin2_bp.route('/scan_management', methods=['GET', 'POST'])
@login_required
@admin_required
def scan_management():
    if request.method == 'GET':
        return render_admin_spa(title='Libraries & scans · Oneirodex Admin')
    auto_form = AutoScanForm()
    manual_form = ScanFolderForm()
    release_group_form = ReleaseGroupForm()

    libraries = db.session.execute(select(Library)).scalars().all()
    auto_form.library_uuid.choices = [(str(lib.uuid), lib.name) for lib in libraries]
    manual_form.library_uuid.choices = [(str(lib.uuid), lib.name) for lib in libraries]

    # Only pre-select from query param on GET, not POST
    # This prevents overwriting form data during POST submission
    selected_library_uuid = None
    if request.method == 'GET':
        selected_library_uuid = request.args.get('library_uuid')
        if selected_library_uuid:
            auto_form.library_uuid.data = selected_library_uuid
            manual_form.library_uuid.data = selected_library_uuid

    jobs = db.session.execute(select(ScanJob).order_by(ScanJob.last_run.desc())).scalars().all()
    csrf_form = CsrfProtectForm()
    # Unmatched rows load via /api/unmatched_folders — do not hydrate the full
    # list on every Scan management page (that alone made Unmatched feel stuck).
    unmatched_folders_with_platform = []
    unmatched_form = UpdateUnmatchedFolderForm()

    game_count = db.session.scalar(select(func.count(Game.id)))  # Fetch the game count here

    # Data for new tabs
    scanning_filters = db.session.execute(select(ReleaseGroup).order_by(ReleaseGroup.filter_pattern.asc())).scalars().all()
    allowed_file_types = db.session.execute(select(AllowedFileType).order_by(AllowedFileType.value.asc())).scalars().all()

    if request.method == 'POST':
        submit_action = request.form.get('submit')
        if submit_action == 'AutoScan':
            return handle_auto_scan(auto_form)
        elif submit_action == 'ManualScan':
            return handle_manual_scan(manual_form)
        elif submit_action == 'DeleteAllUnmatched':
            return handle_delete_unmatched(all=True)
        elif submit_action == 'DeleteOnlyUnmatched':
            return handle_delete_unmatched(all=False)
        elif submit_action == 'AddReleaseGroup' and release_group_form.validate_on_submit():
            # Canonical String column form ('yes'|'no') -- matches edit_filters.
            new_group = ReleaseGroup(
                filter_pattern=release_group_form.filter_pattern.data,
                case_sensitive=normalize_case_sensitive(release_group_form.case_sensitive.data),
            )
            db.session.add(new_group)
            db.session.commit()
            flash('New scanning filter added.', 'success')
            return redirect(url_for('admin2.scan_management', active_tab='scan_filters'))
        elif submit_action == 'DeleteReleaseGroup':
            # Handle deleting scanning filter
            filter_id = request.form.get('filter_id')
            if filter_id:
                group_to_delete = db.session.get(ReleaseGroup, filter_id)
                if group_to_delete:
                    db.session.delete(group_to_delete)
                    db.session.commit()
                    flash('Scanning filter removed.', 'success')
                else:
                    flash('Filter not found.', 'error')
            return redirect(url_for('admin2.scan_management', active_tab='scan_filters'))
        else:
            flash("Unrecognized action.", "error")
            return redirect(url_for('admin2.scan_management'))

    game_paths_dict = session.get('game_paths', {})
    game_names_with_ids = [{'name': name, 'full_path': path} for name, path in game_paths_dict.items()]
    # Handle active_tab from URL parameter, default to 'auto'
    active_tab = request.args.get('active_tab', 'auto')
    # Libraries is its own page (`/libraries`). The old merged tab document
    # stacked every pane under the libraries table — do not re-enter that mode.
    if active_tab == 'libraries':
        return redirect(url_for('library.libraries'))

    return render_admin_spa(title='Libraries & scans · Oneirodex Admin')
