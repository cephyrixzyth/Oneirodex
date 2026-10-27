"""Wave 9–11 — member Library batch favorite, freshness, status, wishlist APIs."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User, UserLibraryAccess
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def member_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'BatchMember_{uid[:8]}',
        email=f'batch_member_{uid[:8]}@test.com',
        role='user',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def child_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'BatchChild_{uid[:8]}',
        email=f'batch_child_{uid[:8]}@test.com',
        role='child',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'BatchAdmin_{uid[:8]}',
        email=f'batch_admin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def library(db_session):
    lib = Library(name=f'BatchLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


@pytest.fixture
def other_library(db_session):
    lib = Library(name=f'BatchOther_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _unique_igdb_id() -> int:
    """Avoid unique(igdb_id) collisions on a dirty oneirodextest DB."""
    return 100001 + (uuid4().int % 900000)


def _make_game(db_session, library, name=None, **kwargs):
    game = Game(
        name=name or f'Batch Game {uuid4().hex[:6]}',
        full_disk_path=f'/tmp/batch_{uuid4().hex}',
        library_uuid=library.uuid,
        **kwargs,
    )
    db_session.add(game)
    db_session.commit()
    return game


def test_batch_favorite_requires_login(client):
    resp = client.post('/api/games/batch/favorite', json={'uuids': [], 'favorite': True})
    assert resp.status_code in (401, 302)


def test_batch_favorite_add_and_remove(client, db_session, member_user, library):
    g1 = _make_game(db_session, library, 'Fav A')
    g2 = _make_game(db_session, library, 'Fav B')
    _login(client, member_user)

    add = client.post(
        '/api/games/batch/favorite',
        json={'uuids': [g1.uuid, g2.uuid], 'favorite': True},
    )
    assert add.status_code == 200
    body = add.get_json()
    assert body['ok'] is True
    assert body['count'] == 2
    assert {row['uuid'] for row in body['updated']} == {g1.uuid, g2.uuid}
    assert body['skipped'] == []
    assert body['errors'] == []
    assert body['limit'] == 100

    db_session.refresh(member_user)
    fav_uuids = {g.uuid for g in member_user.favorites}
    assert g1.uuid in fav_uuids and g2.uuid in fav_uuids

    # Idempotent: already_set skipped
    again = client.post(
        '/api/games/batch/favorite',
        json={'uuids': [g1.uuid], 'favorite': True},
    )
    assert again.status_code == 200
    again_body = again.get_json()
    assert again_body['updated'] == []
    assert again_body['skipped'] == [{'uuid': g1.uuid, 'reason': 'already_set'}]

    remove = client.post(
        '/api/games/batch/favorite',
        json={'uuids': [g1.uuid, g2.uuid], 'favorite': False},
    )
    assert remove.status_code == 200
    rem = remove.get_json()
    assert rem['ok'] is True
    assert rem['count'] == 2
    db_session.refresh(member_user)
    assert {g.uuid for g in member_user.favorites} == set()


def test_batch_favorite_skips_not_found_and_forbidden(
    client, db_session, child_user, library, other_library
):
    allowed = _make_game(db_session, library, 'Allowed Fav')
    blocked = _make_game(db_session, other_library, 'Blocked Fav')
    db_session.add(UserLibraryAccess(user_id=child_user.id, library_uuid=library.uuid))
    db_session.commit()
    _login(client, child_user)

    missing = str(uuid4())
    resp = client.post(
        '/api/games/batch/favorite',
        json={'uuids': [allowed.uuid, blocked.uuid, missing], 'favorite': True},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['updated'] == [{'uuid': allowed.uuid, 'favorite': True}]
    reasons = {row['uuid']: row['reason'] for row in body['skipped']}
    assert reasons[blocked.uuid] == 'forbidden'
    assert reasons[missing] == 'not_found'


def test_batch_favorite_rejects_over_limit(client, member_user):
    _login(client, member_user)
    uuids = [str(uuid4()) for _ in range(101)]
    resp = client.post(
        '/api/games/batch/favorite',
        json={'uuids': uuids, 'favorite': True},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['limit'] == 100
    assert body['requested'] == 101


def test_batch_freshness_check_partial_success(
    client, db_session, member_user, library, monkeypatch
):
    fresh = _make_game(
        db_session,
        library,
        'Fresh Title',
        freshness_status='current',
        freshness_checked_at=datetime.now(timezone.utc),
    )
    stale = _make_game(
        db_session,
        library,
        'Stale Title',
        freshness_status='behind',
        freshness_checked_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    never = _make_game(db_session, library, 'Never Checked')

    calls = []

    def fake_check(game, *, commit=False, db_session=None):
        calls.append(game.uuid)
        return {'status': 'current', 'confidence': 'low'}

    monkeypatch.setattr(
        'oneirodex.utils.freshness.check_and_store_freshness',
        fake_check,
    )
    _login(client, member_user)

    missing = str(uuid4())
    resp = client.post(
        '/api/games/batch/freshness/check',
        json={'uuids': [fresh.uuid, stale.uuid, never.uuid, missing], 'only_stale': True},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['limit'] == 50
    assert body['only_stale'] is True
    updated_uuids = {row['uuid'] for row in body['updated']}
    assert updated_uuids == {stale.uuid, never.uuid}
    assert set(calls) == {stale.uuid, never.uuid}
    reasons = {row['uuid']: row['reason'] for row in body['skipped']}
    assert reasons[fresh.uuid] == 'fresh'
    assert reasons[missing] == 'not_found'


def test_batch_freshness_respects_acl(
    client, db_session, child_user, library, other_library, monkeypatch
):
    allowed = _make_game(db_session, library, 'Child OK')
    blocked = _make_game(db_session, other_library, 'Child No')
    db_session.add(UserLibraryAccess(user_id=child_user.id, library_uuid=library.uuid))
    db_session.commit()

    monkeypatch.setattr(
        'oneirodex.utils.freshness.check_and_store_freshness',
        lambda game, **kw: {'status': 'current', 'confidence': 'low'},
    )
    _login(client, child_user)

    resp = client.post(
        '/api/games/batch/freshness/check',
        json={'uuids': [allowed.uuid, blocked.uuid], 'only_stale': False},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert [row['uuid'] for row in body['updated']] == [allowed.uuid]
    assert body['skipped'] == [{'uuid': blocked.uuid, 'reason': 'forbidden'}]


def test_batch_freshness_rejects_over_limit(client, member_user):
    _login(client, member_user)
    resp = client.post(
        '/api/games/batch/freshness/check',
        json={'uuids': [str(uuid4()) for _ in range(51)]},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['limit'] == 50


def test_batch_freshness_rejects_oversized_json_before_processing(client, member_user):
    from oneirodex.routes_apis.game_batch import BATCH_FRESHNESS_JSON_MAX_BYTES

    _login(client, member_user)
    body = b'{"uuids":[],"padding":"' + b'a' * BATCH_FRESHNESS_JSON_MAX_BYTES + b'"}'
    resp = client.post(
        '/api/games/batch/freshness/check', data=body,
        content_type='application/json',
    )

    assert resp.status_code == 413
    assert resp.get_json()['error_code'] == 'payload_too_large'


def test_admin_freshness_refresh_still_works(client, db_session, admin_user, library, monkeypatch):
    """Regression: admin library-wide bulk must remain available."""
    game = _make_game(
        db_session,
        library,
        'Admin Bulk',
        freshness_status=None,
        freshness_checked_at=None,
    )
    monkeypatch.setattr(
        'oneirodex.utils.freshness.check_and_store_freshness',
        lambda g, **kw: {'status': 'current', 'confidence': 'low'},
    )
    _login(client, admin_user)
    resp = client.post(
        '/api/admin/freshness/refresh',
        json={'limit': 10, 'only_stale': True, 'library_uuid': library.uuid},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['count'] >= 1
    assert any(row['uuid'] == game.uuid for row in body['updated'])


def test_updates_inbox_advertises_member_batch(client, member_user):
    _login(client, member_user)
    resp = client.get('/api/updates/inbox?limit=5')
    assert resp.status_code == 200
    fc = resp.get_json()['freshness_check']
    assert fc['batch_member'] == 'POST /api/games/batch/freshness/check'
    assert fc['batch_member_limit'] == 50
    assert fc['bulk_admin'] == 'POST /api/admin/freshness/refresh'


# --- Wave 11: batch play status + wishlist ---------------------------------


def test_batch_status_set_clear_and_idempotent(client, db_session, member_user, library):
    from oneirodex.models import user_game_status
    from sqlalchemy import and_, select

    g1 = _make_game(db_session, library, 'Status A')
    g2 = _make_game(db_session, library, 'Status B')
    _login(client, member_user)

    set_resp = client.post(
        '/api/games/batch/status',
        json={'uuids': [g1.uuid, g2.uuid], 'status': 'beaten'},
    )
    assert set_resp.status_code == 200
    body = set_resp.get_json()
    assert body['ok'] is True
    assert body['count'] == 2
    assert body['limit'] == 100
    assert body['status'] == 'beaten'
    assert {row['uuid'] for row in body['updated']} == {g1.uuid, g2.uuid}
    assert body['skipped'] == []
    assert body['errors'] == []

    rows = {
        r[0]: r[1]
        for r in db_session.execute(
            select(user_game_status.c.game_uuid, user_game_status.c.status).where(
                and_(
                    user_game_status.c.user_id == member_user.id,
                    user_game_status.c.game_uuid.in_([g1.uuid, g2.uuid]),
                )
            )
        ).all()
    }
    assert rows == {g1.uuid: 'beaten', g2.uuid: 'beaten'}

    again = client.post(
        '/api/games/batch/status',
        json={'uuids': [g1.uuid], 'status': 'beaten'},
    )
    assert again.status_code == 200
    again_body = again.get_json()
    assert again_body['updated'] == []
    assert again_body['skipped'] == [{'uuid': g1.uuid, 'reason': 'already_set'}]

    clear = client.post(
        '/api/games/batch/status',
        json={'uuids': [g1.uuid, g2.uuid], 'status': ''},
    )
    assert clear.status_code == 200
    cleared = clear.get_json()
    assert cleared['ok'] is True
    assert cleared['count'] == 2
    assert cleared['status'] is None
    remaining = db_session.execute(
        select(user_game_status.c.game_uuid).where(
            and_(
                user_game_status.c.user_id == member_user.id,
                user_game_status.c.game_uuid.in_([g1.uuid, g2.uuid]),
            )
        )
    ).scalars().all()
    assert list(remaining) == []


def test_batch_status_skips_not_found_and_forbidden(
    client, db_session, child_user, library, other_library
):
    allowed = _make_game(db_session, library, 'Status Allowed')
    blocked = _make_game(db_session, other_library, 'Status Blocked')
    db_session.add(UserLibraryAccess(user_id=child_user.id, library_uuid=library.uuid))
    db_session.commit()
    _login(client, child_user)

    missing = str(uuid4())
    resp = client.post(
        '/api/games/batch/status',
        json={'uuids': [allowed.uuid, blocked.uuid, missing], 'status': 'unplayed'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['updated'] == [{'uuid': allowed.uuid, 'status': 'unplayed'}]
    reasons = {row['uuid']: row['reason'] for row in body['skipped']}
    assert reasons[blocked.uuid] == 'forbidden'
    assert reasons[missing] == 'not_found'


def test_batch_status_rejects_invalid_and_over_limit(client, member_user):
    _login(client, member_user)

    bad = client.post(
        '/api/games/batch/status',
        json={'uuids': [str(uuid4())], 'status': 'platinum'},
    )
    assert bad.status_code == 400
    assert bad.get_json()['ok'] is False

    over = client.post(
        '/api/games/batch/status',
        json={'uuids': [str(uuid4()) for _ in range(101)], 'status': 'completed'},
    )
    assert over.status_code == 400
    body = over.get_json()
    assert body['ok'] is False
    assert body['limit'] == 100
    assert body['requested'] == 101


def test_batch_wishlist_add_and_skip_duplicates(client, db_session, member_user, library):
    from oneirodex.models import GameRequest

    g1 = _make_game(db_session, library, 'Wish A')
    g2 = _make_game(db_session, library, 'Wish B')
    _login(client, member_user)

    add = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [g1.uuid, g2.uuid]},
    )
    assert add.status_code == 200
    body = add.get_json()
    assert body['ok'] is True
    assert body['count'] == 2
    assert body['limit'] == 50
    assert {row['uuid'] for row in body['updated']} == {g1.uuid, g2.uuid}
    assert all(row['status'] == 'pending' for row in body['updated'])
    assert body['skipped'] == []

    rows = db_session.query(GameRequest).filter_by(user_id=member_user.id, status='pending').all()
    by_uuid = {r.linked_game_uuid: r for r in rows}
    assert by_uuid[g1.uuid].title == 'Wish A'
    assert by_uuid[g2.uuid].title == 'Wish B'

    again = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [g1.uuid]},
    )
    assert again.status_code == 200
    again_body = again.get_json()
    assert again_body['updated'] == []
    assert again_body['skipped'] == [{'uuid': g1.uuid, 'reason': 'already_pending'}]


def test_batch_wishlist_blocks_child(client, db_session, child_user, library):
    game = _make_game(db_session, library, 'Wish Child Block')
    db_session.add(UserLibraryAccess(user_id=child_user.id, library_uuid=library.uuid))
    db_session.commit()
    _login(client, child_user)

    blocked_child = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [game.uuid]},
    )
    assert blocked_child.status_code == 403
    assert blocked_child.get_json()['ok'] is False


def test_batch_wishlist_skips_not_found(client, db_session, member_user, library):
    game = _make_game(db_session, library, 'Wish Found')
    _login(client, member_user)

    missing = str(uuid4())
    resp = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [game.uuid, missing]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert [row['uuid'] for row in body['updated']] == [game.uuid]
    assert body['skipped'] == [{'uuid': missing, 'reason': 'not_found'}]


def test_batch_wishlist_forbidden_acl_and_over_limit(
    client, db_session, member_user, library, other_library, monkeypatch
):
    """ACL skip uses user_can_access_game; over-limit is 400."""
    allowed = _make_game(db_session, library, 'Wish ACL OK')
    blocked = _make_game(db_session, other_library, 'Wish ACL No')
    _login(client, member_user)

    from oneirodex.utils import library_acl

    real_acl = library_acl.user_can_access_game

    def fake_acl(user, game):
        if game is not None and game.uuid == blocked.uuid:
            return False
        return real_acl(user, game)

    monkeypatch.setattr('oneirodex.routes_apis.game_batch.user_can_access_game', fake_acl)

    resp = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [allowed.uuid, blocked.uuid]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert [row['uuid'] for row in body['updated']] == [allowed.uuid]
    assert body['skipped'] == [{'uuid': blocked.uuid, 'reason': 'forbidden'}]

    over = client.post(
        '/api/games/batch/wishlist',
        json={'uuids': [str(uuid4()) for _ in range(51)]},
    )
    assert over.status_code == 400
    assert over.get_json()['limit'] == 50


# --- Wave 12: batch refresh images (librarian+) ---------------------------------


@pytest.fixture
def librarian_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'BatchLib_{uid[:8]}',
        email=f'batch_lib_{uid[:8]}@test.com',
        role='librarian',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_batch_refresh_images_requires_login(client):
    resp = client.post('/api/games/batch/refresh_images', json={'uuids': []})
    assert resp.status_code in (401, 302)


def test_batch_refresh_images_forbids_regular_user(client, member_user, library, db_session):
    game = _make_game(db_session, library, 'Refresh Member Block', igdb_id=_unique_igdb_id())
    _login(client, member_user)
    resp = client.post(
        '/api/games/batch/refresh_images',
        json={'uuids': [game.uuid]},
    )
    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Librarian or admin required'


def test_batch_refresh_images_rejects_empty_and_over_limit(client, librarian_user):
    _login(client, librarian_user)

    missing = client.post('/api/games/batch/refresh_images', json={})
    assert missing.status_code == 400
    assert missing.get_json()['ok'] is False

    not_list = client.post('/api/games/batch/refresh_images', json={'uuids': 'nope'})
    assert not_list.status_code == 400
    assert not_list.get_json()['ok'] is False

    over = client.post(
        '/api/games/batch/refresh_images',
        json={'uuids': [str(uuid4()) for _ in range(21)]},
    )
    assert over.status_code == 400
    body = over.get_json()
    assert body['ok'] is False
    assert body['limit'] == 20
    assert body['requested'] == 21


def test_batch_refresh_images_queues_happy_path(
    client, db_session, librarian_user, library, monkeypatch
):
    with_igdb = _make_game(db_session, library, 'Refresh Queue', igdb_id=_unique_igdb_id())
    no_igdb = _make_game(db_session, library, 'Refresh No IGDB', igdb_id=None)

    started = []

    # The route hands work to run_in_background now, which owns the thread and
    # the worker's session (utils/background.py). Intercepting there keeps this
    # test about *what gets queued* without starting real threads.
    def fake_run_in_background(app, func, *args, name=None, **kwargs):
        started.append((func, args))
        return None

    monkeypatch.setattr(
        'oneirodex.routes_apis.game_batch.run_in_background', fake_run_in_background
    )
    monkeypatch.setattr(
        'oneirodex.routes_apis.game_batch.refresh_images_in_background',
        lambda game_uuid: None,
    )
    _login(client, librarian_user)

    resp = client.post(
        '/api/games/batch/refresh_images',
        json={'uuids': [with_igdb.uuid, no_igdb.uuid]},
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body['ok'] is True
    assert body['limit'] == 20
    assert body['requested'] == 2
    assert body['count'] == 1
    assert body['errors'] == []
    assert body['queued'] == [
        {'uuid': with_igdb.uuid, 'name': 'Refresh Queue', 'status': 'queued'},
    ]
    assert body['skipped'] == [
        {'uuid': no_igdb.uuid, 'reason': 'no_igdb_id', 'name': 'Refresh No IGDB'},
    ]
    # One worker, for the game that has an igdb_id. Asserting the argument as
    # well as the count: the response says what it *intends* to queue, this
    # says what was actually handed to the worker.
    assert len(started) == 1
    queued_func, queued_args = started[0]
    assert queued_args == (with_igdb.uuid,)


def test_batch_refresh_images_skips_not_found_and_forbidden(
    client, db_session, librarian_user, library, monkeypatch
):
    allowed = _make_game(db_session, library, 'Refresh Allowed', igdb_id=_unique_igdb_id())
    blocked = _make_game(db_session, library, 'Refresh Blocked', igdb_id=_unique_igdb_id())
    _login(client, librarian_user)

    from oneirodex.utils import library_acl

    real_acl = library_acl.user_can_access_game

    def fake_acl(user, game):
        if game is not None and game.uuid == blocked.uuid:
            return False
        return real_acl(user, game)

    monkeypatch.setattr('oneirodex.routes_apis.game_batch.user_can_access_game', fake_acl)
    monkeypatch.setattr(
        'oneirodex.routes_apis.game_batch.run_in_background',
        lambda app, func, *args, name=None, **kwargs: None,
    )

    missing = str(uuid4())
    resp = client.post(
        '/api/games/batch/refresh_images',
        json={'uuids': [allowed.uuid, blocked.uuid, missing]},
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body['ok'] is True
    assert body['queued'] == [
        {'uuid': allowed.uuid, 'name': 'Refresh Allowed', 'status': 'queued'},
    ]
    reasons = {row['uuid']: row['reason'] for row in body['skipped']}
    assert reasons[blocked.uuid] == 'forbidden'
    assert reasons[missing] == 'not_found'
    assert body['errors'] == []
