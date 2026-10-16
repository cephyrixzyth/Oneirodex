"""Admin UI for ROM reference set (DAT) uploads."""

from __future__ import annotations

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required

from oneirodex.platform import LibraryPlatform, NATIVE_PC_PLATFORMS
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex import db
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.functions import igdb_platform_id_for
from oneirodex.utils.set_completion import (
    REGION_PREF_ORDER,
    VALID_SOURCES,
    delete_reference_set,
    list_reference_sets,
    upsert_reference_set,
    normalize_region,
    validate_library_platform,
    ReferenceSetReplacementConflict,
)

from . import admin2_bp

MAX_DAT_BYTES = 32 * 1024 * 1024


@admin2_bp.route('/api/admin/reference-sets', methods=['GET', 'POST'])
@login_required
@admin_required
def reference_sets_api():
    if request.method == 'GET':
        try:
            platforms = sorted([{'id': p.name, 'label': p.value} for p in LibraryPlatform], key=lambda row: row['label'].lower())
            response = current_app.make_response(api_ok({
                'sets': list_reference_sets(), 'platforms': platforms,
                'catalog_platforms': [p for p in platforms if p['id'] not in NATIVE_PC_PLATFORMS and igdb_platform_id_for(p['id']) is not None],
                'regions': list(REGION_PREF_ORDER), 'sources': sorted(VALID_SOURCES),
                'max_dat_bytes': MAX_DAT_BYTES,
            }))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except Exception:
            return api_error('Could not load reference sets', code='internal')
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return api_error('DAT file required', code='bad_request')
    platform = (request.form.get('library_platform') or '').strip()
    region = (request.form.get('region') or 'USA').strip()
    source = (request.form.get('source') or 'nointro').strip()
    if any(len(value) > 64 or any(ord(c) < 32 for c in value) for value in (platform, region, source)):
        return api_error('Invalid platform, region, or source', code='bad_request')
    raw = upload.read(MAX_DAT_BYTES + 1)
    if len(raw) > MAX_DAT_BYTES:
        return api_error('DAT too large (max 32 MiB)', code='bad_request')
    if not raw:
        return api_error('Empty DAT file', code='bad_request')
    try:
        platform = validate_library_platform(platform)
        existing = next((row for row in list_reference_sets() if row['library_platform'] == platform and row['region'] == normalize_region(region)), None)
        if existing and request.form.get('replace') != 'true':
            return api_error('A set already exists for this platform and region. Confirm replacement before uploading.', code='conflict')
        ref = upsert_reference_set(library_platform=platform, region=region, source=source, dat_bytes=raw, uploader_id=getattr(current_user, 'id', None), allow_replace=request.form.get('replace') == 'true')
    except ReferenceSetReplacementConflict:
        db.session.rollback()
        return api_error('A set already exists for this platform and region. Confirm replacement before uploading.', code='conflict')
    except ValueError:
        db.session.rollback()
        return api_error('Could not parse the DAT. Check its contents and selected platform.', code='bad_request')
    except Exception:
        db.session.rollback()
        return api_error('Could not upload the reference set', code='internal')
    log_system_event(f'Reference set uploaded: {ref.library_platform}/{ref.region} ({ref.entry_count} entries)', event_type='admin', event_level='information')
    return api_ok({'reference_set': ref.to_dict()}, status=201)


@admin2_bp.route('/api/admin/reference-sets/<int:set_id>', methods=['DELETE'])
@login_required
@admin_required
def reference_set_delete_api(set_id):
    try:
        if not delete_reference_set(set_id):
            return api_error('Reference set not found', code='not_found')
    except Exception:
        db.session.rollback()
        return api_error('Could not delete the reference set', code='internal')
    log_system_event(f'Reference set deleted: id={set_id}', event_type='admin', event_level='information')
    return api_ok({'id': set_id})


@admin2_bp.route('/admin/reference_sets', methods=['GET', 'POST'])
@login_required
@admin_required
def reference_sets_admin():
    if request.method == 'POST':
        action = (request.form.get('action') or 'upload').strip()
        if action == 'delete':
            try:
                set_id = int(request.form.get('set_id') or '0')
            except ValueError:
                set_id = 0
            if set_id and delete_reference_set(set_id):
                flash('Reference set deleted', 'success')
            else:
                flash('Reference set not found', 'error')
            return redirect(url_for('admin2.reference_sets_admin'))

        upload = request.files.get('file')
        platform = (request.form.get('library_platform') or '').strip()
        region = (request.form.get('region') or 'USA').strip()
        source = (request.form.get('source') or 'nointro').strip()
        if not upload or not upload.filename:
            flash('DAT file required', 'error')
            return redirect(url_for('admin2.reference_sets_admin'))
        raw = upload.read(MAX_DAT_BYTES + 1)
        if len(raw) > MAX_DAT_BYTES:
            flash('DAT too large (max 32 MiB)', 'error')
            return redirect(url_for('admin2.reference_sets_admin'))
        try:
            ref = upsert_reference_set(
                library_platform=platform,
                region=region,
                source=source,
                dat_bytes=raw,
                uploader_id=getattr(current_user, 'id', None),
            )
            flash(
                f'Uploaded {ref.name}: {ref.entry_count} entries for '
                f'{ref.library_platform}/{ref.region}',
                'success',
            )
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception as exc:  # noqa: BLE001
            flash(f'Failed to parse DAT: {exc}', 'error')
        return redirect(url_for('admin2.reference_sets_admin'))

    return render_admin_spa(title='Reference sets · Oneirodex Admin')
