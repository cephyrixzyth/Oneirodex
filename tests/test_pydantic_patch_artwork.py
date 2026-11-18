"""422 contracts for patch-catalog attach and artwork-apply JSON."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'pyd_art_admin_{uid[:8]}',
        email=f'pyd_art_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.id)
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def _assert_unprocessable(response, field: str) -> None:
    assert response.status_code == 422, response.get_data(as_text=True)
    body = response.get_json()
    assert body['ok'] is False
    assert body['error'] == 'Invalid request.'
    assert body['error_code'] == 'unprocessable'
    assert field in body['detail']


def test_patch_catalog_attach_requires_game_uuid_and_source_url(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/patch-catalog/attach', json={})
    # Both required fields missing gets one plain sentence for the admin form.
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Provide a game UUID and source URL.'


def test_artwork_apply_requires_url(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post(
        f'/api/games/{uuid4()}/artwork/steamgriddb',
        json={},
    )
    _assert_unprocessable(response, 'url')


def test_artwork_apply_blank_url_is_unprocessable(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post(
        f'/api/games/{uuid4()}/artwork/steamgriddb',
        json={'url': '   '},
    )
    _assert_unprocessable(response, 'url')
