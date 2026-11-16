# tests/test_integrations_inventory.py
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _keyring(reusable_secret_keyring):
    return reusable_secret_keyring

from oneirodex.models import User
from oneirodex.utils.integrations_inventory import build_integrations_inventory


@pytest.fixture
def admin_user(db_session):
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=str(uuid4()),
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        state=True,
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=str(uuid4()),
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        state=True,
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_inventory_covers_core_providers(app, db_session):
    with app.app_context():
        rows = build_integrations_inventory()
    ids = {r['id'] for r in rows}
    for required in (
        'igdb',
        'steamgriddb',
        'smtp',
        'oidc',
        'livekit',
        'support',
        'meta_quest',
        'hltb',
        'giantbomb',
    ):
        assert required in ids
    for row in rows:
        assert 'admin_href' in row
        assert row['status'] in ('configured', 'available', 'disabled')


def test_inventory_api_requires_admin(client, app, admin_user, regular_user):
    from flask_login import login_user

    resp = client.get('/api/admin/integrations/inventory')
    assert resp.status_code in (302, 401)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(regular_user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(regular_user)
    resp = client.get('/api/admin/integrations/inventory')
    assert resp.status_code in (302, 403)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(admin_user)
    resp = client.get('/api/admin/integrations/inventory')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['count'] >= 8
    assert payload['hub_href'] == '/admin/integrations'
    assert payload['credential_storage'] == {'available': True, 'message': None}
    assert any(i['id'] == 'igdb' for i in payload['integrations'])
