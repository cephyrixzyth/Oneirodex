"""JSON registration retains invite and whitelist account rules."""

from uuid import uuid4

from oneirodex.models import InviteToken, User, Whitelist


def registration_payload(*, username=None, email=None):
    suffix = uuid4().hex[:8]
    return {
        'username': username or f'guest_{suffix}',
        'email': email or f'guest_{suffix}@example.com',
        'password': 'long-enough-password',
    }


def inviter(db_session):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'inviter_{suffix}', email=f'inviter_{suffix}@example.com',
        password_hash='placeholder', role='admin', user_id=str(uuid4()),
    )
    user.set_password('owner password')
    db_session.add(user)
    db_session.commit()
    return user


def test_invite_registration_claims_link_and_sends_confirmation(client, db_session, monkeypatch):
    import oneirodex.routes_login as routes_login

    sent = []
    monkeypatch.setattr(routes_login, 'send_email', lambda *args: sent.append(args) or True)
    owner = inviter(db_session)
    invite = InviteToken(token=f'inv-{uuid4().hex}', creator_user_id=owner.user_id)
    db_session.add(invite)
    db_session.commit()
    payload = registration_payload(email=f'{uuid4().hex[:8]}@Example.com')

    response = client.post(f'/api/auth/register?token={invite.token}', json=payload)

    assert response.status_code == 202
    assert response.get_json()['requested'] is True
    assert response.get_json()['message'] == (
        'If the details can be used to create an account, check your email for next steps.'
    )
    created = db_session.query(User).filter_by(name=payload['username']).one()
    assert created.email == payload['email'].lower()
    assert created.is_email_verified is False
    assert sent and sent[0][0] == created.email
    db_session.refresh(invite)
    assert invite.used is True and invite.used_by == created.user_id

    duplicate = client.post(f'/api/auth/register?token={invite.token}', json=registration_payload())
    assert duplicate.status_code == 400


def test_allowlisted_email_can_register_without_invite(client, db_session, monkeypatch):
    import oneirodex.routes_login as routes_login

    monkeypatch.setattr(routes_login, 'send_email', lambda *_args: True)
    payload = registration_payload(email=f'{uuid4().hex[:8]}@Example.com')
    db_session.add(Whitelist(email=payload['email'].lower()))
    db_session.commit()

    response = client.post('/api/auth/register', json=payload)

    assert response.status_code == 202
    assert db_session.query(User).filter_by(name=payload['username']).one().email == payload['email'].lower()


def test_registration_does_not_disclose_email_or_username_eligibility(client, db_session):
    suffix = uuid4().hex[:8]
    existing = User(
        name=f'known_{suffix}', email=f'known_{suffix}@example.com',
        password_hash='placeholder', role='user', user_id=str(uuid4()),
    )
    existing.set_password('owner password')
    db_session.add(existing)
    db_session.commit()

    duplicate_email = client.post('/api/auth/register', json=registration_payload(
        username=f'new_{suffix}', email=existing.email,
    ))
    unallowlisted_email = client.post('/api/auth/register', json=registration_payload(
        username=f'newer_{suffix}', email=f'unknown_{suffix}@example.com',
    ))
    duplicate_username = client.post('/api/auth/register', json=registration_payload(
        username=existing.name, email=f'other_{suffix}@example.com',
    ))

    assert duplicate_email.status_code == unallowlisted_email.status_code == 202
    assert duplicate_username.status_code == 202
    assert duplicate_email.get_json() == unallowlisted_email.get_json() == duplicate_username.get_json()
    assert duplicate_email.get_json()['requested'] is True


def test_registration_does_not_disclose_non_allowlisted_email(client):
    response = client.post('/api/auth/register', json=registration_payload())

    assert response.status_code == 202
    assert response.get_json()['requested'] is True


def test_classic_registration_does_not_disclose_email_or_whitelist_state(client, db_session):
    client.application.config['WTF_CSRF_ENABLED'] = False
    suffix = uuid4().hex[:8]
    existing = User(
        name=f'classic_{suffix}', email=f'classic_{suffix}@example.com',
        password_hash='placeholder', role='user', user_id=str(uuid4()),
    )
    existing.set_password('owner password')
    db_session.add(existing)
    db_session.commit()

    duplicate_email = client.post('/register', data={
        'username': f'new_{suffix}', 'email': existing.email, 'password': 'long-password',
    })
    unallowlisted_email = client.post('/register', data={
        'username': f'other_{suffix}', 'email': f'unknown_{suffix}@example.com',
        'password': 'long-password',
    })

    assert duplicate_email.status_code == unallowlisted_email.status_code == 302
    assert duplicate_email.headers['Location'] == unallowlisted_email.headers['Location']


def test_registration_preserves_field_validation_errors(client):
    response = client.post('/api/auth/register', json={
        'username': 'system', 'email': 'not-an-email', 'password': 'short',
    })

    assert response.status_code == 422
    assert response.get_json()['error_code'] == 'unprocessable'
    assert {'username', 'email', 'password'} <= set(response.get_json()['detail'])


def test_registration_requires_valid_invite(client, db_session):
    payload = registration_payload()
    response = client.post('/api/auth/register?token=expired-or-unknown', json=payload)

    assert response.status_code == 400
    assert db_session.query(User).filter_by(name=payload['username']).one_or_none() is None
