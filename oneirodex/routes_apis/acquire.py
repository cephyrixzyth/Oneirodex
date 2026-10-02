"""Member Acquire API — native indexers / hubs / debrid search & send (feature-flagged)."""

from __future__ import annotations

from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, request
from flask_login import current_user, login_required

from oneirodex.schemas.acquire import AcquireDownloadBody
from oneirodex.utils.acquire_scoring import rank_acquire_hits, title_looks_like_newer_repack
from oneirodex.utils.arr_connectors import (
    client_error_message,
    get_arr_config,
    search_indexers,
    send_to_download_client,
)
from oneirodex.utils.debrid_connectors import (
    alldebrid_upload_magnet,
    debrid_enabled,
    debrid_status,
    premiumize_add_magnet,
    real_debrid_add_magnet,
    torbox_add_magnet,
)
from oneirodex.utils.indexer_registry import indexer_status_summary
from oneirodex.utils.module_status import arr_module_on
from oneirodex.utils.rbac import is_librarian, normalize_role
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _acquire_allowed() -> bool:
    return arr_module_on() or debrid_enabled()


def _indexer_readiness() -> dict:
    """Native + hub readiness for Acquire empty-state (same warning semantics as Arr status)."""
    if not arr_module_on():
        return {
            'native_ready': False,
            'hubs_ready': False,
            'indexers_ready': False,
            'indexer_warnings': [],
            'native_count': 0,
            'native_ready_count': 0,
        }
    native = indexer_status_summary()
    cfg = get_arr_config()
    hubs_ready = bool(
        (cfg.get('prowlarr_url') and cfg.get('prowlarr_api_key'))
        or (cfg.get('jackett_url') and cfg.get('jackett_api_key'))
    )
    native_ready = bool(native.get('configured'))
    return {
        'native_ready': native_ready,
        'hubs_ready': hubs_ready,
        'indexers_ready': native_ready or hubs_ready,
        'indexer_warnings': list(native.get('warnings') or []),
        'native_count': int(native.get('count') or 0),
        'native_ready_count': int(native.get('ready') or 0),
    }


@apis_bp.route('/acquire/status', methods=['GET'])
@login_required
def acquire_status():
    readiness = _indexer_readiness()
    return api_ok({
        'enabled': _acquire_allowed(),
        'arr_enabled': arr_module_on(),
        'debrid_enabled': debrid_enabled(),
        'debrid': debrid_status(),
        'can_send': is_librarian(current_user),
        'clients': ['qbittorrent', 'transmission', 'sabnzbd', 'nzbget'],
        'native_ready': readiness['native_ready'],
        'hubs_ready': readiness['hubs_ready'],
        'indexers_ready': readiness['indexers_ready'],
        'indexer_warnings': readiness['indexer_warnings'],
        'native_count': readiness['native_count'],
        'native_ready_count': readiness['native_ready_count'],
        'message': (
            'Acquisition ready (native indexers / hubs / debrid configured by admin).'
            if _acquire_allowed()
            else 'Enable ENABLE_ARR_MODULE and/or ENABLE_DEBRID to use Acquire.'
        ),
    })


@apis_bp.route('/acquire/search', methods=['GET'])
@login_required
def acquire_search():
    if normalize_role(getattr(current_user, 'role', None)) == 'child':
        return api_error(
            'Acquire search is not available on child accounts',
            code='forbidden',
        )
    if not arr_module_on():
        return api_error('Arr module disabled', code='forbidden')
    query = (request.args.get('q') or '').strip()
    if not query:
        return api_error('q required', code='bad_request')
    current_label = (request.args.get('current') or '').strip()
    try:
        hits = search_indexers(query)
    except Exception as exc:
        return api_error(client_error_message(exc, noun='indexer'), code='bad_gateway')
    ranked = rank_acquire_hits([hit.to_dict() for hit in hits], query=query)
    if current_label:
        for row in ranked:
            row['newer_repack'] = title_looks_like_newer_repack(
                str(row.get('title') or ''),
                current_label,
            )
    warnings = list(indexer_status_summary().get('warnings') or [])
    return jsonify({'q': query, 'results': ranked, 'warnings': warnings})


@apis_bp.route('/acquire/download', methods=['POST'])
@login_required
@validate_body(AcquireDownloadBody)
def acquire_download(body: AcquireDownloadBody):
    """Send magnet/URL to download client or debrid — librarian/admin only."""
    if not is_librarian(current_user):
        return api_error('Librarian or admin required', code='forbidden')
    url = (body.url or body.magnet or '').strip()
    provider = (body.provider or 'qbittorrent').strip().lower()
    if url.lower().startswith('http://') or url.lower().startswith('https://'):
        from oneirodex.utils.security import validate_user_outbound_http_url
        ok, result = validate_user_outbound_http_url(url)
        if not ok:
            return api_error(result, code='bad_request')
        url = result
    try:
        if provider in ('qbittorrent', 'transmission', 'sabnzbd', 'nzbget', 'deluge'):
            if not arr_module_on():
                return api_error('Arr module disabled', code='forbidden')
            result = send_to_download_client(url, provider=provider)
            return api_ok({'provider': provider, 'result': result})
        if provider == 'real_debrid':
            if not debrid_enabled():
                return api_error('Debrid disabled', code='forbidden')
            payload = real_debrid_add_magnet(url)
            return api_ok({'provider': 'real_debrid', 'result': payload})
        if provider == 'alldebrid':
            if not debrid_enabled():
                return api_error('Debrid disabled', code='forbidden')
            payload = alldebrid_upload_magnet(url)
            return api_ok({'provider': 'alldebrid', 'result': payload})
        if provider == 'premiumize':
            if not debrid_enabled():
                return api_error('Debrid disabled', code='forbidden')
            payload = premiumize_add_magnet(url)
            return api_ok({'provider': 'premiumize', 'result': payload})
        if provider == 'torbox':
            if not debrid_enabled():
                return api_error('Debrid disabled', code='forbidden')
            payload = torbox_add_magnet(url)
            return api_ok({'provider': 'torbox', 'result': payload})
        return api_error('Unknown provider', code='bad_request')
    except Exception as exc:
        # Not str(exc): a failed SABnzbd/AllDebrid call carries ?apikey=... and
        # the pinned internal address in its text.
        return api_error(client_error_message(exc), code='bad_gateway')
