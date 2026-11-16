import re

from flask import redirect, url_for, flash, abort, request, current_app
from flask_login import login_required
from oneirodex.utils.auth import admin_required
from oneirodex.models import ReleaseGroup
from oneirodex import db
from sqlalchemy import select
from oneirodex.forms import ReleaseGroupForm
from oneirodex.utils.functions import normalize_case_sensitive
from . import admin2_bp
from oneirodex.utils.api_response import api_ok, api_error
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.schemas.admin_filters import ScanFilterBody
from oneirodex.utils.validation import validate_body


def _filter_row(group):
    raw = (group.filter_pattern or '').strip()
    lowered = raw.lower()
    kind = 'dir' if lowered.startswith('dir:') else 'regex' if lowered.startswith('re:') else 'name'
    return {
        'id': group.id,
        'filter_pattern': group.filter_pattern or '',
        'kind': kind,
        'case_sensitive': normalize_case_sensitive(group.case_sensitive),
    }


def _invalid_scan_filter_body(_exc):
    return api_error('Send a filter object.', code='bad_request')


@admin2_bp.route('/api/admin/scan-filters', methods=['GET', 'POST'])
@login_required
@admin_required
@validate_body(ScanFilterBody, methods={'POST'}, on_error=_invalid_scan_filter_body)
def scan_filters_api(body: ScanFilterBody | None = None):
    if request.method == 'GET':
        rows = db.session.execute(
            select(ReleaseGroup).order_by(ReleaseGroup.filter_pattern.asc(), ReleaseGroup.id.asc())
        ).scalars().all()
        response = current_app.make_response(api_ok({'filters': [_filter_row(row) for row in rows]}))
        response.headers['Cache-Control'] = 'no-store'
        return response

    payload = body.model_dump()
    kind = str(payload.get('kind') or 'name').strip().lower()
    raw_pattern = payload.get('pattern')
    if not isinstance(raw_pattern, str):
        return api_error('Pattern must be text.', code='bad_request')
    pattern = raw_pattern.strip()
    if kind not in {'name', 'dir', 'regex'}:
        return api_error('Choose a valid filter type.', code='bad_request')
    if not pattern or len(pattern) > 200:
        return api_error('Pattern must be between 1 and 200 characters.', code='bad_request')
    if kind == 'name' and (pattern.lower().startswith(('dir:', 're:'))):
        return api_error('Name tags cannot use a reserved filter prefix.', code='bad_request')
    if kind in {'dir', 'regex'} and pattern.lower().startswith(('dir:', 're:')):
        return api_error('Enter the pattern without its type prefix.', code='bad_request')
    if kind == 'regex':
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error:
            return api_error('Enter a valid regular expression.', code='bad_request')
    case_sensitive = payload.get('case_sensitive', False)
    if kind != 'name':
        case_sensitive = False
    elif not isinstance(case_sensitive, bool):
        return api_error('Choose whether the name tag is case sensitive.', code='bad_request')
    row = ReleaseGroup(
        filter_pattern=(f'dir:{pattern}' if kind == 'dir' else f're:{pattern}' if kind == 'regex' else pattern),
        case_sensitive='yes' if case_sensitive else 'no',
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Could not add admin scan filter')
        return api_error('Could not add scanning filter.', code='internal')
    return api_ok({'filter': _filter_row(row), 'message': 'Scanning filter added.'}, status=201)


@admin2_bp.route('/api/admin/scan-filters/<int:filter_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_scan_filter_api(filter_id):
    row = db.session.get(ReleaseGroup, filter_id)
    if row is None:
        return api_error('Scanning filter not found.', code='not_found')
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Could not delete admin scan filter')
        return api_error('Could not remove scanning filter.', code='internal')
    return api_ok({'message': 'Scanning filter removed.'})

@admin2_bp.route('/admin/edit_filters', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_filters():
    if request.method == 'GET':
        return render_admin_spa(title='Release filters · Oneirodex Admin')

    form = ReleaseGroupForm()
    if form.validate_on_submit():
        new_group = ReleaseGroup(
            filter_pattern=form.filter_pattern.data,
            case_sensitive=normalize_case_sensitive(form.case_sensitive.data),
        )
        db.session.add(new_group)
        db.session.commit()
        flash('New scanning filter added.')
        return redirect(url_for('admin2.edit_filters'))

    errors = [*form.filter_pattern.errors, *form.case_sensitive.errors]
    if not errors:
        errors = ['Enter a valid scanning filter.']
    for error in errors:
        flash(error, 'danger')
    return redirect(url_for('admin2.edit_filters'))

@admin2_bp.route('/delete_filter/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def delete_filter(id):
    if request.method == 'GET':
        flash('Open Scan Filters and confirm removal there.', 'warning')
        return redirect(url_for('admin2.edit_filters'))

    group_to_delete = db.session.get(ReleaseGroup, id) or abort(404)
    db.session.delete(group_to_delete)
    db.session.commit()
    flash('Scanning filter removed.')
    return redirect(url_for('admin2.edit_filters'))
