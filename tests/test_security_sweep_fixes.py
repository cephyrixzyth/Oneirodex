"""Regression tests for the 2026-09-30 security sweep (access control).

Each test names the hole it closes; the fix is in the module it exercises.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import g

from oneirodex.models import User


def _user(db_session, *, role='user', prefix='sweep', **extra) -> User:
    uid = str(uuid4())
    user = User(name=f'{prefix}_{uid[:8]}', email=f'{prefix}_{uid[:8]}@example.com', password_hash='x',
                role=role, user_id=uid, is_email_verified=True, **extra)
    user.set_password('correct-horse-battery')
    db_session.add(user)
    db_session.commit()
    return user


def _as(app, user):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = user.get_id()
        sess['_fresh'] = True
    return client


def _fresh_g():
    g.pop('_login_user', None)


# -- sessions end when the account is disabled or the password changes ------

def test_a_session_ends_when_the_password_changes(app, db_session):
    from oneirodex.utils.auth import load_user

    user = _user(db_session)
    old_session = user.get_id()
    assert load_user(old_session) is user
    user.set_password('a-new-password-entirely')
    db_session.commit()
    assert load_user(old_session) is None, 'cookies issued before the change stop working'
    assert load_user(user.get_id()) is user


def test_a_disabled_account_keeps_no_session(app, db_session):
    from oneirodex.utils.auth import load_user

    user = _user(db_session)
    session_id = user.get_id()
    user.state = False
    db_session.commit()
    assert load_user(session_id) is None
    assert not user.is_active


def test_a_bare_id_session_is_refused_outside_tests(app, db_session, monkeypatch):
    from oneirodex.utils.auth import load_user

    user = _user(db_session)
    assert load_user(str(user.id)) is user  # tests fake logins this way
    monkeypatch.setattr(app, 'testing', False)
    assert load_user(str(user.id)) is None, 'sessions made before fingerprints existed'


def test_changing_your_own_password_keeps_you_signed_in(app, db_session):
    user = _user(db_session)
    client = _as(app, user)
    resp = client.post('/api/account/password', json={
        'current_password': 'correct-horse-battery', 'new_password': 'another-long-password-1',
        'confirm_password': 'another-long-password-1'})
    assert resp.status_code == 200, resp.get_json()
    _fresh_g()
    assert client.get('/api/account/invites').status_code != 302


# -- rate limiting keys on the real address ------------------------------------

def test_a_forged_forwarded_for_header_does_not_change_the_rate_limit_key():
    from oneirodex.utils.login_rate_limit import client_ip_from_request

    request = SimpleNamespace(headers={'X-Forwarded-For': '203.0.113.9'}, remote_addr='192.0.2.7')
    assert client_ip_from_request(request) == '192.0.2.7'


# -- API tokens need the admin scope for admin routes --------------------------

def test_a_companion_token_owned_by_an_admin_cannot_reach_admin_routes(app, db_session):
    from oneirodex.utils.api_tokens import generate_api_token

    admin = _user(db_session, role='admin', prefix='sweep_admin')
    _row, companion = generate_api_token(admin, 'desktop', ['read:library', 'write:download'])
    _row, full = generate_api_token(admin, 'ops', ['admin'])
    client = app.test_client()
    resp = client.get('/api/admin/ownership/connections', headers={'Authorization': f'Bearer {companion}'})
    assert resp.status_code == 403
    _fresh_g()
    resp = client.get('/api/admin/ownership/connections', headers={'Authorization': f'Bearer {full}'})
    assert resp.status_code == 200


# -- blocks belong to the blocker ----------------------------------------------

def test_a_blocked_member_cannot_lift_the_block(app, db_session):
    from oneirodex.models import UserFriendship

    blocker, blocked = _user(db_session, prefix='blocker'), _user(db_session, prefix='blocked')
    row = UserFriendship(user_id=blocker.id, friend_user_id=blocked.id, status='blocked')
    db_session.add(row)
    db_session.commit()
    row_id = row.id
    assert _as(app, blocked).delete(f'/api/social/friends/{row_id}').status_code == 404
    _fresh_g()
    assert db_session.get(UserFriendship, row_id) is not None
    assert _as(app, blocker).delete(f'/api/social/friends/{row_id}').status_code == 200


# -- OIDC links by subject or verified email, never by name --------------------

def _oidc_config():
    return SimpleNamespace(role_claim='groups', role_map={})


def test_oidc_never_links_by_username_or_unverified_email(app, db_session):
    from oneirodex.utils.oidc import provision_or_update_user

    admin = _user(db_session, role='admin', prefix='localadmin')
    admin_email = admin.email
    by_name = provision_or_update_user(db_session, {'sub': 'idp-1', 'preferred_username': admin.name}, _oidc_config())
    assert by_name.id != admin.id
    with pytest.raises(ValueError, match='already exists'):
        provision_or_update_user(
            db_session, {'sub': 'idp-2', 'email': admin_email, 'email_verified': False, 'preferred_username': 'x'},
            _oidc_config())
    db_session.rollback()
    db_session.refresh(admin)
    assert admin.email == admin_email and admin.oidc_subject is None


def test_oidc_links_a_verified_email_once_then_follows_the_subject(app, db_session):
    from oneirodex.utils.oidc import provision_or_update_user

    member = _user(db_session, prefix='ssomember')
    claims = {'sub': 'idp-member', 'email': member.email, 'email_verified': True, 'preferred_username': 'whatever'}
    assert provision_or_update_user(db_session, claims, _oidc_config()).id == member.id
    db_session.refresh(member)
    assert member.oidc_subject == 'idp-member'
    moved = dict(claims, email='new-address@example.com')
    linked = provision_or_update_user(db_session, moved, _oidc_config())
    assert linked.id == member.id and linked.email == member.email, 'the local email is never overwritten'


# -- live events go only to viewers allowed to see them ------------------------

def test_activity_events_reach_friends_who_share_not_everyone(app, db_session):
    from oneirodex.models import UserFriendship, UserPreference
    from oneirodex.utils.event_visibility import event_visible_to

    player, friend, stranger = (_user(db_session, prefix=p) for p in ('player', 'friend', 'stranger'))
    admin = _user(db_session, role='admin', prefix='evadmin')
    db_session.add(UserFriendship(user_id=player.id, friend_user_id=friend.id, status='accepted'))
    db_session.commit()
    event = SimpleNamespace(type='activity', payload={'user_id': player.id, 'action': 'started'})
    assert event_visible_to(event, player.id)
    assert event_visible_to(event, friend.id)
    assert not event_visible_to(event, stranger.id)
    assert event_visible_to(event, admin.id)
    db_session.add(UserPreference(user_id=player.id, share_activity=False))
    db_session.commit()
    assert not event_visible_to(event, friend.id), 'the player turned sharing off'
    assert event_visible_to(SimpleNamespace(type='scan', payload={'progress': 3}), stranger.id)
    assert not event_visible_to(event, None)


# -- the readiness probe does not describe the database to strangers -----------

def test_the_readiness_probe_hides_the_database_error_text(app, monkeypatch):
    from oneirodex.utils import health_probes

    def boom(*_a, **_k):
        raise RuntimeError('could not connect to server at "db.internal" port 5432 user "oneirodex"')

    monkeypatch.setattr(health_probes.db.session, 'execute', boom)
    ok, error = health_probes.check_database()
    assert ok is False and 'db.internal' not in error and error == 'RuntimeError'
