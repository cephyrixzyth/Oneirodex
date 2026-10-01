"""Register-only store ownership sync APIs (never downloads from stores)."""

from oneirodex.utils.api_response import api_error, api_ok
from flask import request
from flask_login import current_user, login_required

from oneirodex.schemas.ownership import (
    AmazonConnectBody,
    ConnectSteamBody,
    EpicConnectBody,
    GogConnectBody,
    PsnConnectBody,
    XboxConnectBody,
)
from oneirodex.utils.validation import validate_body

from oneirodex.utils.store_ownership import (
    connect_amazon_account,
    connect_epic_account,
    connect_gog_account,
    connect_steam_account,
    disconnect_amazon_account,
    disconnect_epic_account,
    disconnect_gog_account,
    disconnect_steam_account,
    get_ownership_summary,
    connect_psn_account,
    connect_xbox_account,
    disconnect_psn_account,
    disconnect_xbox_account,
    import_amazon_csv,
    import_epic_csv,
    import_psn_csv,
    import_xbox_csv,
    import_gog_csv,
    import_meta_quest_csv,
    import_steam_csv,
    is_ownership_sync_enabled,
)

from . import apis_bp
from oneirodex.utils.store_capabilities import provider_capabilities
from oneirodex.utils.store_connection_status import member_connections
from oneirodex.utils.store_ownership_common import unofficial_store_opt_in
from oneirodex.utils.store_sync_errors import REASONS, SyncOutcomeError, reason_payload
from oneirodex.utils.store_sync_jobs import (
    LIVE_SYNC_ADAPTERS,
    PROVIDER_NAMES,
    exclusive_link_change,
    job_dict,
    request_cancel,
    run_store_sync,
)
from oneirodex.utils.ownership_review import (
    REVIEW_FILTERS,
    ReviewError,
    decide_match,
    list_review_titles,
    match_candidates,
)
from oneirodex import db


@apis_bp.route('/ownership/titles', methods=['GET'])
@login_required
def ownership_review_titles():
    raw = request.args.get('after_id', '0')
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or int(raw) > 2147483647:
        return api_error('after_id must be a nonnegative integer cursor', code='bad_request')
    status = request.args.get('status') or None
    if status is not None and status not in REVIEW_FILTERS:
        return api_error('status must be needs_review or matched', code='bad_request')
    return api_ok(list_review_titles(current_user, int(raw), status))


@apis_bp.route('/ownership/titles/<int:title_id>/candidates', methods=['GET'])
@login_required
def ownership_match_candidates(title_id):
    try:
        return api_ok(match_candidates(current_user, title_id))
    except ReviewError as exc:
        return api_error(str(exc), code=exc.code)


@apis_bp.route('/ownership/titles/<int:title_id>/match', methods=['POST'])
@login_required
def review_ownership_match(title_id):
    return _match_decision(title_id)


@apis_bp.route('/ownership/titles/<int:title_id>/match/undo', methods=['POST'])
@login_required
def undo_ownership_match(title_id):
    return _match_decision(title_id, undo=True)


def _match_decision(title_id, *, undo=False):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or (not undo and 'game_uuid' not in data):
        return api_error('A JSON decision with game_uuid (or null) is required', code='bad_request')
    try:
        return api_ok(decide_match(current_user, title_id, data.get('expected_revision'), data.get('game_uuid'), undo=undo))
    except ReviewError as exc:
        db.session.rollback()
        return api_error(str(exc), code=exc.code)


@apis_bp.route('/ownership/providers', methods=['GET'])
@login_required
def ownership_providers():
    """Capability metadata only; no account identifiers, credentials or network calls."""
    return api_ok({
        'schema_version': 1,
        'providers': provider_capabilities(
            enabled=is_ownership_sync_enabled(),
            unofficial_stores=unofficial_store_opt_in(),
        ),
    })


@apis_bp.route('/ownership/connections', methods=['GET'])
@login_required
def ownership_connections():
    """The current member's status per provider (LIB-04). Stored facts only:
    no provider call, no credential. Poll while a sync runs to show progress."""
    return api_ok(member_connections(current_user))


def _feature_disabled_response():
    return api_error('Store ownership sync is disabled by administrator', code='forbidden')


def _outcome_error(store, reason, job=None):
    """Redacted failure: a catalogue sentence plus reason/action, never exception text."""
    entry = REASONS.get(reason) or REASONS['internal_error']
    info = reason_payload(reason, PROVIDER_NAMES.get(store, store))
    return api_error(info['message'], code=entry.envelope_code, status=entry.http_status,
                     detail=info, job=job_dict(job) if job is not None else None)


def _sync_response(store):
    """Run one member-triggered live sync as a recorded job."""
    if not is_ownership_sync_enabled():
        return _outcome_error(store, 'sync_disabled')
    try:
        outcome = run_store_sync(current_user.id, store, trigger='member', actor_id=current_user.id)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    job = outcome['job']
    if job.status == 'failed':
        return _outcome_error(store, outcome['reason'], job)
    payload = {**(outcome['result'] or {}), 'store': store, 'job': job_dict(job)}
    if job.status == 'cancelled':
        payload.update(synced=0, matched=0, cancelled=True)
    payload['summary'] = get_ownership_summary(current_user.id)
    return api_ok(payload)


def _disconnect_response(store, disconnect):
    if not is_ownership_sync_enabled():
        return _feature_disabled_response()
    # Holds the member's running slot, so no sync can be mid-flight (and write
    # the titles back) while the link and its titles are removed.
    try:
        exclusive_link_change(current_user.id, store, 'disconnect',
                              lambda: disconnect(current_user.id), clear_history=True)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    return api_ok({'summary': get_ownership_summary(current_user.id)})


def _connect_response(store, connect):
    """Save a link or reconnect while no sync for it runs; a sync finishing
    later would otherwise write back the old token over the new one."""
    if not is_ownership_sync_enabled():
        return _feature_disabled_response()
    try:
        account = exclusive_link_change(current_user.id, store, 'connect', connect)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({
        'account': account.to_dict(),
        'summary': get_ownership_summary(current_user.id),
    }, status=201)


@apis_bp.route('/ownership/<store>/sync/cancel', methods=['POST'])
@login_required
def cancel_ownership_sync(store):
    """Ask a running GOG / Epic / Amazon sync to stop at its next page. Steam,
    Xbox and PlayStation make one provider call and are refused, not faked."""
    if store not in LIVE_SYNC_ADAPTERS:
        return api_error('No live sync exists for this store', code='not_found')
    try:
        job = request_cancel(current_user.id, store)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    return api_ok({'job': job_dict(job)}, status=202)


def _read_csv_payload() -> str:
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return data.get('csv') or ''
    upload = request.files.get('file')
    if upload:
        return upload.read().decode('utf-8', errors='replace')
    return request.form.get('csv') or ''


def _csv_response(import_csv, **extra):
    if not is_ownership_sync_enabled():
        return _feature_disabled_response()
    csv_text = _read_csv_payload()
    if not csv_text.strip():
        return api_error('csv content required', code='bad_request')
    try:
        result = import_csv(current_user.id, csv_text)
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({**result, 'summary': get_ownership_summary(current_user.id), **extra})


@apis_bp.route('/ownership', methods=['GET'])
@login_required
def ownership_status():
    return api_ok(get_ownership_summary(current_user.id))


@apis_bp.route('/ownership/steam', methods=['POST'])
@login_required
@validate_body(ConnectSteamBody)
def connect_steam(body: ConnectSteamBody):
    return _connect_response('steam', lambda: connect_steam_account(current_user.id, body.steam_id))


@apis_bp.route('/ownership/steam', methods=['DELETE'])
@login_required
def disconnect_steam():
    return _disconnect_response('steam', disconnect_steam_account)


@apis_bp.route('/ownership/steam/sync', methods=['POST'])
@login_required
def sync_steam():
    return _sync_response('steam')


@apis_bp.route('/ownership/steam/csv', methods=['POST'])
@login_required
def import_steam_csv_route():
    return _csv_response(import_steam_csv)


@apis_bp.route('/ownership/gog', methods=['POST'])
@login_required
@validate_body(GogConnectBody)
def connect_gog(body: GogConnectBody):
    gog_user_id = (body.gog_user_id or body.user_id or '').strip() or None
    note = (body.note or '').strip() or None
    refresh_token = (body.refresh_token or body.token or '').strip() or None
    access_token = (body.access_token or '').strip() or None
    return _connect_response('gog', lambda: connect_gog_account(
        current_user.id,
        gog_user_id,
        note,
        refresh_token=refresh_token,
        access_token=access_token,
    ))


@apis_bp.route('/ownership/gog', methods=['DELETE'])
@login_required
def disconnect_gog():
    return _disconnect_response('gog', disconnect_gog_account)


@apis_bp.route('/ownership/gog/sync', methods=['POST'])
@login_required
def sync_gog():
    return _sync_response('gog')


@apis_bp.route('/ownership/gog/csv', methods=['POST'])
@login_required
def import_gog_csv_route():
    return _csv_response(import_gog_csv)


@apis_bp.route('/ownership/epic', methods=['POST'])
@login_required
@validate_body(EpicConnectBody)
def connect_epic(body: EpicConnectBody):
    epic_account_id = (body.epic_account_id or body.user_id or '').strip() or None
    note = (body.note or '').strip() or None
    device_auth = body.device_auth or body.token or None
    return _connect_response('epic', lambda: connect_epic_account(
        current_user.id, epic_account_id, note, device_auth=device_auth,
    ))


@apis_bp.route('/ownership/epic', methods=['DELETE'])
@login_required
def disconnect_epic():
    return _disconnect_response('epic', disconnect_epic_account)


@apis_bp.route('/ownership/epic/sync', methods=['POST'])
@login_required
def sync_epic():
    return _sync_response('epic')


@apis_bp.route('/ownership/epic/csv', methods=['POST'])
@login_required
def import_epic_csv_route():
    return _csv_response(import_epic_csv)


@apis_bp.route('/ownership/amazon', methods=['POST'])
@login_required
@validate_body(AmazonConnectBody)
def connect_amazon(body: AmazonConnectBody):
    amazon_user_id = (body.amazon_user_id or body.user_id or '').strip() or None
    note = (body.note or '').strip() or None
    credential = body.credential or body.token or body.nile_json or None
    refresh_token = (body.refresh_token or '').strip() or None
    access_token = (body.access_token or '').strip() or None
    device_serial = (body.device_serial or body.device_serial_number or '').strip() or None
    return _connect_response('amazon', lambda: connect_amazon_account(
        current_user.id,
        amazon_user_id,
        note,
        credential=credential,
        refresh_token=refresh_token,
        access_token=access_token,
        device_serial=device_serial,
    ))


@apis_bp.route('/ownership/amazon', methods=['DELETE'])
@login_required
def disconnect_amazon():
    return _disconnect_response('amazon', disconnect_amazon_account)


@apis_bp.route('/ownership/amazon/sync', methods=['POST'])
@login_required
def sync_amazon():
    return _sync_response('amazon')


def _unofficial_store_routes(store: str, connect, disconnect, import_csv, body_model):
    """connect / disconnect / sync / csv for one opt-in unofficial store (INSP-42).

    Register-only. Sync says in one sentence when the operator has not opted
    in or the optional client is not installed; CSV works regardless.
    """

    @apis_bp.route(f'/ownership/{store}', methods=['POST'], endpoint=f'connect_{store}')
    @login_required
    @validate_body(body_model)
    def _connect(body):
        data = body.model_dump(exclude_none=True)
        return _connect_response(store, lambda: connect(current_user.id, **data))

    @apis_bp.route(f'/ownership/{store}', methods=['DELETE'], endpoint=f'disconnect_{store}')
    @login_required
    def _disconnect():
        return _disconnect_response(store, disconnect)

    @apis_bp.route(f'/ownership/{store}/sync', methods=['POST'], endpoint=f'sync_{store}')
    @login_required
    def _sync():
        return _sync_response(store)

    @apis_bp.route(f'/ownership/{store}/csv', methods=['POST'], endpoint=f'import_{store}_csv')
    @login_required
    def _csv():
        return _csv_response(import_csv)


_unofficial_store_routes('xbox', connect_xbox_account, disconnect_xbox_account, import_xbox_csv, XboxConnectBody)
_unofficial_store_routes('psn', connect_psn_account, disconnect_psn_account, import_psn_csv, PsnConnectBody)


@apis_bp.route('/ownership/amazon/csv', methods=['POST'])
@login_required
def import_amazon_csv_route():
    return _csv_response(import_amazon_csv)


@apis_bp.route('/ownership/meta_quest/csv', methods=['POST'])
@login_required
def import_meta_quest_csv_route():
    """Register-only Meta/Quest ownership CSV (never downloads DRM titles)."""
    return _csv_response(
        import_meta_quest_csv,
        note='Ownership register only — Oneirodex never downloads Meta/Quest DRM titles.',
    )
