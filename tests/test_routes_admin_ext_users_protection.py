"""Admin account deletion must preserve at least one active administrator."""

from uuid import uuid4

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import User


def _make_user(db_session, *, role: str):
    suffix = uuid4().hex[:8]
    user = User(
        name=f'account_{suffix}',
        email=f'account_{suffix}@example.com',
        role=role,
        state=True,
        user_id=str(uuid4()),
    )
    user.set_password('a long test password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_last_active_admin_cannot_delete_their_own_account(client, db_session):
    # Keep the target away from the separate id=1 primary-admin rule so this
    # exercises the active-admin protection itself.
    _make_user(db_session, role='user')
    admin = _make_user(db_session, role='admin')
    _login(client, admin)

    response = client.delete(f'/admin/api/user/{admin.id}')

    assert response.status_code == 403
    assert 'Cannot modify the last active admin account' in response.get_data(as_text=True)
    assert db.session.execute(select(User).where(User.id == admin.id)).scalar_one_or_none() is not None
