"""Isolated route/model and migration verification; never load the app factory."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask
from flask_login import LoginManager, UserMixin
import pytest
from sqlalchemy import create_engine, inspect, select, text

from oneirodex import db
from oneirodex.models import Game, OwnershipMatchDecision, UserOwnedTitle
from oneirodex.utils import ownership_review

A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'
HIDDEN = '00000000-0000-0000-0000-000000000003'


def test_database_url():
    value = os.environ.get('P03_TEST_DATABASE_URL')
    if value:
        from database_test_guard import validate_test_database_url
        from sqlalchemy.engine import make_url
        validate_test_database_url(value)
        assert make_url(value).host == '127.0.0.1'
    return value or 'sqlite://'

test_database_url.__test__ = False


@pytest.fixture
def client(monkeypatch):
    from oneirodex.routes_apis import ownership
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI=test_database_url())
    db.init_app(app)
    class Member(UserMixin):
        id = 1
    login = LoginManager(app)
    login.user_loader(lambda uid: Member() if uid == '1' else None)
    app.add_url_rule('/match/<int:title_id>', view_func=ownership.review_ownership_match, methods=['POST'])
    app.add_url_rule('/undo/<int:title_id>', view_func=ownership.undo_ownership_match, methods=['POST'])
    app.add_url_rule('/titles', view_func=ownership.ownership_review_titles)
    app.add_url_rule('/candidates/<int:title_id>', view_func=ownership.ownership_match_candidates)
    monkeypatch.setattr(ownership_review, 'apply_game_access_filters', lambda q, user: q.where(Game.uuid != HIDDEN))
    with app.app_context():
        with db.engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE games (uuid VARCHAR(36) PRIMARY KEY, name TEXT, library_uuid VARCHAR(36))')
            conn.exec_driver_sql('CREATE TABLE libraries (uuid VARCHAR(36) PRIMARY KEY, platform VARCHAR(32))')
            conn.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            conn.execute(text("INSERT INTO games VALUES (:a, 'Same title', 'lib'), (:b, 'Same title', 'lib'), (:h, 'Same title', 'lib')"), dict(a=A,b=B,h=HIDDEN))
            conn.exec_driver_sql("INSERT INTO libraries VALUES ('lib', 'PCWIN')")
            conn.exec_driver_sql('INSERT INTO users VALUES (1), (2)')
        UserOwnedTitle.__table__.create(db.engine)
        OwnershipMatchDecision.__table__.create(db.engine)
        db.session.add_all([
            UserOwnedTitle(id=1,user_id=1,store='steam',external_app_id='1',name='Same title',matched_game_uuid=A),
            UserOwnedTitle(id=2,user_id=2,store='steam',external_app_id='1',matched_game_uuid=A),
        ])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = '1'
            session['_fresh'] = True
        yield client
        db.session.remove()
        with db.engine.begin() as conn:
            for name in ('ownership_match_decisions','user_owned_titles','games','libraries','users'):
                conn.exec_driver_sql('DROP TABLE '+name)


def test_review_undo_and_stale_retry(client):
    response = client.post('/match/1', json={'game_uuid':B,'expected_revision':0})
    assert response.status_code == 200
    assert response.json['match_revision'] == 1
    assert client.post('/match/1',json={'game_uuid':A,'expected_revision':0}).status_code == 409
    response = client.post('/undo/1',json={'expected_revision':1})
    assert response.status_code == 200 and response.json['matched_game_uuid'] == A
    assert client.post('/undo/1',json={'expected_revision':2}).status_code == 409
    rows = db.session.execute(select(OwnershipMatchDecision).order_by(OwnershipMatchDecision.revision)).scalars().all()
    assert [(r.before_uuid,r.after_uuid,r.action,r.actor_id) for r in rows] == [(A,B,'review',1),(B,A,'undo',1)]


@pytest.mark.parametrize('path,payload,code', [
    ('/match/2',{'game_uuid':B,'expected_revision':0},404),
    ('/match/1',{'game_uuid':HIDDEN,'expected_revision':0},404),
    ('/match/1',{'game_uuid':'invalid','expected_revision':0},400),
    ('/match/1',{'game_uuid':B,'expected_revision':True},400),
    ('/match/1',{'expected_revision':0},400),
    ('/undo/1',{'expected_revision':0},409),
])
def test_bad_or_unauthorized_decision_does_not_write(client,path,payload,code):
    assert client.post(path,json=payload).status_code == code
    assert db.session.execute(select(OwnershipMatchDecision)).scalars().all() == []
    assert db.session.get(UserOwnedTitle,1).matched_game_uuid == A


def test_clear_stays_cleared_during_sync(client, monkeypatch):
    from oneirodex.utils import store_ownership_common
    assert client.post('/match/1',json={'game_uuid':None,'expected_revision':0}).status_code == 200
    monkeypatch.setattr(store_ownership_common,'match_title_to_library_game',lambda *args:B)
    row = store_ownership_common.upsert_owned_title(1,'steam','1','renamed')
    db.session.commit()
    assert row.matched_game_uuid is None and row.match_reviewed is True


def test_playnite_repeat_import_preserves_reviewed_clear(client, monkeypatch):
    from oneirodex.utils import playnite_import
    row = db.session.get(UserOwnedTitle,1)
    row.store = 'playnite'
    db.session.commit()
    assert client.post('/match/1',json={'game_uuid':None,'expected_revision':0}).status_code == 200
    monkeypatch.setattr(playnite_import,'_match_game_by_name',lambda name:SimpleNamespace(uuid=B))
    playnite_import.import_playnite_json(1,[{'Id':'1','Name':'Changed title'}])
    assert db.session.get(UserOwnedTitle,1).matched_game_uuid is None


def test_login_required(client):
    with client.session_transaction() as session:
        session.clear()
    assert client.post('/match/1',json={'game_uuid':B,'expected_revision':0}).status_code == 401


def test_list_is_owner_scoped_and_redacts_hidden_mapping(client):
    row = db.session.get(UserOwnedTitle,1)
    row.matched_game_uuid = HIDDEN
    db.session.commit()
    response = client.get('/titles')
    assert response.status_code == 200
    assert [r['id'] for r in response.json['titles']] == [1]
    assert response.json['titles'][0]['matched_game_uuid'] is None
    assert client.get('/titles?after_id=1').json['titles'] == []
    assert client.get('/titles?after_id=-1').status_code == 400


def test_candidates_keep_distinct_editions_and_hide_inaccessible_games(client):
    result = client.get('/candidates/1').json
    assert {r['game_uuid'] for r in result['candidates']} == {A,B}
    assert all(r['requires_review'] and r['platform'] == 'PCWIN' for r in result['candidates'])
    assert client.get('/candidates/2').status_code == 404


@pytest.mark.skipif(not os.environ.get('P03_TEST_DATABASE_URL'),reason='PostgreSQL concurrency acceptance')
def test_concurrent_reviews_have_one_winner(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    app = client.application
    def review(target):
        with app.test_client() as worker:
            with worker.session_transaction() as session:
                session['_user_id'] = '1'
            barrier.wait(timeout=10)
            return worker.post('/match/1',json={'game_uuid':target,'expected_revision':0}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(review,[A,B])) == [200,409]


def test_migration_roundtrip_preserves_existing_match():
    path = Path(__file__).resolve().parents[1]/'alembic/versions/d4e5f6a7b8c9_add_ownership_match_decisions.py'
    spec = importlib.util.spec_from_file_location('ownership_migration',path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(test_database_url())
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('CREATE TABLE user_owned_titles (id INTEGER PRIMARY KEY, matched_game_uuid VARCHAR(36))')
        conn.execute(text('INSERT INTO user_owned_titles VALUES (1, :a)'),dict(a=A))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        migration.upgrade()
        assert conn.exec_driver_sql('SELECT matched_game_uuid, match_revision, match_reviewed FROM user_owned_titles').one() == (A,0,0)
        migration.downgrade()
        assert conn.exec_driver_sql('SELECT matched_game_uuid FROM user_owned_titles').scalar() == A
        assert not inspect(conn).has_table('ownership_match_decisions')
        migration.upgrade()
        assert inspect(conn).has_table('ownership_match_decisions')
        migration.downgrade()
        conn.exec_driver_sql('DROP TABLE user_owned_titles')
        conn.exec_driver_sql('DROP TABLE users')
    engine.dispose()


def test_list_filters_by_review_status_and_names_the_visible_match(client):
    """LIB-02 review UI: needs_review / matched filters, and the current match's name and platform."""
    db.session.add(UserOwnedTitle(id=3, user_id=1, store='gog', external_app_id='9', name='Unmatched'))
    db.session.add(UserOwnedTitle(id=4, user_id=1, store='gog', external_app_id='10', name='Kept apart', match_reviewed=True))
    db.session.commit()
    needs = client.get('/titles?status=needs_review').json['titles']
    assert [t['id'] for t in needs] == [3]
    matched = client.get('/titles?status=matched').json['titles']
    assert [t['id'] for t in matched] == [1]
    assert matched[0]['matched_game'] == {'name': 'Same title', 'platform': 'PCWIN'}
    assert client.get('/titles?status=bogus').status_code == 400
    row = db.session.get(UserOwnedTitle, 1)
    row.matched_game_uuid = HIDDEN
    db.session.commit()
    hidden = client.get('/titles?status=matched').json['titles'][0]
    assert hidden['matched_game'] is None and hidden['matched_game_uuid'] is None
    # Still a match, flagged so the review does not call it "needs review".
    assert hidden['match_hidden'] is True
    assert matched[0]['match_hidden'] is False
