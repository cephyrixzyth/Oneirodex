from uuid import uuid4

import pytest

from oneirodex.models import GlobalSettings, User


@pytest.fixture
def demo_member(db_session):
    user_id = str(uuid4())
    user = User(
        name='demo-visitor',
        email='demo-visitor@example.test',
        password_hash='unused-demo-password',
        role='user',
        user_id=user_id,
        state=True,
    )
    settings = GlobalSettings(setup_completed=True, setup_in_progress=False)
    db_session.add_all((user, settings))
    db_session.commit()
    return user


def test_demo_entrypoint_is_hidden_when_public_demo_is_disabled(client, demo_member, monkeypatch):
    monkeypatch.delenv('ONEIRODEX_PUBLIC_DEMO', raising=False)

    response = client.get('/demo')

    assert response.status_code == 404


def test_demo_entrypoint_logs_in_only_the_member_account(client, demo_member, monkeypatch):
    monkeypatch.setenv('ONEIRODEX_PUBLIC_DEMO', 'true')

    response = client.get('/demo')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/discover')
    with client.session_transaction() as session:
        assert session['_user_id'] == demo_member.get_id()
    assert demo_member.role == 'user'


def test_demo_entrypoint_fails_closed_when_seed_is_missing(client, db_session, monkeypatch):
    monkeypatch.setenv('ONEIRODEX_PUBLIC_DEMO', 'true')

    existing_member = User(
        name='existing-member',
        email='existing-member@example.test',
        password_hash='unused-demo-password',
        role='user',
        user_id=str(uuid4()),
        state=True,
    )
    db_session.add(existing_member)
    db_session.add(GlobalSettings(setup_completed=True, setup_in_progress=False))
    db_session.commit()

    response = client.get('/demo')

    assert response.status_code == 503
