"""Wave 2b — household chat rooms: create / list / ACL / archive."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex import db
from oneirodex.models import ChatChannel, User
from oneirodex.utils.chat import (
    archive_channel,
    create_household_channel,
    ensure_default_channels,
    list_channels_for_user,
    post_message,
    parse_chat_limit,
)


def _slug(prefix: str) -> str:
    """Unique slug per test run — reduces concurrent-pytest UniqueViolation flake."""
    return f'{prefix}-{uuid4().hex[:10]}'


def _make_user(db_session, *, role: str, prefix: str) -> User:
    uid = str(uuid4())
    user = User(
        name=f'{prefix}_{uid[:8]}',
        email=f'{prefix}_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role=role,
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member(db_session):
    return _make_user(db_session, role='user', prefix='member')


@pytest.fixture
def admin(db_session):
    return _make_user(db_session, role='admin', prefix='admin')


@pytest.fixture
def child(db_session):
    return _make_user(db_session, role='child', prefix='child')


@pytest.fixture
def other(db_session):
    return _make_user(db_session, role='user', prefix='other')


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.id)
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


@pytest.mark.parametrize(
    ('raw', 'default', 'maximum', 'expected'),
    [(None, 50, 100, 50), ('', 20, 50, 20), ('150', 50, 100, 100), ('0', 20, 50, 1)],
)
def test_chat_limit_is_defaulted_and_bounded(raw, default, maximum, expected):
    assert parse_chat_limit(raw, default=default, maximum=maximum) == expected


def test_chat_limit_rejects_malformed_value():
    with pytest.raises(ValueError, match='limit must be an integer'):
        parse_chat_limit('many', default=50, maximum=100)


def test_chat_message_api_rejects_malformed_limit(client, app, db_session, member):
    with app.app_context():
        channel = create_household_channel(
            member, name='Paging room', slug=_slug('paging-room'),
        )
        channel_id = channel.id
    _login(client, app, member)

    response = client.get(f'/api/chat/channels/{channel_id}/messages?limit=many')

    assert response.status_code == 400
    assert response.get_json()['error'] == 'limit must be an integer'


def test_member_can_create_household_channel(app, db_session, member):
    with app.app_context():
        slug = _slug('coop-nights')
        ch = create_household_channel(member, name='Co-op nights', slug=slug)
        assert ch.id
        assert ch.kind == 'channel'
        assert ch.slug == slug
        assert ch.is_child_safe is True
        assert ch.created_by_user_id == member.id
        listed = list_channels_for_user(member)
        row = next(c for c in listed if c['id'] == ch.id)
        assert row['name'] == 'Co-op nights'
        assert row['type'] == 'channel'
        assert row['unread'] == 0
        assert row['archived'] is False


def test_member_cannot_set_adult_channel(app, db_session, member):
    with app.app_context():
        ch = create_household_channel(
            member,
            name='Adults only attempt',
            slug=_slug('adults-attempt'),
            is_child_safe=False,
        )
        assert ch.is_child_safe is True


def test_admin_can_create_non_child_safe(app, db_session, admin):
    with app.app_context():
        ch = create_household_channel(
            admin,
            name='After dark',
            slug=_slug('after-dark'),
            is_child_safe=False,
        )
        assert ch.is_child_safe is False


def test_child_cannot_create_channel(app, db_session, child):
    with app.app_context():
        with pytest.raises(PermissionError):
            create_household_channel(child, name='Kid room', slug=_slug('kid-room'))


def test_create_slugifies_from_name(app, db_session, member):
    with app.app_context():
        suffix = uuid4().hex[:8]
        ch = create_household_channel(member, name=f'Friday Night Raid {suffix}!', slug='')
        assert ch.slug == f'friday-night-raid-{suffix}'


def test_list_includes_unread(app, db_session, member, other):
    with app.app_context():
        ensure_default_channels()
        ch = create_household_channel(member, name='Unread room', slug=_slug('unread-room'))
        list_channels_for_user(other)
        post_message(ch, member, 'hello there')
        listed = list_channels_for_user(other)
        row = next(c for c in listed if c['id'] == ch.id)
        assert row['unread'] >= 1


def test_archive_hides_from_list(app, db_session, member, other):
    with app.app_context():
        ch = create_household_channel(member, name='Temp room', slug=_slug('temp-room'))
        archive_channel(member, ch)
        assert ch.archived_at is not None
        ids_member = {c['id'] for c in list_channels_for_user(member)}
        ids_other = {c['id'] for c in list_channels_for_user(other)}
        assert ch.id not in ids_member
        assert ch.id not in ids_other


def test_other_member_cannot_archive(app, db_session, member, other):
    with app.app_context():
        ch = create_household_channel(member, name='Mine', slug=_slug('mine-room'))
        with pytest.raises(PermissionError):
            archive_channel(other, ch)


def test_api_create_list_acl(client, app, db_session, member, child):
    _login(client, app, member)
    slug = _slug('api-room')
    created = client.post(
        '/api/chat/channels',
        json={'name': 'API Room', 'slug': slug},
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body['ok'] is True
    assert body['channel']['slug'] == slug
    assert body['room']['id'] == body['channel']['id']
    assert body['channel']['type'] == 'channel'
    assert body['channel']['unread'] == 0

    listed = client.get('/api/chat/channels')
    assert listed.status_code == 200
    data = listed.get_json()
    assert 'rooms' in data and 'channels' in data
    assert any(r['slug'] == slug for r in data['rooms'])

    _login(client, app, child)
    denied = client.post(
        '/api/chat/channels',
        json={'name': 'Nope', 'slug': _slug('nope-room')},
    )
    assert denied.status_code == 403


def test_api_archive_and_leave_dm(client, app, db_session, member, other):
    _login(client, app, member)
    created = client.post(
        '/api/chat/channels',
        json={'name': 'Archive me', 'slug': _slug('archive-me')},
    )
    channel_id = created.get_json()['channel']['id']

    archive = client.post(f'/api/chat/channels/{channel_id}/archive')
    assert archive.status_code == 200
    assert archive.get_json()['archived'] is True

    listed = client.get('/api/chat/channels')
    assert all(r['id'] != channel_id for r in listed.get_json()['rooms'])

    dm = client.post('/api/chat/dm', json={'user_id': other.id})
    assert dm.status_code == 200
    dm_id = dm.get_json()['channel']['id']
    left = client.post(f'/api/chat/channels/{dm_id}/leave')
    assert left.status_code == 200
    listed2 = client.get('/api/chat/channels')
    assert all(r['id'] != dm_id for r in listed2.get_json()['channels'])
