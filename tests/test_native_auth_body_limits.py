"""Regression coverage for streamed size limits on public JSON auth routes."""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import Request

from oneirodex.runtime_native import auth_login, auth_registration


def _streamed_request(chunks):
    remaining = iter(chunks)

    async def receive():
        try:
            body = next(remaining)
        except StopIteration:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        return {'type': 'http.request', 'body': body, 'more_body': True}

    return Request({
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': '/',
        'raw_path': b'/',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 1234),
        'server': ('testserver', 80),
    }, receive)


@pytest.mark.parametrize('module', [auth_login, auth_registration])
def test_public_auth_json_body_limit_counts_streamed_bytes_without_content_length(module):
    request = _streamed_request([
        b'{"padding":"', b'x' * (64 * 1024), b'"}',
    ])

    body, response = asyncio.run(module._validated_body(request))

    assert body is None
    assert response.status_code == 413
    assert json.loads(response.body)['error_code'] == 'payload_too_large'


@pytest.mark.parametrize('module', [auth_login, auth_registration])
def test_public_auth_json_body_validation_preserves_malformed_json_status(module):
    request = _streamed_request([b'{'])

    body, response = asyncio.run(module._validated_body(request))

    assert body is None
    # Pydantic's model_validate_json reports JSON decoding failures as a
    # ValidationError, which the existing route contract exposes as 422.
    assert response.status_code == 422
    assert json.loads(response.body)['error_code'] == 'unprocessable'
