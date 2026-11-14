from __future__ import annotations

import asyncio
from importlib import import_module

import pytest
from starlette.requests import Request


@pytest.mark.parametrize(
    ('module_name', 'parser_name'),
    [
        ('account_password', '_legacy_password_form'),
        ('account_preferences', '_legacy_form'),
        ('admin_features', '_read_form'),
        ('admin_invites', '_legacy_form'),
        ('admin_newsletters', '_legacy_form'),
        ('admin_whitelist', '_legacy_form'),
    ],
)
def test_native_legacy_form_parsers_select_first_repeated_value(module_name, parser_name):
    module = import_module(f'oneirodex.runtime_native.{module_name}')
    parser = getattr(module, parser_name)
    body = b'csrf_token=token&field=first&field=second'

    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}

    request = Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'http',
            'path': '/form',
            'raw_path': b'/form',
            'query_string': b'',
            'headers': [(b'content-type', b'application/x-www-form-urlencoded')],
            'client': ('127.0.0.1', 1234),
            'server': ('testserver', 80),
        },
        receive,
    )

    form, error = asyncio.run(parser(request))

    assert error is None
    assert form == {'csrf_token': 'token', 'field': 'first'}
