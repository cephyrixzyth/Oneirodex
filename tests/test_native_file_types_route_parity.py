from __future__ import annotations

import logging
import json
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from starlette.requests import Request

import asgi
from oneirodex.runtime_native.system_file_types import (
    _handle_file_type_request,
    create_system_file_types_router,
    validate_file_type_value,
)


def test_file_types_options_matches_flask_automatic_response():
    legacy = Flask(__name__)
    legacy.add_url_rule(
        '/api/file_types/<string:type_category>',
        'manage_file_types',
        lambda type_category: '',
        methods=['GET', 'POST', 'PUT', 'DELETE'],
    )

    current = FastAPI()
    router = create_system_file_types_router(
        SimpleNamespace(config={}),
        find_user=lambda _user_id: None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        data_access=object(),
    )
    current.include_router(router)

    legacy_response = legacy.test_client().options('/api/file_types/allowed')
    current_response = TestClient(current).options('/api/file_types/allowed')

    assert current_response.status_code == legacy_response.status_code == 200
    assert current_response.headers['content-type'] == legacy_response.headers['Content-Type']
    assert set(current_response.headers['allow'].split(', ')) == set(
        legacy_response.headers['Allow'].split(', ')
    )
    assert current_response.content == legacy_response.get_data() == b''


def test_file_types_api_method_error_does_not_leak_allow_header():
    legacy = Flask(__name__)
    legacy.config.update(SECRET_KEY='file-type-405-secret', CSP_ENABLED=False)
    legacy.add_url_rule(
        '/api/file_types/<string:type_category>',
        'manage_file_types',
        lambda type_category: '',
        methods=['GET', 'POST', 'PUT', 'DELETE'],
    )

    @legacy.errorhandler(405)
    def legacy_api_405(error):
        from oneirodex.utils.api_contract import api_error_payload

        payload, status = api_error_payload(
            error.description, code='bad_request', status=405,
        )
        return jsonify(payload), status

    current = FastAPI()
    router = create_system_file_types_router(
        SimpleNamespace(config=legacy.config),
        find_user=lambda _user_id: None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        data_access=object(),
    )
    current.include_router(router)
    asgi._install_native_api_error_handlers(
        current, legacy.config, logging.getLogger('file-type-405-parity-test'),
        routing_app=legacy,
    )

    legacy_response = legacy.test_client().open(
        '/api/file_types/allowed', method='PATCH',
    )
    current_response = TestClient(current).patch('/api/file_types/allowed')

    assert current_response.status_code == legacy_response.status_code == 405
    assert current_response.headers['content-type'] == legacy_response.headers['Content-Type']
    assert json.loads(current_response.content) == json.loads(legacy_response.get_data())
    assert 'allow' not in current_response.headers


def test_file_types_head_uses_read_result():
    request = Request({
        'type': 'http',
        'method': 'HEAD',
        'path': '/api/file_types/allowed',
        'root_path': '',
        'scheme': 'http',
        'query_string': b'',
        'headers': [],
        'server': ('testserver', 80),
        'client': ('testclient', 1),
    })
    data = SimpleNamespace(list=lambda _category: [{'id': 1, 'value': 'nes'}])

    response = asyncio.run(_handle_file_type_request(request, 'allowed', data))

    assert response.status_code == 200
    assert json.loads(response.body) == [{'id': 1, 'value': 'nes'}]


def test_file_type_value_dot_only_is_rejected():
    assert validate_file_type_value('.') is None

