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
    """Forget the previous request's user and token: the test holds one app
    context, so ``g`` outlives each request here (it never does in a server)."""
    g.pop('_login_user', None)
    g.pop('api_token', None)


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
    _fresh_g()
    # Re-blocking from the blocked side must not take the row over either.
    assert _as(app, blocked).post(f'/api/social/friends/{row_id}/block').status_code == 404
    _fresh_g()
    db_session.expire_all()
    assert db_session.get(UserFriendship, row_id).user_id == blocker.id
    assert _as(app, blocker).delete(f'/api/social/friends/{row_id}').status_code == 200


# -- OIDC links by subject or verified email, never by name --------------------

def _oidc_config():
    return SimpleNamespace(
        issuer_url='https://idp.example', role_claim='groups', role_map={},
    )


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
    download = SimpleNamespace(type='download', payload={'user_id': player.id, 'request_id': 7, 'status': 'available'})
    assert event_visible_to(download, player.id) and event_visible_to(download, admin.id)
    assert not event_visible_to(download, friend.id), "a member's downloads are theirs"
    player.state = False
    db_session.commit()
    assert not event_visible_to(download, player.id), 'a disabled account receives nothing more'


# -- the readiness probe does not describe the database to strangers -----------

def test_the_readiness_probe_hides_the_database_error_text(app, monkeypatch):
    from oneirodex.utils import health_probes

    def boom(*_a, **_k):
        raise RuntimeError('could not connect to server at "db.internal" port 5432 user "oneirodex"')

    monkeypatch.setattr(health_probes.db.session, 'execute', boom)
    ok, error = health_probes.check_database()
    assert ok is False and 'db.internal' not in error and error == 'RuntimeError'


# -- an invite link registers exactly one account ------------------------------

def test_an_invite_registers_exactly_one_account(app, db_session, monkeypatch):
    """The claim used to run before the user row existed (used_by references
    users.user_id), so every invite registration failed with an IntegrityError."""
    from oneirodex.models import InviteToken
    import oneirodex.routes_login as routes_login

    monkeypatch.setattr(routes_login, 'send_email', lambda *a, **k: None)
    inviter = _user(db_session, prefix='inviter')
    invite = InviteToken(token=f'inv-{uuid4().hex}', creator_user_id=inviter.user_id)
    db_session.add(invite)
    db_session.commit()
    token = invite.token

    def register(name):
        return app.test_client().post(f'/register?token={token}', data={
            'username': name, 'email': f'{name}@example.com', 'password': 'long-enough-1'})

    first, second = f'guest{uuid4().hex[:6]}', f'guest{uuid4().hex[:6]}'
    register(first)
    db_session.expire_all()
    created = db_session.query(User).filter_by(name=first).one_or_none()
    assert created is not None, 'the invited guest got an account'
    claimed = db_session.query(InviteToken).filter_by(token=token).one()
    assert claimed.used and claimed.used_by == created.user_id
    register(second)
    db_session.expire_all()
    assert db_session.query(User).filter_by(name=second).one_or_none() is None, 'one link, one account'


def test_mixed_case_registration_email_confirms_successfully(app, db_session, monkeypatch):
    """Stored email is normalized, and confirmation must use the same identity."""
    from oneirodex.models import InviteToken
    import oneirodex.routes_login as routes_login

    monkeypatch.setattr(routes_login, 'send_email', lambda *a, **k: None)
    inviter = _user(db_session, prefix='mixed_case_inviter')
    invite = InviteToken(token=f'inv-{uuid4().hex}', creator_user_id=inviter.user_id)
    db_session.add(invite)
    db_session.commit()
    email = f'Alice.{uuid4().hex[:6]}@Example.com'
    username = f'mixedcase{uuid4().hex[:8]}'

    response = app.test_client().post(f'/register?token={invite.token}', data={
        'username': username, 'email': email, 'password': 'long-enough-1',
    })
    assert response.status_code == 302
    db_session.expire_all()
    user = db_session.query(User).filter_by(name=username).one()
    assert user.email == email.lower()
    assert user.is_email_verified is False

    confirmed = app.test_client().get(f'/confirm/{user.email_verification_token}')
    assert confirmed.status_code == 200
    db_session.expire_all()
    assert db_session.query(User).filter_by(id=user.id).one().is_email_verified is True


def test_registration_confirmation_link_ignores_host_header(app, db_session, monkeypatch):
    from oneirodex.models import InviteToken
    import oneirodex.routes_login as routes_login

    sent = []
    monkeypatch.setattr(routes_login, 'send_email', lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(routes_login, 'public_origin', lambda: 'https://library.example')
    inviter = _user(db_session, prefix='host_header_inviter')
    invite = InviteToken(token=f'inv-{uuid4().hex}', creator_user_id=inviter.user_id)
    db_session.add(invite)
    db_session.commit()

    app.test_client().post(
        f'/register?token={invite.token}',
        base_url='http://attacker.example',
        data={
            'username': f'hostguard{uuid4().hex[:8]}',
            'email': f'{uuid4().hex}@example.com',
            'password': 'long-enough-1',
        },
    )

    assert len(sent) == 1
    assert 'https://library.example/confirm/' in sent[0][2]
    assert 'attacker.example' not in sent[0][2]


def test_a_token_cannot_mint_a_broader_token(app, db_session):
    """An admin's companion token could mint itself an admin-scope token."""
    from oneirodex.utils.api_tokens import generate_api_token

    admin = _user(db_session, role='admin', prefix='mint_admin')
    _row, companion = generate_api_token(admin, 'desktop', ['read:library', 'write:download'])
    bearer = {'Authorization': f'Bearer {companion}'}
    client = app.test_client()
    resp = client.post('/api/tokens', json={'name': 'x', 'scopes': ['admin']}, headers=bearer)
    assert resp.status_code == 403
    _fresh_g()
    resp = client.post('/api/tokens', json={'name': 'y', 'scopes': ['read:library']}, headers=bearer)
    assert resp.status_code == 201, 'narrower or equal scopes are still fine'
    _fresh_g()
    resp = _as(app, admin).post('/api/tokens', json={'name': 'from-browser', 'scopes': ['admin']})
    assert resp.status_code == 201, 'a signed-in admin session can still create an admin token'


@pytest.mark.parametrize('role', ['user', 'librarian'])
@pytest.mark.parametrize('padded', [' admin', 'admin ', '\tadmin', 'admin\n'])
def test_a_padded_admin_scope_is_still_the_admin_scope(app, db_session, role, padded):
    """' admin' passed the role check (a raw list compare) and was then stored
    stripped, as 'admin', the wildcard scope."""
    from oneirodex.models import ApiToken

    member = _user(db_session, role=role, prefix=f'pad_{role}')
    _fresh_g()
    resp = _as(app, member).post('/api/tokens', json={'name': 'sneaky', 'scopes': [padded]})
    assert resp.status_code == 403
    assert db_session.query(ApiToken).filter_by(user_id=member.id).count() == 0


def test_token_scopes_must_be_strings(app, db_session):
    member = _user(db_session, prefix='scope_types')
    _fresh_g()
    resp = _as(app, member).post('/api/tokens', json={'name': 'odd', 'scopes': ['read:library', 7]})
    assert resp.status_code == 400


def test_mentions_reach_only_people_who_can_read_the_channel(app, db_session, monkeypatch):
    """A stale membership row (from before invite-only spaces were enforced, or a
    removed member) used to carry the mention text to a non-member."""
    from oneirodex.models import ChatChannelMember
    from oneirodex.utils import chat as chat_mod
    from oneirodex.utils.chat_spaces import add_space_member, create_channel, create_space, remove_space_member

    owner, bob = _user(db_session, prefix='owner'), _user(db_session, prefix='bob')
    space = create_space(name='Private', created_by_user_id=owner.id, visibility='invite')
    ch = create_channel(space=space, name='plans', created_by_user_id=owner.id)
    add_space_member(space, bob.id)
    chat_mod.ensure_channel_membership(ch, bob)
    remove_space_member(space, bob.id)
    assert db_session.query(ChatChannelMember).filter_by(channel_id=ch.id, user_id=bob.id).count() == 0, \
        'leaving a space removes its channel memberships'
    db_session.add(ChatChannelMember(channel_id=ch.id, user_id=bob.id))  # a stale row from before
    db_session.commit()

    sent = []
    monkeypatch.setattr(chat_mod, 'notify_user', lambda user_id, **kw: sent.append(user_id))
    chat_mod.post_message(ch, owner, f'@{bob.name} secret plans')
    assert bob.id not in sent


def test_an_operator_can_trust_a_provider_that_omits_email_verified(app, db_session, monkeypatch):
    from oneirodex.utils.oidc import provision_or_update_user

    member = _user(db_session, prefix='ssolegacy')
    claims = {'sub': 'idp-legacy', 'email': member.email, 'preferred_username': member.name}
    with pytest.raises(ValueError, match='already exists'):
        provision_or_update_user(db_session, claims, _oidc_config())
    db_session.rollback()
    monkeypatch.setitem(app.config, 'OIDC_TRUST_PROVIDER_EMAIL', True)
    assert provision_or_update_user(db_session, claims, _oidc_config()).id == member.id
