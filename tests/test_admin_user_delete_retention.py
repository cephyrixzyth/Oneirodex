from uuid import uuid4

from oneirodex.models import Newsletter, SystemEvents, User


def _make_user(name: str, role: str) -> User:
    user = User(
        name=name,
        email=f'{name}@example.com',
        password_hash='placeholder',
        role=role,
        user_id=str(uuid4()),
        state=True,
    )
    user.set_password('a long enough test password')
    return user


def test_admin_deletion_removes_user_and_retains_anonymized_audit_event(client, db_session):
    suffix = str(uuid4())[:8]
    admin = _make_user(f'del_admin_{suffix}', 'admin')
    victim = _make_user(f'del_member_{suffix}', 'user')
    db_session.add_all([admin, victim])
    db_session.flush()
    victim_id = victim.id
    victim_name = victim.name
    victim_email = victim.email
    audit = SystemEvents(
        event_type='audit',
        event_text=f'{victim_name} ({victim_email}) changed account settings',
        event_level='information',
        audit_user=victim_id,
    )
    newsletter = Newsletter(
        subject='Account-owned announcement',
        content='Test content authored by account being deleted.',
        sender_id=victim_id,
    )
    db_session.add_all([audit, newsletter])
    db_session.commit()
    newsletter_id = newsletter.id

    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True

    response = client.delete(f'/admin/api/user/{victim_id}')

    assert response.status_code == 200, response.get_data(as_text=True)
    assert db_session.get(User, victim_id) is None
    assert db_session.get(Newsletter, newsletter_id) is None
    retained = db_session.get(SystemEvents, audit.id)
    assert retained is not None
    assert retained.audit_user is None
    assert victim_name not in retained.event_text
    assert victim_email not in retained.event_text
