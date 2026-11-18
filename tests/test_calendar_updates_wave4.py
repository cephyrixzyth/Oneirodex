"""Calendar + updates inbox Wave 4 (P1-11 light) API tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'CalAdmin_{uid[:8]}',
        email=f'cal_admin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'CalMember_{uid[:8]}',
        email=f'cal_member_{uid[:8]}@test.com',
        role='user',
        is_email_verified=True,
        state=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def library(db_session):
    lib = Library(name=f'CalLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_calendar_empty_when_igdb_off(client, admin_user, monkeypatch):
    _login(client, admin_user)

    def boom(**kwargs):
        return []

    monkeypatch.setattr(
        'oneirodex.utils.release_calendar.fetch_release_calendar',
        boom,
    )
    resp = client.get('/api/calendar?days_ahead=30&days_behind=7&limit=10')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['count'] == 0
    assert body['releases'] == []
    assert body['days_ahead'] == 30
    assert body['days_behind'] == 7
    assert body['limit'] == 10
    assert body['generated_at']
    assert body['source'] == 'igdb'


def test_calendar_rejects_non_integer_window(client, admin_user):
    _login(client, admin_user)
    resp = client.get('/api/calendar?days_ahead=nope')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['error'] == 'Invalid query parameters'
    assert body['error_code'] == 'bad_request'


def test_calendar_igdb_error_dict_returns_empty_200(client, admin_user, monkeypatch):
    """make_igdb_api_request error dict must not 500/502 the hub."""
    _login(client, admin_user)

    monkeypatch.setattr(
        'oneirodex.utils.release_calendar.make_igdb_api_request',
        lambda *a, **k: {'error': 'IGDB settings not configured in database'},
    )
    resp = client.get('/api/calendar')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['releases'] == []
    assert body['count'] == 0


def test_updates_inbox_includes_generated_at(client, db_session, member_user, library):
    game = Game(
        name=f'Stale Inbox {uuid4().hex[:6]}',
        full_disk_path='/definitely/not/a/real/path_' + uuid4().hex,
        library_uuid=library.uuid,
        freshness_status='behind',
        freshness_checked_at=datetime.now(timezone.utc),
    )
    db_session.add(game)
    db_session.commit()

    _login(client, member_user)
    resp = client.get('/api/updates/inbox?limit=20')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert 'generated_at' in payload
    assert payload['generated_at']
    assert payload['limit'] == 20
    assert payload['count'] >= 1
    assert 'freshness_check' in payload
    assert 'freshness/check' in payload['freshness_check']['single']
    assert any(item['name'] == game.name for item in payload['items'])
