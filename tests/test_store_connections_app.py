"""LIB-04 on the full app and real schema: connect-body validation, the
Playnite kill switch, the status route, admin authorization, the poller's job
records and long provider IDs. Provider calls are faked; nothing leaves the host.
"""
import json
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import GlobalSettings, StoreAccount, StoreSyncJob, User, UserOwnedTitle


def _person(db_session, role='user'):
    uid = str(uuid4())
    row = User(name=f'p04_{uid[:8]}', email=f'p04_{uid[:8]}@example.com', role=role, user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def member(db_session):
    return _person(db_session)


def _settings(db_session, **values):
    row = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
    if row is None:
        row = GlobalSettings()
        db_session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db_session.commit()
    return row


def _login(client, app, person):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(person.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(person)


def test_connect_bodies_accept_existing_aliases_and_reject_the_rest(client, app, db_session, member):
    _settings(db_session, enable_store_ownership_sync=True)
    _login(client, app, member)
    assert client.post('/api/ownership/gog', json={'user_id': 'me', 'token': 'refresh'}).status_code == 201
    stored = db_session.execute(select(StoreAccount).filter_by(user_id=member.id, store='gog')).scalar_one()
    assert json.loads(stored.credential) == {'refresh_token': 'refresh'} and stored.updated_at is not None
    assert client.post('/api/ownership/epic', json={'note': 'n', 'device_auth': {'account_id': 'a', 'device_id': 'd', 'secret': 's'}}).status_code == 201
    assert client.post('/api/ownership/amazon', json={'nile_json': {'tokens': {'bearer': {'refresh_token': 'r'}}}, 'device_serial_number': 'S'}).status_code == 201
    response = client.post('/api/ownership/gog', json={'refresh_token': 'x', 'download': True})
    assert response.status_code == 422 and response.get_json()['error_code'] == 'unprocessable'
    assert client.post('/api/ownership/epic', json={'note': 'x' * 121}).status_code == 422
    body = client.post('/api/ownership/gog', json={'refresh_token': 'y'}).get_json()
    assert 'refresh' not in json.dumps(body['account']) and body['ok'] is True


def test_over_long_notes_are_bounded_not_logged_with_credentials(client, app, db_session, member):
    _settings(db_session, enable_store_ownership_sync=True)
    _login(client, app, member)
    assert client.post('/api/ownership/xbox', json={'note': 'n' * 120, 'credential': {'oauth': {}}}).status_code == 201
    stored = db_session.execute(select(StoreAccount).filter_by(user_id=member.id, store='xbox')).scalar_one()
    assert len(stored.external_account_id) == 64


def test_playnite_import_honours_the_kill_switch_and_reports_bad_files(client, app, db_session, member):
    _login(client, app, member)
    _settings(db_session, enable_store_ownership_sync=True)
    response = client.post('/api/imports/playnite', data={'file': (__import__('io').BytesIO(b'{not json'), 'library.json')},
                           content_type='multipart/form-data')
    assert response.status_code == 400 and response.get_json()['error_code'] == 'bad_request'
    # An export the importer refuses says why, and keeps its counts where callers read them.
    response = client.post('/api/imports/playnite', data={'file': (__import__('io').BytesIO(b'appid,store\n570,steam\n'), 'steam.csv')},
                           content_type='multipart/form-data')
    body = response.get_json()
    assert response.status_code == 400 and body['error'] == 'CSV must include a Name column'
    assert body['imported'] == 0 and body['errors'] == ['CSV must include a Name column']
    _settings(db_session, enable_store_ownership_sync=False)
    assert client.post('/api/imports/playnite', json=[{'Name': 'Game'}]).status_code == 403


def test_status_route_covers_every_provider(client, app, db_session, member):
    _settings(db_session, enable_store_ownership_sync=True)
    _login(client, app, member)
    body = client.get('/api/ownership/connections').get_json()
    assert body['ok'] is True and body['schema_version'] == 1
    assert len(body['connections']) == 14
    assert {c['state'] for c in body['connections']} <= {
        'unavailable', 'disabled', 'import_only', 'not_configured', 'not_connected', 'needs_credential',
        'connected', 'syncing', 'partial', 'reauth_required', 'failed', 'cancelled'}


def test_admin_diagnostics_require_admin(client, app, db_session, member):
    _login(client, app, member)
    assert client.get('/api/admin/ownership/connections').status_code in (302, 401, 403)
    admin = _person(db_session, role='admin')
    _login(client, app, admin)
    response = client.get('/api/admin/ownership/connections')
    assert response.status_code == 200 and 'household' in response.get_json()


def test_csv_import_keeps_long_ids_whole_and_skips_absurd_ones(client, app, db_session, member):
    _settings(db_session, enable_store_ownership_sync=True)
    _login(client, app, member)
    pfn = 'Microsoft.SeaofThieves_8wekyb3d8bbwe'
    csv_text = f'pfn,name\n{pfn},Sea of Thieves\n{"x" * 200},Too long\n'
    body = client.post('/api/ownership/xbox/csv', json={'csv': csv_text}).get_json()
    assert body['imported'] == 1 and body['skipped'] == 1
    ids = db_session.execute(select(UserOwnedTitle.external_app_id).filter_by(user_id=member.id, store='xbox')).scalars().all()
    assert ids == [pfn]


def test_poller_records_jobs_and_waits_for_a_reconnect(app, db_session, member, monkeypatch):
    from oneirodex.utils import ownership_poller

    other = _person(db_session)
    for person in (member, other):
        db_session.add(StoreAccount(user_id=person.id, store='steam', external_account_id='7656119'))
    db_session.commit()
    for name, value in (('is_ownership_sync_enabled', lambda: True), ('get_steam_web_api_key', lambda: 'key'),
                        ('gog_live_ready', lambda: False), ('epic_live_ready', lambda: False),
                        ('amazon_live_ready', lambda: False)):
        monkeypatch.setattr(f'oneirodex.utils.store_ownership.{name}', value)
    calls = []

    def fake(user_id):
        from oneirodex.utils.store_sync_errors import StoreSyncError
        calls.append(user_id)
        if user_id == member.id:
            raise StoreSyncError('Steam rejected', 'credential_rejected')
        return {'synced': 0, 'matched': 0, 'store': 'steam'}
    monkeypatch.setattr('oneirodex.utils.store_ownership.sync_steam_owned_games', fake)

    with app.app_context():
        ownership_poller.sync_all_linked_accounts()
        jobs = {j.user_id: j for j in db_session.execute(select(StoreSyncJob).where(
            StoreSyncJob.user_id.in_([member.id, other.id]))).scalars()}
        assert jobs[member.id].trigger == 'schedule' and jobs[member.id].reason == 'credential_rejected'
        assert jobs[other.id].status == 'succeeded'
        calls.clear()
        result = ownership_poller.sync_all_linked_accounts()
        assert member.id not in calls and other.id in calls, 'a refused sign-in waits for the member'
        assert result['waiting'] >= 1


def test_poller_keeps_retrying_a_refused_household_sign_in(app, db_session, member, monkeypatch):
    """The operator fixes a household token by replacing it; the poller must try again."""
    from oneirodex.utils import ownership_poller
    from oneirodex.utils.store_sync_jobs import utcnow

    db_session.add(StoreAccount(user_id=member.id, store='steam', external_account_id='7656119'))
    db_session.add(StoreSyncJob(user_id=member.id, store='steam', trigger='schedule', status='failed',
                                reason='household_credential_rejected', started_at=utcnow(),
                                heartbeat_at=utcnow(), finished_at=utcnow()))
    db_session.commit()
    for name, value in (('is_ownership_sync_enabled', lambda: True), ('get_steam_web_api_key', lambda: 'key'),
                        ('gog_live_ready', lambda: False), ('epic_live_ready', lambda: False),
                        ('amazon_live_ready', lambda: False)):
        monkeypatch.setattr(f'oneirodex.utils.store_ownership.{name}', value)
    calls = []
    monkeypatch.setattr('oneirodex.utils.store_ownership.sync_steam_owned_games',
                        lambda uid: calls.append(uid) or {'synced': 0, 'matched': 0, 'store': 'steam'})
    with app.app_context():
        ownership_poller.sync_all_linked_accounts()
    assert member.id in calls


def test_connect_is_refused_while_a_sync_runs(client, app, db_session, member):
    from oneirodex.utils.store_sync_jobs import utcnow

    _settings(db_session, enable_store_ownership_sync=True)
    _login(client, app, member)
    assert client.post('/api/ownership/gog', json={'refresh_token': 'first'}).status_code == 201
    db_session.add(StoreSyncJob(user_id=member.id, store='gog', trigger='member', status='running',
                                cancellable=True, started_at=utcnow(), heartbeat_at=utcnow()))
    db_session.commit()
    response = client.post('/api/ownership/gog', json={'refresh_token': 'second'})
    assert response.status_code == 409 and response.get_json()['detail']['reason'] == 'sync_in_progress'
    stored = db_session.execute(select(StoreAccount.credential).filter_by(user_id=member.id, store='gog')).scalar()
    assert json.loads(stored) == {'refresh_token': 'first'}
    assert client.delete('/api/ownership/gog').status_code == 409


def test_first_run_and_admin_diagnostics_pages_are_served(client, app, db_session, member):
    _login(client, app, member)
    assert client.get('/welcome').status_code == 200
    assert client.get('/admin/ownership').status_code in (302, 401, 403)
    admin = _person(db_session, role='admin')
    _login(client, app, admin)
    page = client.get('/admin/ownership')
    assert page.status_code == 200 and b'data-admin-render="spa"' in page.data
