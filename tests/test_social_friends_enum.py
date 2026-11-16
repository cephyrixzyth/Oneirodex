"""Friend request anti-enumeration (bug-triage O9)."""

from uuid import uuid4

import pytest

from oneirodex.models import User, UserFriendship


@pytest.fixture
def social_users(db_session):
    tag = uuid4().hex[:8]
    alice = User(
        name=f'alice-{tag}',
        email=f'alice-{tag}@example.com',
        password_hash='unused',
        role='user',
        user_id=str(uuid4()),
        avatarpath='newstyle/avatar_default.jpg',
    )
    bob = User(
        name=f'bob-{tag}',
        email=f'bob-{tag}@example.com',
        password_hash='unused',
        role='user',
        user_id=str(uuid4()),
        avatarpath='newstyle/avatar_default.jpg',
    )
    db_session.add_all([alice, bob])
    db_session.commit()
    return alice, bob


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_friend_request_unknown_user_is_opaque(client, social_users):
    alice, _bob = social_users
    _login(client, alice)

    response = client.post(
        '/api/social/friends',
        json={'username': 'definitely-not-a-real-user-xyz'},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data.get('sent') is False
    assert 'exists' in (data.get('message') or '').lower()
    assert 'not found' not in (data.get('message') or '').lower()


def test_friend_request_blocked_user_is_opaque(client, social_users, db_session):
    alice, bob = social_users
    db_session.add(
        UserFriendship(user_id=alice.id, friend_user_id=bob.id, status='blocked')
    )
    db_session.commit()
    _login(client, alice)

    response = client.post('/api/social/friends', json={'username': bob.name})
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True
    assert data.get('sent') is False


def test_friend_request_real_user_still_sends(client, social_users):
    alice, bob = social_users
    _login(client, alice)

    response = client.post('/api/social/friends', json={'username': bob.name})
    assert response.status_code == 201
    data = response.get_json()
    assert data['ok'] is True
    assert data.get('sent') is True
    assert data['friendship']['friend_user_id'] == bob.id


def test_friend_request_persistence_failure_uses_safe_api_error_and_writes_nothing(
    app, client, db_session, social_users, monkeypatch,
):
    from oneirodex import db

    alice, bob = social_users
    _login(client, alice)

    def fail_commit():
        raise RuntimeError('synthetic persistence failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)

    with client:
        response = client.post('/api/social/friends', json={'username': bob.name})

    assert response.status_code == 500
    assert response.content_type.startswith('application/json')
    assert response.get_json() == {
        'ok': False,
        'error': 'Something went wrong on our end. The error has been logged.',
        'error_code': 'internal',
        'message': 'Something went wrong on our end. The error has been logged.',
        'success': False,
    }
    db_session.rollback()
    assert db_session.query(UserFriendship).filter_by(
        user_id=alice.id, friend_user_id=bob.id,
    ).count() == 0
