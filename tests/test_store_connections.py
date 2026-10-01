"""Store connection status, sync jobs and repair routes (LIB-04).

Bare Flask app, never the app factory: runs on in-memory SQLite, or on a
dedicated loopback PostgreSQL given as P04_TEST_DATABASE_URL (validated by the
shared test-database guard). Provider calls are replaced by fakes; nothing here
reaches a network.
"""
import contextvars
import json
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests
from flask import Blueprint, Flask, g
from flask_login import LoginManager, UserMixin
from sqlalchemy import delete as sa_delete, func, select, text, update

from oneirodex import db
from oneirodex.models import StoreAccount, StoreSyncJob, UserOwnedTitle
from oneirodex.utils import store_ownership, store_ownership_common, store_sync_jobs
from oneirodex.utils.store_connection_status import admin_connections, member_connections
from oneirodex.utils.store_sync_errors import StoreSyncError
from oneirodex.utils.store_sync_jobs import checkpoint, mark_partial, mark_warning, request_cancel, utcnow

SECRET = 'SECRET-TOKEN-0123456789abcdef'
STEAM_URL = f'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={SECRET}&steamid=765'
MEMBER, OTHER, ADMIN = 1, 2, 3
EPIC_DEVICE = json.dumps({'account_id': 'a', 'device_id': 'd', 'secret': 's'})


def test_database_url():
    value = os.environ.get('P04_TEST_DATABASE_URL')
    if value:
        from database_test_guard import validate_test_database_url
        from sqlalchemy.engine import make_url
        validate_test_database_url(value)
        assert make_url(value).host == '127.0.0.1'
    return value or 'sqlite://'

test_database_url.__test__ = False


class Person(UserMixin):
    def __init__(self, uid, role):
        self.id = uid
        self.role = role


@pytest.fixture
def settings(monkeypatch):
    row = SimpleNamespace(enable_store_ownership_sync=True, steam_web_api_key=None)
    monkeypatch.setattr(store_ownership_common, 'global_settings_row', lambda: row)
    for name in ('GOG_ACCESS_TOKEN', 'GOG_REFRESH_TOKEN', 'GOG_API_TOKEN', 'EPIC_DEVICE_AUTH', 'EPIC_API_TOKEN',
                 'AMAZON_REFRESH_TOKEN', 'AMAZON_NILE_JSON', 'AMAZON_API_TOKEN', 'XBOX_TOKENS_JSON', 'PSN_NPSSO',
                 'STEAM_WEB_API_KEY', 'ENABLE_UNOFFICIAL_STORE_SYNC'):
        monkeypatch.delenv(name, raising=False)
    return row


@pytest.fixture
def app(settings):
    from oneirodex.routes_apis import ownership, ownership_admin
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI=test_database_url())
    db.init_app(flask_app)
    people = {str(MEMBER): Person(MEMBER, 'user'), str(OTHER): Person(OTHER, 'user'), str(ADMIN): Person(ADMIN, 'admin')}
    login = LoginManager(flask_app)
    login.user_loader(people.get)
    stub = Blueprint('login', __name__)
    stub.add_url_rule('/login', 'login', lambda: 'login page')
    flask_app.register_blueprint(stub)
    # Requests made inside the test's app context share its `g`; drop the
    # cached user so each request authenticates from its own session.
    flask_app.before_request(lambda: g.pop('_login_user', None) and None)
    routes = [
        ('/api/ownership/connections', ownership.ownership_connections, ['GET']),
        ('/api/ownership/steam/sync', ownership.sync_steam, ['POST']),
        ('/api/ownership/gog/sync', ownership.sync_gog, ['POST']),
        ('/api/ownership/epic/sync', ownership.sync_epic, ['POST']),
        ('/api/ownership/gog', ownership.disconnect_gog, ['DELETE']),
        ('/api/ownership/<store>/sync/cancel', ownership.cancel_ownership_sync, ['POST']),
        ('/api/admin/ownership/connections', ownership_admin.admin_ownership_connections, ['GET']),
        ('/api/admin/ownership/connections/<int:user_id>/<store>/sync', ownership_admin.admin_retry_ownership_sync, ['POST']),
        ('/api/admin/ownership/connections/<int:user_id>/<store>/cancel', ownership_admin.admin_cancel_ownership_sync, ['POST']),
    ]
    for path, view, methods in routes:
        flask_app.add_url_rule(path, view_func=view, methods=methods)
    with flask_app.app_context():
        with db.engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(64))')
            conn.exec_driver_sql('CREATE TABLE games (uuid VARCHAR(36) PRIMARY KEY, name TEXT, library_uuid VARCHAR(36), steam_app_id INTEGER)')
            conn.exec_driver_sql("INSERT INTO users VALUES (1, 'Member'), (2, 'Other'), (3, 'Admin')")
        for model in (StoreAccount, UserOwnedTitle, StoreSyncJob):
            model.__table__.create(db.engine)
        yield flask_app
        db.session.remove()
        with db.engine.begin() as conn:
            for name in ('store_sync_jobs', 'user_owned_titles', 'store_accounts', 'games', 'users'):
                conn.exec_driver_sql('DROP TABLE ' + name)


def _client(app, uid):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(uid)
        session['_fresh'] = True
    return client


def _link(uid, store, credential=None, external='acct', created=None):
    # Linked before any job a test records, as a real link always is.
    created = created or utcnow() - timedelta(hours=3)
    db.session.add(StoreAccount(user_id=uid, store=store, external_account_id=external, credential=credential,
                                created_at=created, updated_at=utcnow() - timedelta(hours=1)))
    db.session.commit()


def _job(uid, store, status='running', *, reason=None, cancellable=None, age=timedelta(0), finished=None):
    now = utcnow() - age
    job = StoreSyncJob(user_id=uid, store=store, trigger='member', status=status, reason=reason,
                       cancellable=store in store_sync_jobs.CANCELLABLE_STORES if cancellable is None else cancellable,
                       started_at=now, heartbeat_at=now, finished_at=finished)
    db.session.add(job)
    db.session.commit()
    return job.id


def _state(client, store):
    body = client.get('/api/ownership/connections').get_json()
    return next(c for c in body['connections'] if c['provider'] == store)


def _fake_sync(store, rows, *, before_write=None):
    def run(user_id):
        if before_write:
            before_write(user_id)
        for ext, name in rows:
            store_ownership_common.upsert_owned_title(user_id, store, ext, name)
        db.session.commit()
        return {'synced': len(rows), 'matched': 0, 'store': store}
    return run


def _titles(uid, store):
    return db.session.execute(select(func.count()).select_from(UserOwnedTitle).where(
        UserOwnedTitle.user_id == uid, UserOwnedTitle.store == store)).scalar()


def test_successful_sync_is_recorded_and_reported_connected(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', _fake_sync('gog', [('1', 'A'), ('2', 'B')]))
        client = _client(app, MEMBER)
        response = client.post('/api/ownership/gog/sync')
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body['ok'] is True and body['synced'] == 2 and body['job']['status'] == 'succeeded'
        entry = _state(client, 'gog')
        assert entry['state'] == 'connected' and entry['records']['owned'] == 2
        assert entry['last_sync']['synced'] == 2 and 'sync' in entry['actions']
        assert entry['credential']['source'] == 'member'


def test_failure_is_redacted_and_writes_nothing(app, monkeypatch, settings):
    settings.steam_web_api_key = SECRET
    with app.app_context():
        _link(MEMBER, 'steam', external='76561198000000000')

        def failing(user_id):
            store_ownership_common.upsert_owned_title(user_id, 'steam', '10', 'Staged')
            response = requests.Response()
            response.status_code = 500
            response.url = STEAM_URL
            response.raise_for_status()
        monkeypatch.setattr(store_ownership, 'sync_steam_owned_games', failing)
        client = _client(app, MEMBER)
        response = client.post('/api/ownership/steam/sync')
        assert response.status_code == 502
        assert SECRET not in response.get_data(as_text=True)
        body = response.get_json()
        assert body['error_code'] == 'bad_gateway' and body['detail']['reason'] == 'upstream_unavailable'
        assert body['detail']['action'] == 'retry_later' and body['job']['status'] == 'failed'
        assert _titles(MEMBER, 'steam') == 0, 'a failed sync must not leave staged rows'
        entry = _state(client, 'steam')
        assert entry['state'] == 'failed' and entry['last_sync']['outcome']['reason'] == 'upstream_unavailable'
        assert SECRET not in json.dumps(entry)


def test_rejected_sign_in_needs_reconnect_and_reconnect_clears_it(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "old"}')

        def rejected(user_id):
            raise StoreSyncError('GOG rejected the saved token', 'credential_rejected')
        monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', rejected)
        client = _client(app, MEMBER)
        response = client.post('/api/ownership/gog/sync')
        assert response.status_code == 400 and response.get_json()['detail']['action'] == 'reconnect'
        entry = _state(client, 'gog')
        assert entry['state'] == 'reauth_required' and entry['actions'][0] == 'reconnect'
        assert 'sync' not in entry['actions']
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'acct', credential='{"refresh_token": "new"}')
        entry = _state(client, 'gog')
        assert entry['state'] == 'connected' and entry['last_sync'] is None
        assert entry['previous_failure']['outcome']['reason'] == 'credential_rejected'


def test_cancel_stops_at_the_next_page_and_saves_nothing(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')

        def paged(user_id):
            checkpoint(pages=1, items=50)
            request_cancel(user_id, 'gog')  # what the cancel route does from another request
            checkpoint(pages=1, items=50)
            raise AssertionError('checkpoint should have stopped the sync')
        monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', _fake_sync('gog', [], before_write=paged))
        client = _client(app, MEMBER)
        body = client.post('/api/ownership/gog/sync').get_json()
        assert body['cancelled'] is True and body['job']['status'] == 'cancelled' and body['synced'] == 0
        assert body['job']['progress'] == {'pages': 2, 'items_seen': 100}
        assert _titles(MEMBER, 'gog') == 0
        assert _state(client, 'gog')['state'] == 'cancelled'


def test_cancel_route_is_honest_about_what_can_stop(app, settings):
    settings.steam_web_api_key = 'k'
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        _link(MEMBER, 'steam', external='765')
        client = _client(app, MEMBER)
        assert client.post('/api/ownership/gog/sync/cancel').get_json()['detail']['reason'] == 'nothing_to_cancel'
        _job(MEMBER, 'steam')
        response = client.post('/api/ownership/steam/sync/cancel')
        assert response.status_code == 409 and response.get_json()['detail']['reason'] == 'not_cancellable'
        assert _state(client, 'steam')['actions'] == []
        _job(MEMBER, 'gog')
        assert _state(client, 'gog')['actions'] == ['cancel']
        response = client.post('/api/ownership/gog/sync/cancel')
        assert response.status_code == 202 and response.get_json()['job']['cancel_requested'] is True
        assert _state(client, 'gog')['actions'] == [], 'no second cancel once requested'
        assert client.post('/api/ownership/nintendo/sync/cancel').status_code == 404


def test_a_running_sync_blocks_a_second_one_and_disconnect(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'epic', credential=EPIC_DEVICE)
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        monkeypatch.setattr(store_ownership, 'sync_epic_owned_games', _fake_sync('epic', [('x', 'X')]))
        _job(MEMBER, 'epic')
        _job(MEMBER, 'gog')
        client = _client(app, MEMBER)
        response = client.post('/api/ownership/epic/sync')
        assert response.status_code == 409 and response.get_json()['detail']['reason'] == 'sync_in_progress'
        assert _titles(MEMBER, 'epic') == 0
        response = client.delete('/api/ownership/gog')
        assert response.status_code == 409
        assert db.session.execute(select(StoreAccount.id).where(StoreAccount.user_id == MEMBER, StoreAccount.store == 'gog')).first()


def test_a_lost_sync_reads_as_interrupted_and_does_not_block(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'epic', credential=EPIC_DEVICE)
        _job(MEMBER, 'epic', age=timedelta(hours=1))
        client = _client(app, MEMBER)
        entry = _state(client, 'epic')
        assert entry['state'] == 'failed' and entry['last_sync']['outcome']['reason'] == 'interrupted'
        monkeypatch.setattr(store_ownership, 'sync_epic_owned_games', _fake_sync('epic', [('x', 'X')]))
        assert client.post('/api/ownership/epic/sync').status_code == 200
        statuses = db.session.execute(select(StoreSyncJob.status, StoreSyncJob.reason).where(StoreSyncJob.store == 'epic').order_by(StoreSyncJob.id)).all()
        assert [tuple(s) for s in statuses] == [('failed', 'interrupted'), ('succeeded', None)]


def test_partial_and_warning_outcomes(app, monkeypatch, settings):
    settings.steam_web_api_key = 'k'
    with app.app_context():
        _link(MEMBER, 'epic', credential=EPIC_DEVICE)
        _link(MEMBER, 'steam', external='765')
        monkeypatch.setattr(store_ownership, 'sync_epic_owned_games',
                            _fake_sync('epic', [('x', 'X')], before_write=lambda uid: mark_partial('page_limit')))
        monkeypatch.setattr(store_ownership, 'sync_steam_owned_games',
                            _fake_sync('steam', [], before_write=lambda uid: mark_warning('library_not_visible')))
        client = _client(app, MEMBER)
        assert client.post('/api/ownership/epic/sync').get_json()['job']['status'] == 'partial'
        assert _titles(MEMBER, 'epic') == 1, 'a partial list is still saved'
        entry = _state(client, 'epic')
        assert entry['state'] == 'partial' and entry['last_sync']['outcome']['reason'] == 'page_limit'
        assert client.post('/api/ownership/steam/sync').get_json()['job']['status'] == 'succeeded'
        entry = _state(client, 'steam')
        assert entry['state'] == 'connected' and entry['last_sync']['outcome']['action'] == 'check_privacy'


def test_state_matrix_without_accounts(app, monkeypatch, settings):
    with app.app_context():
        client = _client(app, MEMBER)
        states = {c['provider']: c for c in client.get('/api/ownership/connections').get_json()['connections']}
        assert len(states) == 14
        assert states['humble']['state'] == 'unavailable' and states['humble']['actions'] == []
        assert states['meta_quest']['state'] == 'import_only' and states['meta_quest']['actions'] == ['import_csv']
        assert states['playnite']['actions'] == ['import_file']
        assert states['xbox']['state'] == 'not_configured' and states['xbox']['setup']['missing'] == 'opt_in'
        assert states['steam']['state'] == 'not_configured' and states['steam']['setup']['missing'] == 'server_key'
        # A Steam ID needs no server key (free-game claims use it); only live sync does.
        assert states['steam']['actions'] == ['connect', 'import_csv']
        assert 'connect' not in states['xbox']['actions']
        assert states['gog']['state'] == 'not_connected' and states['gog']['actions'][:1] == ['connect']
        monkeypatch.setenv('ENABLE_UNOFFICIAL_STORE_SYNC', 'xbox')
        monkeypatch.setattr('oneirodex.utils.store_ownership_xbox.client_available', lambda: False)
        xbox = _state(client, 'xbox')
        assert xbox['state'] == 'not_configured' and xbox['setup']['missing'] == 'client_package'
        settings.enable_store_ownership_sync = False
        states = {c['provider']: c['state'] for c in client.get('/api/ownership/connections').get_json()['connections']}
        assert states['gog'] == 'disabled' and states['humble'] == 'unavailable'


def test_credential_source_is_reported_not_revealed(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential=None)
        client = _client(app, MEMBER)
        entry = _state(client, 'gog')
        assert entry['state'] == 'needs_credential' and entry['credential'] == {'source': 'none', 'household_available': False}
        monkeypatch.setenv('GOG_REFRESH_TOKEN', SECRET)
        entry = _state(client, 'gog')
        assert entry['state'] == 'connected' and entry['credential']['source'] == 'household'
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'acct', credential=json.dumps({'refresh_token': SECRET, 'origin': 'household'}))
        assert _state(client, 'gog')['credential']['source'] == 'household', 'a stored household token is still household'
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'acct', credential=json.dumps({'refresh_token': 'mine-' + SECRET}))
        body = client.get('/api/ownership/connections').get_data(as_text=True)
        assert SECRET not in body and '"credential":"' not in body.replace(' ', '')
        assert _state(client, 'gog')['credential']['source'] == 'member'


def test_other_members_jobs_do_not_leak_into_status(app):
    with app.app_context():
        _link(OTHER, 'epic', credential=EPIC_DEVICE)
        _job(OTHER, 'epic', 'failed', reason='credential_rejected', finished=utcnow())
        entry = _state(_client(app, MEMBER), 'epic')
        assert entry['state'] == 'not_connected' and entry['last_sync'] is None


def test_admin_diagnostics_are_redacted_and_admin_only(app, monkeypatch):
    monkeypatch.setenv('EPIC_DEVICE_AUTH', SECRET)
    with app.app_context():
        _link(OTHER, 'epic', credential=json.dumps({'account_id': 'a', 'device_id': 'd', 'secret': SECRET}), external='PrivateGamertag')
        store_ownership_common.upsert_owned_title(OTHER, 'epic', 'cat-1', 'Very Private Title')
        db.session.commit()
        _job(OTHER, 'epic', 'failed', reason='credential_rejected', finished=utcnow())
        assert _client(app, MEMBER).get('/api/admin/ownership/connections').status_code == 302
        response = _client(app, ADMIN).get('/api/admin/ownership/connections')
        assert response.status_code == 200
        text_body = response.get_data(as_text=True)
        for private in (SECRET, 'PrivateGamertag', 'Very Private Title', 'external_account_id'):
            assert private not in text_body
        body = response.get_json()
        assert body['household']['household_tokens']['epic'] is True
        row = next(m for m in body['members'] if m['user_id'] == OTHER)['stores'][0]
        assert row['provider'] == 'epic' and row['state'] == 'reauth_required'
        assert row['credential']['source'] == 'member' and row['admin_actions'] == []
        assert row['records']['owned'] == 1


def test_admin_retry_and_cancel_act_for_the_member(app, monkeypatch):
    with app.app_context():
        _link(OTHER, 'gog', credential='{"refresh_token": "r"}')
        monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', _fake_sync('gog', [('7', 'Seven')]))
        admin = _client(app, ADMIN)
        response = admin.post(f'/api/admin/ownership/connections/{OTHER}/gog/sync')
        assert response.status_code == 200 and response.get_json()['job']['trigger'] == 'admin'
        assert _titles(OTHER, 'gog') == 1 and _titles(ADMIN, 'gog') == 0
        assert admin.post(f'/api/admin/ownership/connections/{MEMBER}/gog/sync').get_json()['detail']['reason'] == 'not_connected'
        assert admin.post('/api/admin/ownership/connections/999/gog/sync').status_code == 404
        _job(OTHER, 'gog')
        assert admin.post(f'/api/admin/ownership/connections/{OTHER}/gog/cancel').status_code == 202
        assert _client(app, MEMBER).post(f'/api/admin/ownership/connections/{OTHER}/gog/cancel').status_code == 302


def test_finished_jobs_are_pruned_per_member_and_store(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        for _ in range(store_sync_jobs.KEEP_JOBS + 5):
            _job(MEMBER, 'gog', 'succeeded', finished=utcnow())
        _job(OTHER, 'gog', 'succeeded', finished=utcnow())
        monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', _fake_sync('gog', []))
        assert _client(app, MEMBER).post('/api/ownership/gog/sync').status_code == 200
        count = lambda uid: db.session.execute(select(func.count()).select_from(StoreSyncJob).where(StoreSyncJob.user_id == uid)).scalar()
        assert count(MEMBER) == store_sync_jobs.KEEP_JOBS and count(OTHER) == 1


def test_member_connections_is_one_contract_for_every_surface(app):
    """first-run, Settings and admin read the same derivation."""
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        member = member_connections(SimpleNamespace(id=MEMBER))
        gog = next(c for c in member['connections'] if c['provider'] == 'gog')
        admin = admin_connections()
        row = next(m for m in admin['members'] if m['user_id'] == MEMBER)['stores'][0]
        for key in ('state', 'live', 'cancellable', 'setup', 'credential', 'records', 'last_sync'):
            assert row[key] == gog[key]


class _Resp:
    def __init__(self, status=200, payload=None, url='https://provider.invalid/x'):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.content = b'{}'
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.url = self.url
            response.raise_for_status()


def _run(uid, store):
    return store_sync_jobs.run_store_sync(uid, store, trigger='member')


def test_gog_invalid_grant_is_a_rejected_sign_in(app, monkeypatch):
    from oneirodex.utils import store_ownership_gog
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "expired"}')
        monkeypatch.setattr(store_ownership_gog, '_outbound', lambda *a, **k: _Resp(400, {'error': 'invalid_grant'}))
        outcome = _run(MEMBER, 'gog')
        assert outcome['job'].status == 'failed' and outcome['reason'] == 'credential_rejected'


def test_gog_missing_names_are_partial_and_household_tokens_stay_labelled(app, monkeypatch):
    from oneirodex.utils import store_ownership_gog
    monkeypatch.setenv('GOG_REFRESH_TOKEN', SECRET)

    def outbound(method, url, **kwargs):
        if 'token' in url:
            return _Resp(200, {'access_token': 'acc', 'refresh_token': 'rotated-' + SECRET})
        if 'user/data/games' in url:
            return _Resp(200, {'owned': [1, 2]})
        raise requests.ConnectionError('names service down')
    monkeypatch.setattr(store_ownership_gog, '_outbound', outbound)
    with app.app_context():
        _link(MEMBER, 'gog', credential=None)
        outcome = _run(MEMBER, 'gog')
        assert outcome['job'].status == 'partial' and outcome['reason'] == 'names_incomplete'
        assert _titles(MEMBER, 'gog') == 2, 'IDs are recorded even without names'
        stored = json.loads(db.session.execute(select(StoreAccount.credential).where(StoreAccount.user_id == MEMBER)).scalar())
        assert stored['origin'] == 'household'
        assert _state(_client(app, MEMBER), 'gog')['credential']['source'] == 'household'


def test_epic_page_cap_is_reported_partial(app, monkeypatch):
    from oneirodex.utils import store_ownership_epic
    pages = []

    def outbound(method, url, **kwargs):
        if 'oauth/token' in url:
            return _Resp(200, {'access_token': 'acc', 'displayName': 'EpicName'})
        pages.append(1)
        return _Resp(200, {'records': [{'catalogItemId': f'c{len(pages)}', 'title': 'T'}],
                           'responseMetadata': {'nextCursor': f'cursor{len(pages)}'}})
    monkeypatch.setattr(store_ownership_epic, '_outbound', outbound)
    with app.app_context():
        _link(MEMBER, 'epic', credential=json.dumps({'account_id': 'a', 'device_id': 'd', 'secret': 's'}))
        outcome = _run(MEMBER, 'epic')
        assert len(pages) == store_ownership_epic._EPIC_MAX_PAGES
        assert outcome['job'].status == 'partial' and outcome['reason'] == 'page_limit'
        assert outcome['job'].pages == store_ownership_epic._EPIC_MAX_PAGES
        assert _titles(MEMBER, 'epic') == store_ownership_epic._EPIC_MAX_PAGES


def test_amazon_repeated_page_token_ends_as_partial(app, monkeypatch):
    from oneirodex.utils import store_ownership_amazon
    calls = []

    def outbound(method, url, **kwargs):
        if 'auth/token' in url:
            return _Resp(200, {'access_token': 'acc'})
        calls.append(1)
        return _Resp(200, {'entitlements': [{'product': {'id': f'amzn1.adg.product.{len(calls):036d}', 'title': 'T'}}],
                           'nextToken': 'same-token'})
    monkeypatch.setattr(store_ownership_amazon, '_outbound', outbound)
    with app.app_context():
        _link(MEMBER, 'amazon', credential=json.dumps({'refresh_token': 'r', 'device_serial': 'serial'}))
        outcome = _run(MEMBER, 'amazon')
        assert len(calls) == 2, 'the loop stops when a page token repeats'
        assert outcome['job'].status == 'partial' and outcome['reason'] == 'page_limit'
        ids = db.session.execute(select(UserOwnedTitle.external_app_id).where(UserOwnedTitle.store == 'amazon')).scalars().all()
        assert all(len(i) > 32 for i in ids), 'long product IDs are stored whole'


@pytest.mark.parametrize('status,reason', [(500, 'upstream_unavailable'), (429, 'rate_limited'), (403, 'access_denied')])
def test_steam_failures_never_carry_the_server_key(app, monkeypatch, settings, status, reason):
    settings.steam_web_api_key = SECRET
    monkeypatch.setattr(store_ownership, '_outbound', lambda *a, **k: _Resp(status, url=STEAM_URL))
    with app.app_context():
        _link(MEMBER, 'steam', external='765')
        response = _client(app, MEMBER).post('/api/ownership/steam/sync')
        assert SECRET not in response.get_data(as_text=True)
        assert response.get_json()['detail']['reason'] == reason


def test_steam_private_library_is_a_warning_not_an_empty_success(app, monkeypatch, settings):
    settings.steam_web_api_key = 'k'
    monkeypatch.setattr(store_ownership, '_outbound', lambda *a, **k: _Resp(200, {'response': {}}))
    with app.app_context():
        _link(MEMBER, 'steam', external='765')
        outcome = _run(MEMBER, 'steam')
        assert outcome['job'].status == 'succeeded' and outcome['reason'] == 'library_not_visible'
        monkeypatch.setattr(store_ownership, '_outbound', lambda *a, **k: _Resp(200, {'response': {'game_count': 0}}))
        assert _run(MEMBER, 'steam')['reason'] is None, 'a visible empty library is just empty'


def test_xbox_keeps_the_operator_client_pair_out_of_member_rows(app, monkeypatch):
    from oneirodex.utils import store_ownership_xbox
    monkeypatch.setenv('ENABLE_UNOFFICIAL_STORE_SYNC', 'xbox')
    monkeypatch.setenv('XBOX_TOKENS_JSON', json.dumps({'oauth': {'refresh_token': 'household'}}))
    monkeypatch.setenv('XBOX_CLIENT_ID', 'operator-app')
    monkeypatch.setenv('XBOX_CLIENT_SECRET', SECRET)
    monkeypatch.setattr(store_ownership_xbox, 'client_available', lambda: True)
    with app.app_context():
        _link(MEMBER, 'xbox', credential=None)
        account = db.session.execute(select(StoreAccount).where(StoreAccount.store == 'xbox')).scalar_one()
        tokens = store_ownership_xbox._tokens_for(account)
        assert tokens['origin'] == 'household'
        stored = store_ownership_xbox._stored_tokens(tokens, {'refresh_token': 'rotated'}, '2533')
        assert SECRET not in json.dumps(stored) and 'client_id' not in stored and stored['origin'] == 'household'
        mine = store_ownership_xbox._stored_tokens({'client_id': 'mine', 'client_secret': 'mine-s'}, {}, '1')
        assert mine['client_id'] == 'mine' and mine['client_secret'] == 'mine-s' and 'origin' not in mine
        # End to end through the job runner, with the provider call faked.
        monkeypatch.setattr(store_ownership_xbox, '_xbox_title_history',
                            lambda t: ([('1234', 'Halo')], store_ownership_xbox._stored_tokens(t, {'refresh_token': 'r2'}, '2533')))
        assert _run(MEMBER, 'xbox')['job'].status == 'succeeded'
        saved = db.session.execute(select(StoreAccount.credential).where(StoreAccount.store == 'xbox')).scalar()
        assert SECRET not in saved and json.loads(saved)['origin'] == 'household'
        assert _state(_client(app, MEMBER), 'xbox')['credential']['source'] == 'household'


# --- Review findings (LIB-04 adversarial review) -----------------------------

def test_a_refused_household_sign_in_is_the_operators_to_fix_and_is_superseded_when_replaced(app, monkeypatch):
    from oneirodex.utils import store_ownership_gog
    monkeypatch.setenv('GOG_REFRESH_TOKEN', 'household-old')
    refreshes = []

    def outbound(method, url, **kwargs):
        if 'token' in url:
            refreshes.append(kwargs['data']['refresh_token'])
            if kwargs['data']['refresh_token'] != 'household-new':
                return _Resp(400, {'error': 'invalid_grant'})
            return _Resp(200, {'access_token': 'acc', 'refresh_token': 'household-new-rotated'})
        if 'user/data/games' in url:
            return _Resp(200, {'owned': [1]})
        return _Resp(200, [{'id': 1, 'title': 'One'}])
    monkeypatch.setattr(store_ownership_gog, '_outbound', outbound)
    with app.app_context():
        _link(MEMBER, 'gog', credential=json.dumps({'refresh_token': 'household-old-rotated', 'origin': 'household',
                                                    'household_fp': store_ownership_common.household_fp('household-old')}))
        outcome = _run(MEMBER, 'gog')
        assert outcome['reason'] == 'household_credential_rejected'
        client = _client(app, MEMBER)
        entry = _state(client, 'gog')
        assert entry['state'] == 'failed' and 'sync' in entry['actions']
        assert entry['last_sync']['outcome']['audience'] == 'admin'
        admin_row = next(m for m in admin_connections()['members'] if m['user_id'] == MEMBER)['stores'][0]
        assert admin_row['admin_actions'] == ['sync']
        # The operator replaces the household token: the stale copy is dropped, not reused.
        monkeypatch.setenv('GOG_REFRESH_TOKEN', 'household-new')
        assert _run(MEMBER, 'gog')['job'].status == 'succeeded'
        assert refreshes[-1] == 'household-new'


def test_an_incomplete_member_credential_never_falls_back_to_the_household_account(app, monkeypatch):
    from oneirodex.utils import store_ownership_epic
    monkeypatch.setenv('EPIC_DEVICE_AUTH', json.dumps({'account_id': 'HOUSE', 'device_id': 'd', 'secret': 's'}))
    called = []
    monkeypatch.setattr(store_ownership_epic, '_outbound', lambda *a, **k: called.append(1) or _Resp(200, {}))
    with app.app_context():
        _link(MEMBER, 'epic', credential=json.dumps({'account_id': 'MINE', 'access_token': 'legendary-user-json'}))
        entry = _state(_client(app, MEMBER), 'epic')
        assert entry['credential']['source'] == 'none' and entry['state'] == 'needs_credential'
        assert _run(MEMBER, 'epic')['reason'] == 'credential_missing'
        assert called == [], 'the household device auth must not be used'


def test_amazon_household_access_token_is_reported_and_serial_has_its_own_reason(app, monkeypatch):
    from oneirodex.utils import store_ownership_amazon
    monkeypatch.setenv('AMAZON_ACCESS_TOKEN', 'house-access')
    monkeypatch.setenv('AMAZON_DEVICE_SERIAL', 'house-serial')
    with app.app_context():
        _link(MEMBER, 'amazon', credential=None)
        entry = _state(_client(app, MEMBER), 'amazon')
        assert entry['credential'] == {'source': 'household', 'household_available': True}
        # A member's own token is never paired with the household serial.
        store_ownership_amazon.connect_amazon_account(MEMBER, refresh_token='mine')
        assert _run(MEMBER, 'amazon')['reason'] == 'device_serial_missing'
        assert _state(_client(app, MEMBER), 'amazon')['state'] == 'reauth_required'
        # Reconnecting with only the serial keeps the saved token.
        store_ownership_amazon.connect_amazon_account(MEMBER, device_serial='my-serial')
        saved = json.loads(db.session.execute(select(StoreAccount.credential).where(StoreAccount.store == 'amazon')).scalar())
        assert saved == {'refresh_token': 'mine', 'device_serial': 'my-serial'}
        assert _state(_client(app, MEMBER), 'amazon')['state'] == 'connected'


@pytest.mark.parametrize('store, body', [
    ('amazon', {'credential': {'refresh_token': 'r', 'device_serial': 's', 'origin': 'household', 'household_fp': 'x'}}),
    ('xbox', {'credential': {'oauth': {'refresh_token': 'r'}, 'origin': 'household'}}),
    ('epic', {'device_auth': {'account_id': 'a', 'device_id': 'd', 'secret': 's', 'origin': 'household'}}),
])
def test_members_cannot_tag_their_own_credential_as_household(app, store, body):
    from importlib import import_module
    module = import_module(f'oneirodex.utils.store_ownership_{store}')
    connect = getattr(module, f'connect_{store}_account')
    with app.app_context():
        connect(MEMBER, **body)
        stored = json.loads(db.session.execute(select(StoreAccount.credential).where(StoreAccount.store == store)).scalar())
        assert 'origin' not in stored and 'household_fp' not in stored
        assert _state(_client(app, MEMBER), store)['credential']['source'] in ('member', 'none')


def test_xbox_rows_holding_the_operator_pair_heal_on_the_next_sync(app, monkeypatch):
    from oneirodex.utils import store_ownership_xbox
    monkeypatch.setenv('XBOX_CLIENT_ID', 'OPERATOR-ID')
    monkeypatch.setenv('XBOX_CLIENT_SECRET', SECRET)
    legacy = {'oauth': {'refresh_token': 'r'}, 'client_id': 'OPERATOR-ID', 'client_secret': SECRET}
    stored = store_ownership_xbox._stored_tokens(legacy, {'refresh_token': 'r2'}, 'x')
    assert 'client_id' not in stored and 'client_secret' not in stored


def test_unofficial_stores_without_opt_in_say_so(app):
    with app.app_context():
        _link(MEMBER, 'xbox', credential='{"oauth": {}}')
        entry = _state(_client(app, MEMBER), 'xbox')
        assert entry['state'] == 'not_configured' and entry['setup'] == {'ready': False, 'missing': 'opt_in'}
        assert entry['actions'] == ['import_csv', 'disconnect']


def test_a_running_sync_stays_visible_and_cancellable_when_sync_is_turned_off(app, settings):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        _job(MEMBER, 'gog')
        settings.enable_store_ownership_sync = False
        entry = _state(_client(app, MEMBER), 'gog')
        assert entry['state'] == 'syncing' and entry['actions'] == ['cancel']


def test_only_a_real_reconnect_clears_a_refused_sign_in(app):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "old"}')
        _job(MEMBER, 'gog', 'failed', reason='credential_rejected', finished=utcnow())
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'a new label')  # no new token
        assert _state(_client(app, MEMBER), 'gog')['state'] == 'reauth_required'
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'a new label', credential='{"refresh_token": "new"}')
        assert _state(_client(app, MEMBER), 'gog')['state'] == 'connected'


def test_upstream_failures_are_not_cleared_by_a_reconnect_but_fixed_configuration_is(app, settings):
    with app.app_context():
        _link(MEMBER, 'epic', credential=json.dumps({'account_id': 'a', 'device_id': 'd', 'secret': 's'}))
        _job(MEMBER, 'epic', 'failed', reason='rate_limited', finished=utcnow())
        store_ownership_common.connect_store_account(MEMBER, 'epic', None, credential=json.dumps({'account_id': 'a', 'device_id': 'd', 'secret': 't'}))
        assert _state(_client(app, MEMBER), 'epic')['state'] == 'failed'
        _link(MEMBER, 'steam', external='765')
        _job(MEMBER, 'steam', 'failed', reason='server_key_missing', finished=utcnow())
        assert _state(_client(app, MEMBER), 'steam')['state'] == 'not_configured'
        settings.steam_web_api_key = 'now-configured'
        entry = _state(_client(app, MEMBER), 'steam')
        assert entry['state'] == 'connected' and entry['previous_failure']['outcome']['reason'] == 'server_key_missing'


def test_disconnect_clears_history_so_a_new_link_starts_clean(app, monkeypatch):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        _job(MEMBER, 'gog', 'succeeded', finished=utcnow())
        client = _client(app, MEMBER)
        assert client.delete('/api/ownership/gog').status_code == 200
        assert db.session.execute(select(func.count()).select_from(StoreSyncJob)).scalar() == 0
        store_ownership_common.connect_store_account(MEMBER, 'gog', None, credential='{"refresh_token": "r2"}')
        entry = _state(client, 'gog')
        assert entry['state'] == 'connected' and entry['last_sync'] is None


def test_history_from_an_earlier_link_is_ignored(app):
    with app.app_context():
        _job(MEMBER, 'gog', 'succeeded', age=timedelta(hours=2), finished=utcnow() - timedelta(hours=2))
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}', created=utcnow())
        assert _state(_client(app, MEMBER), 'gog')['last_sync'] is None


def test_link_changes_and_syncs_never_overlap(app):
    from oneirodex.utils.store_sync_errors import SyncOutcomeError
    from oneirodex.utils.store_sync_jobs import exclusive_link_change
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')
        seen = {}

        def during_disconnect():
            # A sync trying to start while the disconnect holds the slot is refused.
            with pytest.raises(SyncOutcomeError) as busy:
                store_sync_jobs.run_store_sync(MEMBER, 'gog', trigger='schedule', sync_fn=lambda uid: {})
            seen['reason'] = busy.value.reason
        exclusive_link_change(MEMBER, 'gog', 'disconnect', during_disconnect, clear_history=True)
        assert seen['reason'] == 'store_busy'
        _job(MEMBER, 'gog')
        with pytest.raises(SyncOutcomeError) as running:
            exclusive_link_change(MEMBER, 'gog', 'connect', lambda: None)
        assert running.value.reason == 'sync_in_progress'


def test_a_linked_steam_id_can_be_changed_without_a_server_key(app):
    with app.app_context():
        _link(MEMBER, 'steam', external='765')
        steam = _state(_client(app, MEMBER), 'steam')
        assert steam['state'] == 'not_configured' and steam['actions'] == ['reconnect', 'import_csv', 'disconnect']


def test_a_sign_in_saved_before_the_upgrade_is_not_claimed_as_the_members_own(app, monkeypatch):
    """Before LIB-04, GOG / Amazon / Xbox wrote the household token they had
    used onto the member's account, untagged. The migration leaves updated_at
    NULL, so on a server with a household sign-in such a copy is 'unknown'."""
    with app.app_context():
        db.session.add(StoreAccount(user_id=MEMBER, store='gog', external_account_id='acct',
                                    credential=json.dumps({'refresh_token': 'rotated-long-ago'}),
                                    created_at=utcnow() - timedelta(days=30), updated_at=None))
        db.session.commit()
        client = _client(app, MEMBER)
        assert _state(client, 'gog')['credential']['source'] == 'member', 'no household sign-in: nothing to confuse it with'
        monkeypatch.setenv('GOG_REFRESH_TOKEN', SECRET)
        entry = _state(client, 'gog')
        assert entry['credential']['source'] == 'unknown' and entry['state'] == 'connected'
        admin = _client(app, ADMIN).get('/api/admin/ownership/connections').get_json()
        assert any(s['credential']['source'] == 'unknown' for m in admin['members'] for s in m['stores'])
        # Reconnecting with the member's own sign-in settles it.
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'acct', credential=json.dumps({'refresh_token': 'mine'}))
        assert _state(client, 'gog')['credential']['source'] == 'member'


def test_link_time_is_utc_whatever_the_database_time_zone(app):
    """A tz-aware created_at was shifted to the PostgreSQL session time zone,
    so on a server east of UTC a fresh link hid its first jobs for hours."""
    with app.app_context():
        if db.engine.dialect.name != 'postgresql':
            pytest.skip('PostgreSQL time zone conversion')
        db.session.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))
        store_ownership_common.connect_store_account(MEMBER, 'gog', 'acct', credential=json.dumps({'refresh_token': 'r'}))
        created = db.session.execute(select(StoreAccount.created_at).filter_by(user_id=MEMBER, store='gog')).scalar()
        assert abs(created - utcnow()) < timedelta(minutes=5)
        job_id = _job(MEMBER, 'gog', 'failed', reason='credential_rejected', finished=utcnow())
        entry = _state(_client(app, MEMBER), 'gog')
        assert entry['last_sync']['id'] == job_id and entry['state'] == 'reauth_required'


def test_the_poller_survives_a_job_deleted_while_it_runs(app, monkeypatch):
    """A disconnect during a cycle deletes that store's jobs; the poller used to
    read the expired, deleted row and end the cycle for everyone after it."""
    from oneirodex.utils import ownership_poller
    monkeypatch.setattr(store_ownership, 'get_steam_web_api_key', lambda: 'k')
    monkeypatch.setattr(store_ownership, 'gog_live_ready', lambda: True)
    monkeypatch.setattr(store_ownership, 'epic_live_ready', lambda: False)
    monkeypatch.setattr(store_ownership, 'amazon_live_ready', lambda: False)
    calls = []

    def steam(uid):
        calls.append(('steam', uid))
        # What another request's exclusive_link_change(clear_history=True) commits.
        db.session.execute(sa_delete(StoreSyncJob).where(StoreSyncJob.user_id == OTHER, StoreSyncJob.store == 'gog')
                           .execution_options(synchronize_session=False))
        db.session.commit()
        return {'synced': 0, 'matched': 0}

    def gog(uid):
        calls.append(('gog', uid))
        return {'synced': 0, 'matched': 0}

    monkeypatch.setattr(store_ownership, 'sync_steam_owned_games', steam)
    monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', gog)
    with app.app_context():
        _link(MEMBER, 'steam', external='765')
        _link(OTHER, 'gog', credential='{"refresh_token": "r"}')
        _job(MEMBER, 'steam', 'succeeded', finished=utcnow())
        _job(OTHER, 'gog', 'succeeded', finished=utcnow())
        result = ownership_poller.sync_all_linked_accounts()
        assert calls == [('steam', MEMBER), ('gog', OTHER)]
        assert result['synced'] == 2


def test_one_members_unexpected_error_does_not_end_the_cycle(app, monkeypatch):
    from oneirodex.utils import ownership_poller
    monkeypatch.setattr(store_ownership, 'get_steam_web_api_key', lambda: 'k')
    monkeypatch.setattr(store_ownership, 'gog_live_ready', lambda: True)
    monkeypatch.setattr(store_ownership, 'epic_live_ready', lambda: False)
    monkeypatch.setattr(store_ownership, 'amazon_live_ready', lambda: False)
    real_run = store_sync_jobs.run_store_sync

    def run(user_id, store, **kwargs):
        if user_id == MEMBER:
            raise RuntimeError('SELECT ... token=' + SECRET)
        return real_run(user_id, store, **kwargs)

    monkeypatch.setattr(store_sync_jobs, 'run_store_sync', run)
    monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', lambda uid: {'synced': 0, 'matched': 0})
    with app.app_context():
        _link(MEMBER, 'steam', external='765')
        _link(OTHER, 'gog', credential='{"refresh_token": "r"}')
        result = ownership_poller.sync_all_linked_accounts()
        assert result['failed'] == 1 and result['synced'] == 1


def _as_another_request(fn, *args, **kwargs):
    """Run ``fn`` as a concurrent request would: same app, no running sync of its own."""
    def run():
        store_sync_jobs._current.set(None)
        return fn(*args, **kwargs)
    return contextvars.copy_context().run(run)


def test_a_sync_taken_over_while_quiet_cannot_write_titles_back(app):
    """A job silent past STALE_AFTER is expired by the next link change. The old
    worker may still be alive: its commit is refused, not published."""
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')

        def slow_sync(uid):
            job_id = store_sync_jobs._current.get().job_id
            db.session.execute(update(StoreSyncJob).where(StoreSyncJob.id == job_id).values(
                heartbeat_at=utcnow() - timedelta(minutes=11)))
            db.session.commit()
            # The member disconnects meanwhile, from another request; the link
            # change takes the slot.
            _as_another_request(
                store_sync_jobs.exclusive_link_change, uid, 'gog', 'disconnect',
                lambda: store_ownership_common.disconnect_store_account(uid, 'gog'), clear_history=True)
            store_ownership_common.upsert_owned_title(uid, 'gog', '123', 'Game')
            db.session.commit()
            return {'synced': 1, 'matched': 0}

        outcome = store_sync_jobs.run_store_sync(MEMBER, 'gog', trigger='member', actor_id=MEMBER, sync_fn=slow_sync)
        assert outcome['job'].status == 'failed' and outcome['reason'] == 'interrupted'
        titles = db.session.execute(select(func.count()).select_from(UserOwnedTitle).where(
            UserOwnedTitle.user_id == MEMBER)).scalar()
        assert titles == 0
        assert db.session.execute(select(StoreAccount).filter_by(user_id=MEMBER, store='gog')).scalar() is None
        assert db.session.execute(select(func.count()).select_from(StoreSyncJob)).scalar() == 0


def test_a_sync_expired_by_a_newer_one_keeps_the_interrupted_record(app):
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')

        def quiet_then_write(uid):
            job_id = store_sync_jobs._current.get().job_id
            db.session.execute(update(StoreSyncJob).where(StoreSyncJob.id == job_id).values(
                heartbeat_at=utcnow() - timedelta(minutes=11)))
            db.session.commit()
            # A newer sync's start (another request) expires this one.
            _as_another_request(store_sync_jobs._expire_stale, uid, 'gog')
            store_ownership_common.upsert_owned_title(uid, 'gog', '123', 'Game')
            db.session.commit()

        outcome = store_sync_jobs.run_store_sync(MEMBER, 'gog', trigger='member', sync_fn=quiet_then_write)
        assert outcome['job'].status == 'failed' and outcome['job'].reason == 'interrupted'
        assert db.session.execute(select(func.count()).select_from(UserOwnedTitle)).scalar() == 0


def test_a_takeover_after_the_last_commit_reports_interrupted_not_an_internal_error(app):
    """The fence lets a commit through that won the row lock; a takeover that
    lands after it marks the job interrupted. The sync says so."""
    from oneirodex.utils.store_sync_jobs import job_dict
    with app.app_context():
        _link(MEMBER, 'gog', credential='{"refresh_token": "r"}')

        def commit_then_taken_over(uid):
            store_ownership_common.upsert_owned_title(uid, 'gog', '123', 'Game')
            db.session.commit()
            job_id = store_sync_jobs._current.get().job_id
            db.session.execute(update(StoreSyncJob).where(StoreSyncJob.id == job_id).values(
                heartbeat_at=utcnow() - timedelta(minutes=11)))
            db.session.commit()
            _as_another_request(store_sync_jobs._expire_stale, uid, 'gog')
            return {'synced': 1, 'matched': 0}

        outcome = store_sync_jobs.run_store_sync(MEMBER, 'gog', trigger='member', sync_fn=commit_then_taken_over)
        assert outcome['reason'] == 'interrupted' and outcome['job'].status == 'failed' and outcome['result'] is None
        # Removed by a disconnect instead: the stand-in still names the store.
        _link(OTHER, 'gog', credential='{"refresh_token": "r"}')

        def disconnected_after_commit(uid):
            db.session.commit()
            _as_another_request(
                db.session.execute, sa_delete(StoreSyncJob).where(StoreSyncJob.user_id == uid)
                .execution_options(synchronize_session=False))
            _as_another_request(db.session.commit)
            return {'synced': 0, 'matched': 0}

        outcome = store_sync_jobs.run_store_sync(OTHER, 'gog', trigger='member', sync_fn=disconnected_after_commit)
        view = job_dict(outcome['job'])
        assert outcome['reason'] == 'interrupted' and view['store'] == 'gog' and 'GOG' in view['outcome']['message']
