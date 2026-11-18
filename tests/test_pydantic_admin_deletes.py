"""422 contracts for admin full-game and image-delete JSON."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'pyd_del_admin_{uid[:8]}',
        email=f'pyd_del_admin_{uid[:8]}@example.com',
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


def test_delete_full_game_requires_game_uuid(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/delete_full_game', json={})
    _assert_unprocessable(response, 'game_uuid')


def test_delete_image_requires_image_id(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/delete_image', json={})
    _assert_unprocessable(response, 'image_id')


def test_delete_image_malformed_body_is_422_even_if_scan_running(client, app, admin_user):
    """Validation runs before the in-view scan lock, so `{}` is 422 not 403."""
    _login(client, app, admin_user)
    with patch(
        'oneirodex.utils.scanning.is_scan_job_running',
        return_value=True,
    ):
        response = client.post('/delete_image', json={})
    _assert_unprocessable(response, 'image_id')
