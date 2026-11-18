"""Email-confirmation password-body contracts; no DB, mail or provider I/O."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.auth_confirmation import create_auth_confirmation_router


PASSWORD_ERROR = 'Password must be at least 8 characters.'
MISMATCH_ERROR = 'Passwords do not match.'


@pytest.fixture
def clients():
    native_calls = []
    native = FastAPI()
    data = SimpleNamespace(inspect=lambda _token, _secret: 'confirmed', confirm=lambda _token, _secret, password: native_calls.append(password) or 'confirmed')
    native.include_router(create_auth_confirmation_router(data_access=data, app_config={'SECRET_KEY': 'synthetic-confirm-body-contract', 'WTF_CSRF_ENABLED': False}))
    with TestClient(native) as native_client:
        yield native_client, native_calls


@pytest.mark.parametrize(
    ('payload', 'message'),
    [
        ({}, PASSWORD_ERROR),
        (None, PASSWORD_ERROR),
        ([], PASSWORD_ERROR),
        ('12345678', PASSWORD_ERROR),
        ({'password': None}, PASSWORD_ERROR),
        ({'password': 12345678, 'confirm_password': 12345678}, PASSWORD_ERROR),
        ({'password': '1234567', 'confirm_password': '1234567'}, PASSWORD_ERROR),
        ({'password': '        ', 'confirm_password': '        '}, PASSWORD_ERROR),
        ({'password': 'a' * 1025, 'confirm_password': 'a' * 1025}, PASSWORD_ERROR),
        ({'password': '😀' * 257, 'confirm_password': '😀' * 257}, PASSWORD_ERROR),
        ({'password': '\ud800' * 8, 'confirm_password': '\ud800' * 8}, PASSWORD_ERROR),
        ({'password': '12345678'}, MISMATCH_ERROR),
        ({'password': '12345678', 'confirm_password': 12345678}, MISMATCH_ERROR),
        ({'password': '12345678', 'confirm_password': []}, MISMATCH_ERROR),
        ({'password': '12345678', 'confirm_password': 'different'}, MISMATCH_ERROR),
    ],
    ids=[
        'missing',
        'null',
        'array',
        'scalar',
        'null-password',
        'numeric',
        'short',
        'blank',
        'ascii-over-limit',
        'utf8-over-limit',
        'invalid-utf8',
        'missing-confirmation',
        'numeric-confirmation',
        'array-confirmation',
        'different-confirmation',
    ],
)
def test_invalid_confirmation_body_is_sanitized_and_never_activates(clients, payload, message):
    native_client, native_calls = clients
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8', 'backslashreplace')
    right = native_client.post('/api/auth/confirm/synthetic-token', content=raw, headers={'Content-Type': 'application/json'})
    assert right.status_code == 422
    assert right.json()['message'] == message
    assert right.json().get('detail') is None
    assert native_calls == []


@pytest.mark.parametrize(
    'password',
    [
        '12345678',
        'a' * 1024,
        '😀' * 256,
        '  aaaaaa',
    ],
    ids=[
        'minimum',
        'maximum-ascii',
        'maximum-utf8',
        'untrimmed',
    ],
)
def test_valid_confirmation_password_is_passed_exactly(clients, password):
    native_client, native_calls = clients
    raw = json.dumps({'password': password, 'confirm_password': password, 'unused': 'extra-field'}, ensure_ascii=False)
    right = native_client.post('/api/auth/confirm/synthetic-token', content=raw, headers={'Content-Type': 'application/json'})
    assert right.status_code == 200
    assert right.json()['confirmed'] is True
    assert native_calls == [password]

def test_get_ignores_a_body_and_never_activates(clients):
    native_client, native_calls = clients
    right = native_client.request('GET', '/api/auth/confirm/synthetic-token', content='[]', headers={'Content-Type': 'application/json'})
    assert right.status_code == 200
    assert right.json()['confirmed'] is False
    assert native_calls == []


@pytest.mark.parametrize(
    ('raw', 'kind', 'native_status', 'native_message'),
    [
        ('{', 'application/json', 400, 'Invalid JSON body.'),
        ('{"password":"12345678"}', 'text/plain', 422, MISMATCH_ERROR),
    ],
)
def test_malformed_or_non_json_confirmation_body_preserves_each_parser_contract(clients, raw, kind, native_status, native_message):
    native_client, native_calls = clients
    right = native_client.post('/api/auth/confirm/synthetic-token', content=raw, headers={'Content-Type': kind})
    assert right.status_code == native_status
    assert right.json()['message'] == native_message
    assert native_calls == []
