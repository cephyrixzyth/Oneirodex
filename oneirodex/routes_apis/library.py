# /oneirodex/routes_apis/library.py
from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, jsonify, request, url_for
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import Game, IgdbPlatformRelease, Library, ReferenceSet, UnmatchedFolder
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.auth import admin_required
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.library_acl import filter_libraries, user_can_access_library
from oneirodex.utils.platform_release_projection import platform_release_totals
from oneirodex.utils.library_batch import (
    LIBRARY_BATCH_DELETE_CAP,
    LIBRARY_BATCH_UUID_CAP,
    parse_bool_flag,
    parse_confirm_names,
    parse_library_uuids,
    require_confirm_or_force,
)
from oneirodex.utils.library_watch import (
    is_library_watch_enabled,
    library_watch_effective,
)
from oneirodex.utils.rbac import is_librarian
from sqlalchemy import func, select
from uuid import uuid4
import os
from PIL import Image as PILImage, UnidentifiedImageError
from . import apis_bp

_DEFAULT_LIBRARY_IMAGE = 'newstyle/default_library.jpg'
_LIBRARY_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
_LIBRARY_IMAGE_MAX_BYTES = 10 * 1024 * 1024


@apis_bp.route('/admin/libraries', methods=['POST'])
@login_required
@admin_required
def create_library():
    """Create library metadata for the React form; the client queues its first scan."""
    data = request.form if request.mimetype == 'multipart/form-data' else (request.get_json(silent=True) or {})
    name = str(data.get('name') or '').strip()
    platform_key = str(data.get('platform') or '').strip()
    try:
        depth = int(data.get('scan_depth', 1))
        watch_enabled = _parse_watch_enabled(data.get('watch_enabled', 'default'))
    except (TypeError, ValueError):
        return api_error('Choose a supported scan depth and watch setting.', code='bad_request')
    if not name or len(name) > 255:
        return api_error('Library name is required and must be 255 characters or fewer.', code='bad_request')
    if depth not in (1, 2):
        return api_error('Scan depth must be 1 or 2.', code='bad_request')
    try:
        platform = LibraryPlatform[platform_key]
    except KeyError:
        return api_error('Choose a supported platform.', code='bad_request')

    image_url = url_for('static', filename=_DEFAULT_LIBRARY_IMAGE)
    saved_image_path = None
    image = request.files.get('image')
    if image and image.filename:
        extension = image.filename.rsplit('.', 1)[-1].lower() if '.' in image.filename else ''
        if extension not in _LIBRARY_IMAGE_EXTENSIONS:
            return api_error('Choose a JPG, PNG, GIF, or WebP library image.', code='bad_request')
        image.stream.seek(0, os.SEEK_END)
        image_size = image.stream.tell()
        image.stream.seek(0)
        if image_size > _LIBRARY_IMAGE_MAX_BYTES:
            return api_error('Library image must be 10 MB or smaller.', code='bad_request')
        try:
            with PILImage.open(image.stream) as opened:
                if opened.width * opened.height > 80_000_000:
                    return api_error('Library image dimensions are too large.', code='bad_request')
                converted = opened.convert('RGBA')
                if converted.width > 1024 or converted.height > 1024:
                    converted.thumbnail((1024, 1024), PILImage.LANCZOS)
                image_name = f'{uuid4()}.png'
                image_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images')
                os.makedirs(image_dir, exist_ok=True)
                saved_image_path = os.path.join(image_dir, image_name)
                converted.save(saved_image_path, 'PNG')
                image_url = url_for('static', filename=f'library/images/{image_name}')
        except (UnidentifiedImageError, OSError, ValueError):
            if saved_image_path and os.path.exists(saved_image_path):
                os.remove(saved_image_path)
            return api_error('The uploaded library image could not be read.', code='bad_request')

    library = Library(
        uuid=str(uuid4()),
        name=name,
        platform=platform,
        scan_depth=depth,
        watch_enabled=watch_enabled,
        image_url=image_url,
    )
    db.session.add(library)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if saved_image_path and os.path.exists(saved_image_path):
            os.remove(saved_image_path)
        return api_error('Library could not be created.', code='internal', status=500)
    log_system_event(
        f'Library created: {library.name}',
        event_type='library',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )
    return api_ok({'library_uuid': library.uuid, 'name': library.name})


def _resolve_library_image_url(raw: str | None) -> str:
    """Return a browser-safe library thumb URL (never an empty/broken path)."""
    text = (raw or '').strip()
    if not text:
        return url_for('static', filename=_DEFAULT_LIBRARY_IMAGE)
    # Already a site- or absolute URL.
    if text.startswith('/') or text.startswith('http://') or text.startswith('https://'):
        return text
    # Bare filename under library/images (common after stock picker).
    if '/' not in text and '\\' not in text:
        return url_for('static', filename=f'library/images/{text}')
    return url_for('static', filename=text.lstrip('/'))


def _parse_watch_enabled(raw):
    """Parse API/form watch_enabled → True | False | None (follow global)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ('', 'null', 'none', 'default', 'follow', 'global'):
        return None
    if text in ('1', 'true', 'yes', 'on', 'enabled'):
        return True
    if text in ('0', 'false', 'no', 'off', 'disabled'):
        return False
    raise ValueError(f'Invalid watch_enabled: {raw!r}')


def _library_watch_payload(library: Library) -> dict:
    flag = getattr(library, 'watch_enabled', None)
    return {
        'watch_enabled': flag,
        'watch_effective': library_watch_effective(library),
        'watch_global_enabled': is_library_watch_enabled(),
    }


def _parse_group_name(raw):
    """Strip and cap a library group label. Empty / None clears the group."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[:80]


def _platform_release_totals() -> dict[str, int]:
    """Released-set size per LibraryPlatform name.

    Priority: DAT ``entry_count`` > unique IGDB licensed-catalog titles >
    built-in ROM-set estimates. Platforms with none of those stay absent so
    the UI leaves those game counts uncoloured instead of treating them as empty.
    """
    return platform_release_totals(db.session, IgdbPlatformRelease, ReferenceSet)


def _library_public_fields(library: Library) -> dict:
    group = getattr(library, 'group_name', None)
    return {
        'uuid': library.uuid,
        'name': library.name,
        'platform': library.platform.name if library.platform else None,
        'scan_depth': int(getattr(library, 'scan_depth', 1) or 1),
        'last_scan_folder': getattr(library, 'last_scan_folder', None),
        'group_name': (group or '').strip() or None,
        'image_url': _resolve_library_image_url(getattr(library, 'image_url', None)),
        **_library_watch_payload(library),
    }


@apis_bp.route('/admin/libraries/<string:library_uuid>', methods=['GET', 'PUT'])
@login_required
@admin_required
def admin_library_detail(library_uuid):
    """Read or update one library for the native admin editor."""
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        return api_error('Library not found.', code='not_found', status=404)
    if request.method == 'GET':
        return api_ok(_library_public_fields(library))

    data = request.form if request.mimetype == 'multipart/form-data' else (request.get_json(silent=True) or {})
    if not isinstance(data, dict) and request.mimetype != 'multipart/form-data':
        return api_error('Provide valid library fields.', code='bad_request')
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 255:
        return api_error('Library name is required and must be 255 characters or fewer.', code='bad_request')
    try:
        platform = LibraryPlatform[str(data.get('platform') or '').strip()]
        depth = int(data.get('scan_depth', 1))
        watch_enabled = _parse_watch_enabled(data.get('watch_enabled', 'default'))
    except (KeyError, TypeError, ValueError):
        return api_error('Choose a supported platform, scan depth, and watch setting.', code='bad_request')
    if depth not in (1, 2):
        return api_error('Scan depth must be 1 or 2.', code='bad_request')

    image = request.files.get('image')
    saved_image_path = None
    if image and image.filename:
        extension = image.filename.rsplit('.', 1)[-1].lower() if '.' in image.filename else ''
        if extension not in _LIBRARY_IMAGE_EXTENSIONS:
            return api_error('Choose a JPG, PNG, GIF, or WebP library image.', code='bad_request')
        image.stream.seek(0, os.SEEK_END)
        image_size = image.stream.tell()
        image.stream.seek(0)
        if image_size > _LIBRARY_IMAGE_MAX_BYTES:
            return api_error('Library image must be 10 MB or smaller.', code='bad_request')
        try:
            with PILImage.open(image.stream) as opened:
                if opened.width * opened.height > 80_000_000:
                    return api_error('Library image dimensions are too large.', code='bad_request')
                converted = opened.convert('RGBA')
                if converted.width > 1024 or converted.height > 1024:
                    converted.thumbnail((1024, 1024), PILImage.LANCZOS)
                image_name = f'{uuid4()}.png'
                image_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images')
                os.makedirs(image_dir, exist_ok=True)
                saved_image_path = os.path.join(image_dir, image_name)
                converted.save(saved_image_path, 'PNG')
                image_url = url_for('static', filename=f'library/images/{image_name}')
        except (UnidentifiedImageError, OSError, ValueError):
            if saved_image_path and os.path.exists(saved_image_path):
                os.remove(saved_image_path)
            return api_error('The uploaded library image could not be read.', code='bad_request')
        library.image_url = image_url

    library.name = name
    library.platform = platform
    library.scan_depth = depth
    library.watch_enabled = watch_enabled
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if saved_image_path and os.path.exists(saved_image_path):
            os.remove(saved_image_path)
        return api_error('Library could not be saved.', code='internal', status=500)
    log_system_event(
        f'Library updated: {library.name}', event_type='library', event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )
    return api_ok(_library_public_fields(library))


def _rejected_body(payload: dict, http_status: int):
    """Turn a batch-refusal dict into the shared envelope.

    Classic scan/library JS still reads `status: 'rejected'` and, for typed
    confirm, a machine token in `error` with the sentence in `message`.
    """
    message = payload.get('message') or payload.get('error') or 'Rejected'
    token = payload.get('error')
    extras = {
        key: value for key, value in payload.items()
        if key not in ('ok', 'error', 'message', 'status', 'success', 'error_code')
    }
    if token and token != message:
        extras['body_error'] = token
    code = {
        400: 'bad_request',
        403: 'forbidden',
        404: 'not_found',
        409: 'conflict',
        500: 'internal',
    }.get(http_status, 'bad_request')
    return api_error(
        message,
        code=code,
        status=http_status,
        body_status=payload.get('status', 'rejected'),
        **extras,
    )


def _cap_error(cap: int):
    return api_error(
        f'library_uuids cap is {cap}',
        code='bad_request',
        body_status='rejected',
        cap=cap,
    )


def _start_library_delete_job(library: Library) -> str:
    """Enqueue background library deletion; returns job_id."""
    from oneirodex.utils.library_deletion import start_library_delete_job
    from oneirodex.routes_admin_ext.library_delete import (
        delete_library_background,
        deletion_progress,
    )

    return start_library_delete_job(
        library, worker=delete_library_background, progress=deletion_progress,
    )


@apis_bp.route('/get_libraries')
@login_required
def get_libraries():
    # Direct query to the Library model, ordered alphabetically by name
    libraries_query = filter_libraries(
        db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all(),
        current_user,
    )
    count_rows = db.session.execute(
        select(Game.library_uuid, func.count(Game.id)).group_by(Game.library_uuid)
    ).all()
    game_counts = {uuid: int(n or 0) for uuid, n in count_rows}
    unmatched_rows = db.session.execute(
        select(UnmatchedFolder.library_uuid, func.count(UnmatchedFolder.id))
        .where(UnmatchedFolder.status.in_(('Pending', 'Unmatched')))
        .group_by(UnmatchedFolder.library_uuid)
    ).all()
    unmatched_counts = {uuid: int(n or 0) for uuid, n in unmatched_rows if uuid}
    release_totals = _platform_release_totals()
    libraries = [
        {
            'uuid': lib.uuid,
            'name': lib.name,
            'platform': lib.platform.value if lib.platform else '',
            'platform_key': lib.platform.name if lib.platform else '',
            'game_count': game_counts.get(lib.uuid, 0),
            'unmatched_count': unmatched_counts.get(lib.uuid, 0),
            'platform_total': release_totals.get(
                lib.platform.name if lib.platform else '',
            ),
            'group_name': (getattr(lib, 'group_name', None) or '').strip() or None,
            'image_url': _resolve_library_image_url(lib.image_url),
            # The admin Scan button posts no folder and lets the scan route fall
            # back to this. Sending it lets the button say *why* it is disabled
            # instead of posting a request the route is bound to reject.
            'last_scan_folder': lib.last_scan_folder or '',
            **_library_watch_payload(lib),
        } for lib in libraries_query
    ]
    return jsonify(libraries)

@apis_bp.route('/reorder_libraries', methods=['POST'])
@login_required
@admin_required
def reorder_libraries():
    try:
        new_order = request.json.get('order', [])
        for index, library_uuid in enumerate(new_order):
            library = db.session.get(Library, library_uuid)
            if library:
                library.display_order = index
        db.session.commit()
        # admin_manage_libs.js reads `data.status === 'success'` here.
        return api_ok({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning('library update failed: %s', e)
        return api_error(
            'Could not update the library',
            code='internal',
            body_status='error',
        )

@apis_bp.route('/library/<string:library_uuid>', methods=['GET'])
@login_required
def get_library(library_uuid):
    """Return information about a specific library"""
    if not user_can_access_library(current_user, library_uuid):
        return api_error('Forbidden', code='forbidden')
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        return api_error('Library not found', code='not_found')
        
    return jsonify(_library_public_fields(library))


@apis_bp.route('/library/<string:library_uuid>/watch', methods=['GET', 'PUT'])
@login_required
def library_watch(library_uuid):
    """Get or set per-library incremental watch intent under ``ONEIRODEX_LIBRARY_WATCH``.

    PUT body: ``{"watch_enabled": true|false|null}``
      - null / omit on GET-only → follow global when env on
      - false → opt-out even when ``ONEIRODEX_LIBRARY_WATCH=1``
      - true → prefer watch (still requires env master switch)

    Librarian or admin required for PUT.
    """
    if not user_can_access_library(current_user, library_uuid):
        return api_error('Forbidden', code='forbidden')
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        return api_error('Library not found', code='not_found')

    if request.method == 'GET':
        return jsonify({
            'uuid': library.uuid,
            'name': library.name,
            **_library_watch_payload(library),
        })

    if not is_librarian(current_user):
        return api_error('Librarian or admin required', code='forbidden')

    data = request.get_json(silent=True) or {}
    if 'watch_enabled' not in data:
        return api_error('watch_enabled required (true|false|null)', code='bad_request')
    try:
        library.watch_enabled = _parse_watch_enabled(data.get('watch_enabled'))
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    db.session.commit()
    return jsonify({
        'uuid': library.uuid,
        'name': library.name,
        **_library_watch_payload(library),
    })


@apis_bp.route('/admin/libraries/batch/scan', methods=['POST'])
@login_required
@admin_required
def batch_scan_libraries():
    """Multi-select scan start/queue for libraries (W22-1 / UID-003).

    Body:
      library_uuids: string[] (required; alias ``uuids``; or singular ``library_uuid``)
      folder / folders: optional shared folder or ``{uuid: path}`` map
      scan_mode, remove_missing, download_missing_images, force_updates_extras
      force_parallel / queue_policy — same as single ``/api/admin/libraries/scan``

    Partial success. Cap ``LIBRARY_BATCH_UUID_CAP``.
    """
    from oneirodex.utils.scan_queue import (
        FORCE_PARALLEL_RISK,
        parse_force_parallel,
        parse_queue_policy,
        start_or_queue_scan,
    )

    data = request.get_json(silent=True) or {}
    uuids, err = parse_library_uuids(data)
    if err:
        payload, status = err
        return _rejected_body(payload, status)
    if len(uuids) > LIBRARY_BATCH_UUID_CAP:
        return _cap_error(LIBRARY_BATCH_UUID_CAP)

    folders_map = data.get('folders') if isinstance(data.get('folders'), dict) else {}
    shared_folder = data.get('folder')
    scan_mode = data.get('scan_mode') or 'folders'
    force_raw = data.get('force_parallel')
    policy_raw = data.get('queue_policy')
    queue_policy = parse_queue_policy(policy_raw, force_parallel=force_raw)

    def _bool(key, default=False):
        return parse_bool_flag(data.get(key), default=default)

    results = []
    started = 0
    queued = 0
    skipped = 0
    failed = 0
    for library_uuid in uuids:
        library = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()
        if not library:
            results.append({
                'uuid': library_uuid,
                'ok': False,
                'error': 'not_found',
                'status': 'rejected',
            })
            failed += 1
            continue
        folder = (
            folders_map.get(library_uuid)
            or shared_folder
            or library.last_scan_folder
        )
        if not folder:
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': 'no_scan_folder',
                'status': 'skipped',
                'message': (
                    'No folder provided and library has no last_scan_folder. '
                    'Run one Auto Scan first or pass folder/folders.'
                ),
            })
            skipped += 1
            continue
        try:
            result = start_or_queue_scan(
                folder_path=folder,
                library_uuid=library_uuid,
                scan_mode=scan_mode,
                remove_missing=_bool('remove_missing'),
                download_missing_images=_bool('download_missing_images'),
                force_updates_extras_scan=_bool('force_updates_extras'),
                queue_policy=queue_policy,
                allow_force=True,
                app=current_app._get_current_object(),
            )
            row = {
                'uuid': library_uuid,
                'name': library.name,
                'ok': result.get('status') in ('started', 'queued'),
                'status': result.get('status'),
                'job_id': result.get('job_id'),
                'position': result.get('position'),
                'message': result.get('message'),
                'coalesced': result.get('coalesced'),
            }
            if result.get('status') == 'started' and parse_force_parallel(force_raw):
                row['risk'] = FORCE_PARALLEL_RISK
            if result.get('status') == 'started':
                started += 1
            elif result.get('status') == 'queued':
                queued += 1
            else:
                failed += 1
                row['ok'] = False
                row['error'] = result.get('message') or result.get('status') or 'rejected'
            results.append(row)
        except Exception as exc:
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': str(exc),
                'status': 'error',
            })
            failed += 1

    log_system_event(
        (
            f"Batch library scan by {getattr(current_user, 'name', 'admin')}: "
            f"started={started} queued={queued} skipped={skipped} failed={failed}"
        ),
        event_type='library',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )
    return api_ok({
                'started': started,
        'queued': queued,
        'skipped': skipped,
        'failed': failed,
        'count': len(uuids),
        'results': results,
    })


@apis_bp.route('/admin/libraries/batch/edit', methods=['POST'])
@login_required
@admin_required
def batch_edit_libraries():
    """Apply shared field updates to selected libraries (W22-1 / UID-003).

    Body:
      library_uuids: string[] (required)
      scan_depth?: 1|2
      watch_enabled?: true|false|null
      platform?: LibraryPlatform enum name (e.g. PCWIN, N64)
      group_name?: string (empty clears the group)
      Optional ``items``: [{uuid|library_uuid, scan_depth?, watch_enabled?, platform?, group_name?}]
        for per-row overrides (merged over shared fields).

    Does **not** rename (use single edit for name/image). Cap 100. Partial OK.
    """
    data = request.get_json(silent=True) or {}
    uuids, err = parse_library_uuids(data)
    if err:
        payload, status = err
        return _rejected_body(payload, status)
    if len(uuids) > LIBRARY_BATCH_UUID_CAP:
        return _cap_error(LIBRARY_BATCH_UUID_CAP)

    items_by_uuid: dict[str, dict] = {}
    raw_items = data.get('items')
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            key = str(item.get('uuid') or item.get('library_uuid') or '').strip()
            if key:
                items_by_uuid[key] = item

    shared_keys = ('scan_depth', 'watch_enabled', 'platform', 'group_name')
    has_shared = any(k in data for k in shared_keys)
    if not has_shared and not items_by_uuid:
        return api_error(
            'Provide scan_depth and/or watch_enabled and/or platform and/or group_name (or items[])',
            code='bad_request',
            body_status='rejected',
        )

    results = []
    updated = 0
    skipped = 0
    failed = 0

    for library_uuid in uuids:
        library = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()
        if not library:
            results.append({
                'uuid': library_uuid,
                'ok': False,
                'error': 'not_found',
            })
            failed += 1
            continue

        patch = {k: data[k] for k in shared_keys if k in data}
        if library_uuid in items_by_uuid:
            for key in shared_keys:
                if key in items_by_uuid[library_uuid]:
                    patch[key] = items_by_uuid[library_uuid][key]

        if not patch:
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': 'no_fields',
                'status': 'skipped',
            })
            skipped += 1
            continue

        changed = []
        try:
            if 'scan_depth' in patch:
                depth = int(patch['scan_depth'])
                if depth not in (1, 2):
                    raise ValueError('scan_depth must be 1 or 2')
                if int(getattr(library, 'scan_depth', 1) or 1) != depth:
                    library.scan_depth = depth
                    changed.append('scan_depth')
            if 'watch_enabled' in patch:
                new_watch = _parse_watch_enabled(patch['watch_enabled'])
                if getattr(library, 'watch_enabled', None) != new_watch:
                    library.watch_enabled = new_watch
                    changed.append('watch_enabled')
            if 'platform' in patch:
                plat_raw = str(patch['platform'] or '').strip()
                try:
                    new_plat = LibraryPlatform[plat_raw]
                except KeyError:
                    try:
                        new_plat = LibraryPlatform(plat_raw)
                    except ValueError as exc:
                        raise ValueError(f'Invalid platform: {plat_raw}') from exc
                if library.platform != new_plat:
                    library.platform = new_plat
                    changed.append('platform')
            if 'group_name' in patch:
                new_group = _parse_group_name(patch['group_name'])
                current_group = (getattr(library, 'group_name', None) or '').strip() or None
                if current_group != new_group:
                    library.group_name = new_group
                    changed.append('group_name')

            if not changed:
                results.append({
                    'uuid': library_uuid,
                    'name': library.name,
                    'ok': True,
                    'status': 'unchanged',
                    'changed': [],
                    **_library_public_fields(library),
                })
                skipped += 1
                continue

            db.session.commit()
            updated += 1
            results.append({
                'uuid': library_uuid,
                'ok': True,
                'status': 'updated',
                'changed': changed,
                **_library_public_fields(library),
            })
        except ValueError as exc:
            db.session.rollback()
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': str(exc),
            })
            failed += 1
        except Exception as exc:
            db.session.rollback()
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': str(exc),
            })
            failed += 1

    if updated:
        log_system_event(
            (
                f"Batch library edit by {getattr(current_user, 'name', 'admin')}: "
                f"updated={updated} skipped={skipped} failed={failed}"
            ),
            event_type='library',
            event_level='information',
            audit_user=getattr(current_user, 'id', None),
        )

    return api_ok({
                'updated': updated,
        'skipped': skipped,
        'failed': failed,
        'count': len(uuids),
        'results': results,
    })


@apis_bp.route('/admin/libraries/batch/delete', methods=['POST'])
@login_required
@admin_required
def batch_delete_libraries():
    """Multi-select library delete with typed-name confirm or force (W22-1).

    Body:
      library_uuids: string[] (required; cap 50)
      force: bool — when true, skip per-name typing (still admin + CSRF)
      confirm_names: {uuid: exactName} — required when force is false
      confirm_name: string — optional single phrase applied to every uuid
        when confirm_names omits that uuid

    Starts background delete jobs (same as ``/delete_full_library/<uuid>``).
    Progress: ``GET /delete_library_progress/<job_id>`` or
    ``GET /check_deletion_progress/<job_id>``.
    """
    data = request.get_json(silent=True) or {}
    uuids, err = parse_library_uuids(data)
    if err:
        payload, status = err
        return _rejected_body(payload, status)
    if len(uuids) > LIBRARY_BATCH_DELETE_CAP:
        return _cap_error(LIBRARY_BATCH_DELETE_CAP)

    force = parse_bool_flag(
        data.get('force') if 'force' in data else data.get('force_delete'),
        default=False,
    )
    confirm_names = parse_confirm_names(data)
    single_confirm = data.get('confirm_name')
    if single_confirm is not None:
        single_confirm = str(single_confirm)

    if not force and not confirm_names and (
        single_confirm is None or not str(single_confirm).strip()
    ):
        return api_error(
            (
                'Provide confirm_names {uuid: exact library name} for each '
                'selection, or force=true to skip typed confirmation '
                '(admin + CSRF still required).'
            ),
            code='bad_request',
            body_status='rejected',
            body_error='confirm_name_required',
        )

    results = []
    started = 0
    failed = 0
    for library_uuid in uuids:
        library = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()
        if not library:
            results.append({
                'uuid': library_uuid,
                'ok': False,
                'error': 'not_found',
                'status': 'rejected',
            })
            failed += 1
            continue

        confirm_err = require_confirm_or_force(
            library_uuid=library_uuid,
            library_name=library.name,
            force=force,
            confirm_names=confirm_names,
            single_confirm_name=single_confirm,
        )
        if confirm_err:
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': confirm_err,
                'status': 'rejected',
                'expected_name': library.name if confirm_err == 'confirm_name_mismatch' else None,
            })
            failed += 1
            continue

        try:
            job_id = _start_library_delete_job(library)
            started += 1
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': True,
                'status': 'started',
                'job_id': job_id,
                'force': force,
            })
        except Exception as exc:
            results.append({
                'uuid': library_uuid,
                'name': library.name,
                'ok': False,
                'error': str(exc),
                'status': 'error',
            })
            failed += 1

    log_system_event(
        (
            f"Batch library delete by {getattr(current_user, 'name', 'admin')}: "
            f"started={started} failed={failed} force={force}"
        ),
        event_type='library',
        event_level='warning' if force else 'information',
        audit_user=getattr(current_user, 'id', None),
    )

    http = 200 if started else 400
    # `ok` is computed: "did any delete start", not "did the request succeed".
    # api_ok would stamp it True and hide a batch where nothing ran.
    return jsonify({
        'ok': started > 0,
        'started': started,
        'failed': failed,
        'count': len(uuids),
        'force': force,
        'results': results,
        'progress_hint': {
            'sse': '/delete_library_progress/<job_id>',
            'poll': '/check_deletion_progress/<job_id>',
        },
    }), http
