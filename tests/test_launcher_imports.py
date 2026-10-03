"""Launcher import framework and sync-all (register-only ownership)."""
import json
from io import BytesIO
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import GlobalSettings, StoreAccount, User, UserOwnedTitle
from oneirodex.utils.launcher_imports import detect_format, parse_export


def _person(db_session):
    uid = str(uuid4())
    row = User(name=f'li_{uid[:8]}', email=f'li_{uid[:8]}@example.com', role='user', user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, person):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(person.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(person)


def _enable(db_session):
    row = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
    if row is None:
        row = GlobalSettings()
        db_session.add(row)
    row.enable_store_ownership_sync = True
    db_session.commit()


HEROIC = {'library': [
    {'app_name': 'Sugar', 'title': 'Celeste', 'runner': 'legendary'},
    {'app_name': '1207658930', 'title': 'Hades', 'runner': 'gog'},
]}
LUTRIS = [{'id': 4, 'slug': 'doom-2016', 'name': 'DOOM', 'runner': 'linux', 'platform': 'Linux'}]
GALAXY = {'games': [{'title': 'Witcher 3', 'platform': 'gog', 'releaseKey': 'gog_1207664643'}]}
PLAYNITE = [{'Id': 'abc-1', 'Name': 'Portal'}]


@pytest.mark.parametrize('data, key', [
    (HEROIC, 'heroic'), (LUTRIS, 'lutris'), (GALAXY, 'galaxy'), (PLAYNITE, 'playnite'),
])
def test_each_export_is_recognised(data, key):
    assert detect_format(data).key == key


def test_heroic_ids_are_namespaced_per_runner():
    fmt, titles = parse_export(json.dumps(HEROIC))
    assert fmt.store == 'heroic'
    assert {(t.external_id, t.name) for t in titles} == {
        ('legendary:Sugar', 'Celeste'), ('gog:1207658930', 'Hades'),
    }


def test_generic_csv_needs_a_name_column_and_reads_ids():
    fmt, titles = parse_export('Title,AppId\nTetris,t1\nChess,\n', filename='x.csv')
    assert fmt.key == 'import'
    assert [(t.external_id, t.name) for t in titles] == [('t1', 'Tetris'), ('Chess', 'Chess')]
    with pytest.raises(ValueError, match='Name or Title'):
        parse_export('Foo,Bar\n1,2\n', filename='x.csv')


@pytest.mark.parametrize('text', ['', '{not json', '[]'])
def test_unreadable_exports_raise_member_safe_errors(text):
    with pytest.raises(ValueError):
        parse_export(text)


def test_unknown_launcher_hint_is_rejected():
    with pytest.raises(ValueError, match='Unknown launcher'):
        parse_export('[]', launcher='nope')


def test_import_route_records_titles_idempotently(client, app, db_session):
    _enable(db_session)
    member = _person(db_session)
    _login(client, app, member)
    first = client.post('/api/imports/launcher', json=HEROIC).get_json()
    assert first['ok'] and (first['launcher'], first['imported'], first['updated']) == ('heroic', 2, 0)
    again = client.post('/api/imports/launcher', json=HEROIC).get_json()
    assert (again['imported'], again['updated']) == (0, 2)
    rows = db_session.execute(select(UserOwnedTitle).filter_by(user_id=member.id, store='heroic')).scalars().all()
    assert len(rows) == 2


def test_import_route_accepts_a_file_and_a_launcher_hint(client, app, db_session):
    _enable(db_session)
    member = _person(db_session)
    _login(client, app, member)
    response = client.post(
        '/api/imports/launcher',
        data={'file': (BytesIO(b'Name,Id\nPong,p1\n'), 'games.csv'), 'launcher': 'lutris'},
        content_type='multipart/form-data',
    )
    body = response.get_json()
    assert response.status_code == 200 and body['launcher'] == 'lutris' and body['imported'] == 1


def test_import_route_refuses_bad_input_and_disabled_sync(client, app, db_session):
    _enable(db_session)
    member = _person(db_session)
    _login(client, app, member)
    assert client.post('/api/imports/launcher', json={'games': []}).status_code == 400
    assert client.post('/api/imports/launcher', json=HEROIC, query_string={'launcher': 'bogus'}).status_code == 400
    row = db_session.execute(select(GlobalSettings).limit(1)).scalars().first()
    row.enable_store_ownership_sync = False
    db_session.commit()
    assert client.post('/api/imports/launcher', json=HEROIC).status_code == 403


def test_launcher_list_and_providers_include_import_sources(client, app, db_session):
    _enable(db_session)
    _login(client, app, _person(db_session))
    ids = [row['id'] for row in client.get('/api/imports/launchers').get_json()['launchers']]
    assert ids == ['heroic', 'lutris', 'galaxy', 'playnite', 'import']
    providers = {p['id']: p for p in client.get('/api/ownership/providers').get_json()['providers']}
    assert providers['heroic']['capabilities']['file_import'] == 'heroic_export'


def test_sync_all_runs_linked_stores_and_reports_the_rest(client, app, db_session, monkeypatch):
    from oneirodex.utils import store_ownership
    _enable(db_session)
    member = _person(db_session)
    db_session.add(StoreAccount(user_id=member.id, store='gog', credential='{}'))
    db_session.commit()
    monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', lambda user_id: {'synced': 3, 'matched': 1})
    _login(client, app, member)
    body = client.post('/api/ownership/sync-all').get_json()
    by_store = {r['store']: r for r in body['results']}
    assert by_store['gog']['status'] == 'succeeded' and by_store['gog']['synced'] == 3
    assert by_store['steam'] == {'store': 'steam', 'status': 'skipped', 'reason': 'not_connected'}


def test_sync_all_isolates_a_failing_store(client, app, db_session, monkeypatch):
    from oneirodex.utils import store_ownership
    _enable(db_session)
    member = _person(db_session)
    db_session.add_all([StoreAccount(user_id=member.id, store='gog', credential='{}'),
                        StoreAccount(user_id=member.id, store='epic', credential='{}')])
    db_session.commit()

    def boom(user_id):
        raise RuntimeError('secret-token-leak')

    monkeypatch.setattr(store_ownership, 'sync_gog_owned_games', boom)
    monkeypatch.setattr(store_ownership, 'sync_epic_owned_games', lambda user_id: {'synced': 2, 'matched': 0})
    _login(client, app, member)
    raw = client.post('/api/ownership/sync-all').get_data(as_text=True)
    assert 'secret-token-leak' not in raw
    by_store = {r['store']: r for r in json.loads(raw)['results']}
    assert by_store['gog']['status'] == 'failed'
    assert by_store['epic']['status'] == 'succeeded'
