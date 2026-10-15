"""Library ACL (child allow-list) unit + API tests."""

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_acl import (
    allowed_library_uuids,
    apply_game_library_acl,
    set_user_library_allowlist,
    user_can_access_game,
    user_can_access_library,
)
from sqlalchemy import select
from oneirodex.models import Game as GameModel


@pytest.fixture
def libs(db_session):
    a = Library(name=f'Kids_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    b = Library(name=f'Adult_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([a, b])
    db_session.commit()
    return a, b


@pytest.fixture
def child(db_session):
    uid = str(uuid4())
    user = User(
        name=f'aclchild_{uid[:8]}',
        email=f'aclchild_{uid[:8]}@example.com',
        role='child',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def adult(db_session):
    uid = str(uuid4())
    user = User(
        name=f'acluser_{uid[:8]}',
        email=f'acluser_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_child_empty_allowlist_blocks_all(db_session, child, libs, adult):
    kids, _adult_lib = libs
    assert allowed_library_uuids(child) == set()
    assert not user_can_access_library(child, kids.uuid)
    assert allowed_library_uuids(adult) is None


def test_child_allowlist_and_query(db_session, child, libs, adult):
    kids, adult_lib = libs
    set_user_library_allowlist(child.id, [kids.uuid])
    db_session.commit()

    g1 = Game(name='Kid Game', library_uuid=kids.uuid, full_disk_path='/tmp/' + uuid4().hex)
    g2 = Game(name='Adult Game', library_uuid=adult_lib.uuid, full_disk_path='/tmp/' + uuid4().hex)
    db_session.add_all([g1, g2])
    db_session.commit()

    assert user_can_access_game(child, g1)
    assert not user_can_access_game(child, g2)
    assert user_can_access_game(adult, g2)

    q = apply_game_library_acl(select(GameModel), child)
    names = {g.name for g in db_session.execute(q).scalars().all()}
    assert 'Kid Game' in names
    assert 'Adult Game' not in names


def test_get_libraries_respects_acl(client, app, db_session, child, libs):
    kids, adult_lib = libs
    set_user_library_allowlist(child.id, [kids.uuid])
    db_session.commit()
    _login(client, app, child)
    with client:
        resp = client.get('/api/get_libraries')
        assert resp.status_code == 200
        uuids = {row['uuid'] for row in resp.get_json()}
        assert kids.uuid in uuids
        assert adult_lib.uuid not in uuids


def test_search_and_details_blocked(client, app, db_session, child, libs):
    kids, adult_lib = libs
    set_user_library_allowlist(child.id, [kids.uuid])
    db_session.commit()
    blocked = Game(
        name='Secret Title XYZ',
        library_uuid=adult_lib.uuid,
        full_disk_path='/tmp/' + uuid4().hex,
    )
    db_session.add(blocked)
    db_session.commit()

    _login(client, app, child)
    with client:
        search = client.get('/api/search?query=Secret')
        assert search.status_code == 200
        assert search.get_json() == []

        details = client.get(f'/game_details/{blocked.uuid}')
        assert details.status_code == 403

        download = client.get(f'/download_game/{blocked.uuid}')
        assert download.status_code == 405
        blocked_download = client.post(f'/download_game/{blocked.uuid}')
        assert blocked_download.status_code == 403
