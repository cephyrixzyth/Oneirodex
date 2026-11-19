"""Library ACL (child allow-list) unit + API tests."""

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, GameCollection, GameCollectionItem, Library, User
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


def test_child_collection_owner_sees_only_currently_allowed_games(
    app, client, db_session, child, libs,
):
    allowed_library, denied_library = libs
    set_user_library_allowlist(child.id, [allowed_library.uuid])
    allowed_game = Game(
        name='Visible Shelf Game', library_uuid=allowed_library.uuid,
        full_disk_path='/tmp/' + uuid4().hex,
    )
    denied_game = Game(
        name='Hidden Shelf Game', library_uuid=denied_library.uuid,
        full_disk_path='/tmp/' + uuid4().hex,
    )
    db_session.add_all([allowed_game, denied_game])
    db_session.flush()
    collection = GameCollection(
        name='Owned shelf', owner_user_id=child.id, is_public=True,
    )
    db_session.add(collection)
    db_session.flush()
    db_session.add_all([
        GameCollectionItem(collection_id=collection.id, game_uuid=allowed_game.uuid),
        GameCollectionItem(collection_id=collection.id, game_uuid=denied_game.uuid),
    ])
    db_session.commit()
    _login(client, app, child)

    listed = client.get('/api/collections')
    detail = client.get(f'/api/collections/{collection.uuid}')
    updated = client.patch(
        f'/api/collections/{collection.uuid}', json={'name': 'Renamed shelf'},
    )

    assert listed.status_code == 200
    owned_row = next(
        row for row in listed.get_json()['collections']
        if row['uuid'] == collection.uuid
    )
    assert owned_row['item_count'] == 1
    for response in (detail, updated):
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['item_count'] == 1
        assert [item['game_name'] for item in payload['items']] == ['Visible Shelf Game']


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


def test_profile_totals_and_recency_follow_the_viewers_catalog(app, db_session, child, adult, libs):
    from datetime import datetime, timedelta
    from oneirodex.models import UserFriendship, UserGameProgress
    from oneirodex.runtime_native.social_reads import SocialReadData

    kids, adults = libs
    set_user_library_allowlist(child.id, [kids.uuid])
    db_session.add(UserFriendship(user_id=child.id, friend_user_id=adult.id, status='accepted'))
    for index in range(54):
        game = Game(name=f'Title {index}', library_uuid=kids.uuid if index < 13 else adults.uuid,
                    full_disk_path=f'/tmp/{uuid4().hex}')
        db_session.add(game)
        db_session.flush()
        for member in (child, adult):
            db_session.add(UserGameProgress(user_id=member.id, game_uuid=game.uuid, total_seconds=index + 1,
                                           last_played_at=datetime(2026, 1, 1) + timedelta(days=index)))
    db_session.commit()
    reads = SocialReadData()
    profile = reads.profile(child, adult.id, app)
    assert profile['total_seconds'] == sum(range(1, 14))
    assert [g['game_name'] for g in profile['recent_games']] == [f'Title {n}' for n in range(12, 0, -1)]
    shared, status = reads.profile_compare(child, adult.id, child.id)
    assert status == 200
    assert [g['game_name'] for g in shared['shared_games']] == [f'Title {n}' for n in range(12, -1, -1)]
