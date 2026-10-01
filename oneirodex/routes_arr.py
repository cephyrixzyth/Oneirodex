"""Optional *arr automation module (feature-flagged connectors)."""

from __future__ import annotations

import requests
from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from oneirodex import db
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.arr_connectors import (
    client_error_message,
    connector_status,
    get_arr_config,
    qbittorrent_add_url,
    save_arr_config,
    search_indexers,
)
from oneirodex.utils.arr_hardlink_pipeline import (
    apply_proposals,
    pipeline_enabled,
    propose_hardlinks,
)
from oneirodex.utils.auth import admin_required
from oneirodex.utils.indexer_registry import (
    add_indexer,
    bulk_import_indexers,
    delete_indexer,
    enable_presets,
    get_indexer,
    indexer_public_view,
    indexer_status_summary,
    list_indexers,
    load_indexer_presets,
    update_indexer,
)
from oneirodex.utils.module_status import (
    arr_db_enabled,
    arr_module_on,
    ensure_global_settings,
    env_flag,
)
from oneirodex.schemas.arr import ArrDownloadBody, ArrHardlinkPreviewBody
from oneirodex.utils.quality_profiles import score_release_title
from oneirodex.utils.security import validate_user_outbound_http_url
from oneirodex.utils.validation import validate_body

arr_bp = Blueprint('arr', __name__)


def arr_module_enabled() -> bool:
    return arr_module_on()


def _arr_disabled():
    return api_error('Arr module is disabled', code='forbidden')


@arr_bp.route('/api/arr/status', methods=['GET'])
@login_required
@admin_required
def arr_status():
    """Feature-flag + connector readiness for the optional *arr module."""
    enabled = arr_module_enabled()
    connectors = connector_status() if enabled else []
    configured = any(c.get('configured') for c in connectors)
    return api_ok({
        'enabled': enabled,
        'module': 'arr',
        'status': (
            'ready' if enabled and configured
            else 'enabled' if enabled
            else 'disabled'
        ),
        'message': (
            'Arr module ready — configure native indexers, presets, and optional '
            'Prowlarr/Jackett hubs in Admin → Arr.'
            if enabled
            else 'Arr module is disabled. Set ENABLE_ARR_MODULE=true or enable in Admin.'
        ),
        'connectors': connectors,
        'indexer_warnings': next(
            (c.get('warnings') or [] for c in connectors if c.get('id') == 'native_indexers'),
            [],
        ),
    })


@arr_bp.route('/api/arr/module', methods=['GET', 'PUT'])
@login_required
@admin_required
def arr_module_flag():
    """Read/write the DB toggle. Available even when the module is currently off."""
    env_on = env_flag('ENABLE_ARR_MODULE')
    if request.method == 'GET':
        return jsonify({
            'enabled': arr_module_enabled(),
            'db_enabled': arr_db_enabled(),
            'env_enabled': env_on,
        })
    data = request.get_json(silent=True) or {}
    if 'enabled' not in data and 'enable_arr_module' not in data:
        return api_error('enabled is required', code='bad_request')
    enabled = bool(data.get('enabled', data.get('enable_arr_module')))
    settings = ensure_global_settings()
    settings.enable_arr_module = enabled
    db.session.commit()
    return api_ok({
        'status': 'saved',
        'enabled': arr_module_enabled(),
        'db_enabled': bool(settings.enable_arr_module),
        'env_enabled': env_on,
    })


@arr_bp.route('/api/arr/config', methods=['GET', 'PUT'])
@login_required
@admin_required
def arr_config():
    if not arr_module_enabled():
        return _arr_disabled()
    if request.method == 'GET':
        cfg = get_arr_config()
        return jsonify({
            'prowlarr_url': cfg.get('prowlarr_url') or '',
            'prowlarr_api_key_set': bool(cfg.get('prowlarr_api_key')),
            'jackett_url': cfg.get('jackett_url') or '',
            'jackett_api_key_set': bool(cfg.get('jackett_api_key')),
            'qbittorrent_url': cfg.get('qbittorrent_url') or '',
            'qbittorrent_username': cfg.get('qbittorrent_username') or 'admin',
            'qbittorrent_password_set': bool(cfg.get('qbittorrent_password')),
            'transmission_url': cfg.get('transmission_url') or '',
            'transmission_username': cfg.get('transmission_username') or '',
            'transmission_password_set': bool(cfg.get('transmission_password')),
            'sabnzbd_url': cfg.get('sabnzbd_url') or '',
            'sabnzbd_api_key_set': bool(cfg.get('sabnzbd_api_key')),
            'nzbget_url': cfg.get('nzbget_url') or '',
            'nzbget_username': cfg.get('nzbget_username') or '',
            'nzbget_password_set': bool(cfg.get('nzbget_password')),
        })
    data = request.get_json(silent=True) or {}
    try:
        saved = save_arr_config(data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'status': 'saved', 'config': saved})


@arr_bp.route('/api/arr/indexers', methods=['GET', 'POST'])
@login_required
@admin_required
def arr_indexers():
    """List native indexers + read-only presets catalog, or add one indexer."""
    if not arr_module_enabled():
        return _arr_disabled()
    if request.method == 'GET':
        return jsonify({
            'indexers': [indexer_public_view(row) for row in list_indexers()],
            'presets': load_indexer_presets(),
        })
    data = request.get_json(silent=True) or {}
    try:
        row = add_indexer(data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'status': 'created', 'indexer': indexer_public_view(row)}, status=201)


@arr_bp.route('/api/arr/indexers/bulk', methods=['POST'])
@login_required
@admin_required
def arr_indexers_bulk():
    if not arr_module_enabled():
        return _arr_disabled()
    data = request.get_json(silent=True)
    if data is None:
        raw = (request.get_data(as_text=True) or '').strip()
        data = raw
    try:
        created = bulk_import_indexers(data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except Exception:
        return api_error('Could not import indexers', code='bad_request')
    return api_ok({
        'status': 'imported',
        'count': len(created),
        'indexers': [indexer_public_view(row) for row in created],
    }, status=201)


@arr_bp.route('/api/arr/indexers/enable-presets', methods=['POST'])
@login_required
@admin_required
def arr_indexers_enable_presets():
    if not arr_module_enabled():
        return _arr_disabled()
    data = request.get_json(silent=True) or {}
    preset_ids = data.get('preset_ids') or data.get('ids') or []
    if not isinstance(preset_ids, list):
        return api_error('preset_ids must be an array', code='bad_request')
    try:
        created = enable_presets(preset_ids)
    except KeyError as exc:
        return api_error(f'Unknown preset_id: {exc.args[0]}', code='not_found')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({
        'status': 'enabled',
        'count': len(created),
        'indexers': [indexer_public_view(row) for row in created],
    }, status=201)


@arr_bp.route('/api/arr/indexers/<indexer_id>', methods=['GET', 'PUT', 'PATCH', 'DELETE'])
@login_required
@admin_required
def arr_indexer_one(indexer_id: str):
    if not arr_module_enabled():
        return _arr_disabled()
    if request.method == 'GET':
        row = get_indexer(indexer_id)
        if not row:
            return api_error('Indexer not found', code='not_found')
        return jsonify({'indexer': indexer_public_view(row)})
    if request.method == 'DELETE':
        if not delete_indexer(indexer_id):
            return api_error('Indexer not found', code='not_found')
        return api_ok({'status': 'deleted', 'id': indexer_id})
    data = request.get_json(silent=True) or {}
    try:
        row = update_indexer(indexer_id, data)
    except KeyError:
        return api_error('Indexer not found', code='not_found')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'status': 'saved', 'indexer': indexer_public_view(row)})


@arr_bp.route('/api/arr/search', methods=['GET'])
@login_required
@admin_required
def arr_search():
    if not arr_module_enabled():
        return _arr_disabled()
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return api_error('Query parameter q is required', code='bad_request')
    try:
        limit = min(int(request.args.get('limit') or 25), 50)
    except (TypeError, ValueError):
        limit = 25
    try:
        hits = search_indexers(query, limit=limit)
    except RuntimeError as exc:
        return api_error(client_error_message(exc, noun='indexer'), code='bad_gateway')
    # Prefer active profile scores; drop hard-blocked / excluded hits unless
    # ``include_disallowed=1`` (operators still see prefer-order for allowed).
    include_disallowed = str(request.args.get('include_disallowed') or '').strip().lower() in {
        '1', 'true', 'yes', 'on',
    }
    results = []
    excluded = 0
    for hit in hits:
        payload = hit.to_dict()
        quality = score_release_title(hit.title, size_bytes=hit.size)
        payload['quality'] = quality
        if not quality.get('allowed', True) and not include_disallowed:
            excluded += 1
            continue
        results.append(payload)
    results.sort(key=lambda item: item['quality']['score'], reverse=True)
    return jsonify({
        'query': query,
        'results': results,
        'excluded_by_quality': excluded,
        'warnings': indexer_status_summary().get('warnings') or [],
    })


@arr_bp.route('/api/arr/download', methods=['POST'])
@login_required
@admin_required
@validate_body(ArrDownloadBody)
def arr_download(body: ArrDownloadBody):
    if not arr_module_enabled():
        return _arr_disabled()
    url = (body.download_url or body.url or '').strip()
    if url.lower().startswith('http://') or url.lower().startswith('https://'):
        ok, result = validate_user_outbound_http_url(url)
        if not ok:
            return api_error(result, code='bad_request')
        url = result
    try:
        result = qbittorrent_add_url(url)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except (RuntimeError, requests.RequestException) as exc:
        # A failed request's text carries the full URL; see client_error_message.
        return api_error(client_error_message(exc, noun='qBittorrent server'), code='bad_gateway')
    return api_ok(result, status=202)


@arr_bp.route('/api/arr/hardlink/preview', methods=['POST'])
@login_required
@admin_required
@validate_body(ArrHardlinkPreviewBody)
def arr_hardlink_preview(body: ArrHardlinkPreviewBody):
    if not arr_module_enabled():
        return _arr_disabled()
    if not pipeline_enabled():
        return api_error(
            'Arr-hardlink pipeline is disabled. Set ENABLE_ARR_HARDLINK_PIPELINE=true.',
            code='forbidden',
        )
    dest = (body.library_dest_dir or body.dest_dir or '').strip()
    try:
        limit = min(int(body.limit or 50), 200)
    except (TypeError, ValueError):
        limit = 50
    try:
        result = propose_hardlinks(dest, limit=limit)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except RuntimeError as exc:
        return api_error(str(exc), code='bad_gateway')
    return jsonify(result)


@arr_bp.route('/api/arr/hardlink/apply', methods=['POST'])
@login_required
@admin_required
def arr_hardlink_apply():
    if not arr_module_enabled():
        return _arr_disabled()
    if not pipeline_enabled():
        return api_error(
            'Arr-hardlink pipeline is disabled. Set ENABLE_ARR_HARDLINK_PIPELINE=true.',
            code='forbidden',
        )
    data = request.get_json(silent=True) or {}
    proposals = data.get('proposals')
    if not isinstance(proposals, list) or not proposals:
        dest = (data.get('library_dest_dir') or data.get('dest_dir') or '').strip()
        if not dest:
            return api_error('proposals or library_dest_dir required', code='bad_request')
        try:
            preview = propose_hardlinks(dest, limit=int(data.get('limit') or 50))
            proposals = preview.get('proposals') or []
        except ValueError as exc:
            return api_error(str(exc), code='bad_request')
        except PermissionError as exc:
            return api_error(str(exc), code='forbidden')
        except RuntimeError as exc:
            return api_error(str(exc), code='bad_gateway')
    try:
        result = apply_proposals(proposals, only_ok=bool(data.get('only_ok', True)))
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    return jsonify(result), 201


@arr_bp.route('/admin/arr', methods=['GET'])
@login_required
@admin_required
def arr_admin_page():
    """Admin page for the optional *arr module."""
    enabled = arr_module_enabled()
    return render_template(
        'admin/arr_module.html',
        enabled=enabled,
        db_enabled=arr_db_enabled(),
        env_enabled=env_flag('ENABLE_ARR_MODULE'),
        connectors=connector_status() if enabled else [],
        hardlink_pipeline=pipeline_enabled(),
    )
