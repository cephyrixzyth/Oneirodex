"""Administrator store-connection diagnostics and repair (LIB-04).

An administrator sees each member's connection *state*, reason codes, counts
and which kind of credential a sync would use — never the credential, the
member's external account ID or their title list — and can retry or cancel a
sync on a member's behalf. A retry runs with the member's own saved sign-in,
exactly as the background refresh would, and records who asked.
"""

from flask import request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import StoreAccount, User
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.store_connection_status import admin_connections
from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled
from oneirodex.utils.store_sync_errors import REASONS, SyncOutcomeError, reason_payload
from oneirodex.utils.store_sync_jobs import LIVE_SYNC_ADAPTERS, PROVIDER_NAMES, job_dict, request_cancel, run_store_sync

from . import apis_bp


def _outcome_error(store, reason, job=None):
    entry = REASONS.get(reason) or REASONS['internal_error']
    info = reason_payload(reason, PROVIDER_NAMES.get(store, store))
    return api_error(info['message'], code=entry.envelope_code, status=entry.http_status,
                     detail=info, job=job_dict(job) if job is not None else None)


@apis_bp.route('/admin/ownership/connections', methods=['GET'])
@login_required
@admin_required
def admin_ownership_connections():
    raw = request.args.get('after_id', '0')
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or int(raw) > 2147483647:
        return api_error('after_id must be a nonnegative integer cursor', code='bad_request')
    return api_ok(admin_connections(after_id=int(raw)))


def _member_store(user_id, store):
    if store not in LIVE_SYNC_ADAPTERS:
        return api_error('No live sync exists for this store', code='not_found')
    if db.session.execute(select(User.id).where(User.id == user_id)).first() is None:
        return api_error('Member not found', code='not_found')
    return None


@apis_bp.route('/admin/ownership/connections/<int:user_id>/<store>/sync', methods=['POST'])
@login_required
@admin_required
def admin_retry_ownership_sync(user_id, store):
    problem = _member_store(user_id, store)
    if problem is not None:
        return problem
    if not is_ownership_sync_enabled():
        return api_error('Store ownership sync is disabled by administrator', code='forbidden')
    linked = db.session.execute(select(StoreAccount.id).where(
        StoreAccount.user_id == user_id, StoreAccount.store == store,
    )).first()
    if linked is None:
        return _outcome_error(store, 'not_connected')
    try:
        outcome = run_store_sync(user_id, store, trigger='admin', actor_id=current_user.id)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    job = outcome['job']
    if job.status == 'failed':
        return _outcome_error(store, outcome['reason'], job)
    return api_ok({'job': job_dict(job)})


@apis_bp.route('/admin/ownership/connections/<int:user_id>/<store>/cancel', methods=['POST'])
@login_required
@admin_required
def admin_cancel_ownership_sync(user_id, store):
    problem = _member_store(user_id, store)
    if problem is not None:
        return problem
    try:
        job = request_cancel(user_id, store)
    except SyncOutcomeError as exc:
        return _outcome_error(store, exc.reason, exc.job)
    return api_ok({'job': job_dict(job)}, status=202)
