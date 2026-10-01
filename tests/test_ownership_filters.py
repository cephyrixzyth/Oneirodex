"""Execute ownership predicates against an isolated in-memory relational fixture.

Only predicate columns are needed; no app/global configuration or live DB access.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from werkzeug.datastructures import MultiDict

from oneirodex.models import Game
from oneirodex.utils.ownership_filters import apply_ownership_filters


@pytest.fixture
def connection():
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.exec_driver_sql('CREATE TABLE games (uuid TEXT, library_uuid TEXT)')
        conn.exec_driver_sql('CREATE TABLE user_owned_titles (id INTEGER, user_id INTEGER, store TEXT, matched_game_uuid TEXT)')
        conn.exec_driver_sql("INSERT INTO games VALUES ('both', 'visible'), ('steam', 'visible'), ('other-user', 'visible'), ('unknown', 'visible'), ('hidden', 'private')")
        conn.exec_driver_sql("INSERT INTO user_owned_titles VALUES (1,1,'steam','both'), (2,1,'gog','both'), (3,1,'steam','steam'), (4,2,'gog','other-user'), (5,1,'steam','hidden'), (6,1,'steam','both'), (7,1,'gog',NULL)")
        yield conn
    engine.dispose()


@pytest.mark.parametrize('params,expected', [
    ({}, {'both', 'steam', 'other-user', 'unknown'}),
    ({'store': 'steam'}, {'both', 'steam'}),
    ({'store': 'steam,gog', 'store_match': 'any'}, {'both', 'steam'}),
    ({'store': 'steam,gog', 'store_match': 'all'}, {'both'}),
    ({'ownership': 'owned'}, {'both', 'steam'}),
    ({'ownership': 'unrecorded'}, {'other-user', 'unknown'}),
    ({'store': 'gog', 'ownership': 'unrecorded'}, {'steam', 'other-user', 'unknown'}),
    ({'store': 'steam,gog', 'store_match': 'all', 'ownership': 'unrecorded'}, {'other-user', 'unknown'}),
    ({'store': 'unknown-provider'}, set()),
    ({'ownership': 'not-owned'}, set()),
    ({'store_match': 'invalid'}, set()),
    (MultiDict([('store','steam'), ('store','gog'), ('store_match','all')]), {'both'}),
])
def test_member_scope_union_intersection_and_acl_preservation(connection, params, expected):
    # The surrounding browse query supplies its existing library/content ACL.
    query = select(Game.uuid).where(Game.library_uuid == 'visible')
    query = apply_ownership_filters(query, params, user=SimpleNamespace(id=1, is_authenticated=True))
    query.compile(dialect=postgresql.dialect())
    assert set(connection.execute(query).scalars()) == expected


def test_anonymous_filter_never_reads_other_members(connection):
    query = apply_ownership_filters(select(Game.uuid), {'ownership':'owned'}, user=None)
    assert list(connection.execute(query).scalars()) == []


def test_shared_browse_filter_wires_store_predicate(connection):
    from oneirodex.utils.browse_filters import apply_badge_filters
    query = select(Game.uuid).where(Game.library_uuid == 'visible')
    query = apply_badge_filters(query, {'store':'gog'}, user=SimpleNamespace(id=1, is_authenticated=True))
    assert list(connection.execute(query).scalars()) == ['both']
