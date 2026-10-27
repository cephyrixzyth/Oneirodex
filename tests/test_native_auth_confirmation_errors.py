from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.auth_confirmation import create_auth_confirmation_router


@pytest.mark.parametrize(
    ('outcome', 'status', 'message'),
    [
        (
            'expired',
            400,
            'The confirmation link is invalid or has expired. Request a new activation '
            'from an admin or try registering again with a fresh invite.',
        ),
        (
            'invalid',
            400,
            'This confirmation link is not valid. Check your email for the correct link, '
            'or sign in if your account is already active.',
        ),
        (
            'not_found',
            404,
            'The account for this confirmation link was not found.',
        ),
    ],
)
def test_confirmation_api_error_copy_is_actionable(outcome, status, message):
    data = SimpleNamespace(inspect=lambda _token, _secret: outcome)
    app = FastAPI()
    app.include_router(
        create_auth_confirmation_router(
            data_access=data,
            app_config={'SECRET_KEY': 'test-secret'},
        )
    )

    response = TestClient(app).get('/api/auth/confirm/synthetic-token')

    assert response.status_code == status
    assert response.json()['message'] == message


def test_confirmation_requires_post_and_mailbox_owner_password():
    calls = []
    data = SimpleNamespace(
        inspect=lambda _token, _secret: 'confirmed',
        confirm=lambda _token, _secret, password: calls.append(password) or 'confirmed',
    )
    app = FastAPI()
    app.include_router(create_auth_confirmation_router(
        data_access=data,
        app_config={'SECRET_KEY': 'test-secret', 'WTF_CSRF_ENABLED': False},
    ))
    client = TestClient(app)

    inspected = client.get('/api/auth/confirm/synthetic-token')
    assert inspected.status_code == 200
    assert inspected.json()['confirmed'] is False
    assert calls == []

    mismatch = client.post('/api/auth/confirm/synthetic-token', json={
        'password': 'mailbox-owner-password', 'confirm_password': 'wrong-password',
    })
    assert mismatch.status_code == 422
    assert calls == []

    activated = client.post('/api/auth/confirm/synthetic-token', json={
        'password': 'mailbox-owner-password', 'confirm_password': 'mailbox-owner-password',
    })
    assert activated.status_code == 200
    assert activated.json()['confirmed'] is True
    assert calls == ['mailbox-owner-password']
