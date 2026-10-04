from uuid import uuid4

import pytest

from oneirodex.models import GlobalSettings, User


def _complete_setup(db_session):
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.setup_completed = True
    settings.setup_in_progress = False
    return settings


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
    _complete_setup(db_session)
    db_session.add(user)
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
    _complete_setup(db_session)
    db_session.commit()

    response = client.get('/demo')

    assert response.status_code == 503
