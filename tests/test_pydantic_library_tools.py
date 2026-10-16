"""422 contracts for library-tools `@validate_body` JSON routes.

Required-field refusals (freshness library_uuid, proposal path/igdb_id,
doctor roots/rows) are now 422 unprocessable. Empty ``scan_roots`` /
``write_proposals`` bodies stay valid — those models default to an empty list
because the admin UI posts ``{}``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'pyd_lt_admin_{uid[:8]}',
        email=f'pyd_lt_admin_{uid[:8]}@example.com',
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


def test_check_freshness_requires_library_uuid(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/library_tools/check_freshness', json={})
    _assert_unprocessable(response, 'library_uuid')


def test_approve_proposal_requires_path_and_igdb_id(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/library_tools/proposals/approve', json={})
    _assert_unprocessable(response, 'path')
    assert 'igdb_id' in response.get_json()['detail']


def test_approve_proposal_does_not_return_filesystem_error_path(
    client, app, admin_user, monkeypatch, tmp_path,
):
    _login(client, app, admin_user)
    private_path = str(tmp_path / 'private-library-root')
    monkeypatch.setattr(
        'oneirodex.routes_apis.library_tools.is_safe_path',
        lambda _path, _bases: (True, None),
    )

    def fail(_path):
        raise OSError(f'permission denied: {private_path}')

    monkeypatch.setattr(
        'oneirodex.routes_apis.library_tools.remove_proposal_files', fail,
    )
    response = client.post(
        '/api/library_tools/proposals/approve',
        json={'path': private_path, 'igdb_id': 123},
    )

    assert response.status_code == 500
    assert response.get_json()['error'] == 'Could not clear proposal files'
    assert private_path not in response.get_data(as_text=True)


def test_doctor_dry_run_requires_roots(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/library_tools/doctor/dry_run', json={})
    _assert_unprocessable(response, 'roots')


def test_doctor_apply_renames_requires_rows(client, app, admin_user):
    _login(client, app, admin_user)
    response = client.post('/api/library_tools/doctor/apply_renames', json={})
    _assert_unprocessable(response, 'rows')
