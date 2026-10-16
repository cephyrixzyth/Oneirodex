"""Unit tests for ``validate_body`` and ``validate_batch_body`` (wave A2.4).

DB-free: a throwaway Flask app with decorated routes exercises the helpers
in isolation from any real API surface.
"""

from __future__ import annotations

import json

import pytest
from flask import Flask
from pydantic import BaseModel, ConfigDict, Field

from oneirodex.utils.validation import (
    format_validation_errors,
    read_json_body,
    validate_batch_body,
    validate_body,
)


class _Body(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1)
    count: int = 5


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.post('/echo')
    @validate_body(_Body)
    def echo(body: _Body):  # noqa: D401 - test route
        return {'name': body.name, 'count': body.count, 'type': type(body).__name__}

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_valid_body_passes_through_typed(client):
    resp = client.post('/echo', json={'name': 'Cozy', 'count': 9})
    assert resp.status_code == 200
    assert resp.get_json() == {'name': 'Cozy', 'count': 9, 'type': '_Body'}


def test_valid_body_applies_defaults(client):
    resp = client.post('/echo', json={'name': 'Cozy'})
    assert resp.status_code == 200
    assert resp.get_json()['count'] == 5


def test_missing_required_field_is_422_with_detail(client):
    resp = client.post('/echo', json={'count': 3})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body['ok'] is False
    assert body['error'] == 'Invalid request.'
    assert body['error_code'] == 'unprocessable'
    assert 'name' in body['detail']
    assert isinstance(body['detail']['name'], str)


def test_unknown_key_rejected_by_extra_forbid(client):
    resp = client.post('/echo', json={'name': 'Cozy', 'surprise': 1})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body['error_code'] == 'unprocessable'
    assert 'surprise' in body['detail']


def test_wrong_type_is_422_not_500(client):
    resp = client.post('/echo', json={'name': 'Cozy', 'count': 'lots'})
    assert resp.status_code == 422
    assert 'count' in resp.get_json()['detail']


def test_malformed_json_is_handled_as_empty_body(client):
    resp = client.post(
        '/echo',
        data='{not json at all',
        content_type='application/json',
    )
    # silent=True -> None -> validate {} -> required `name` missing -> 422
    assert resp.status_code == 422
    body = resp.get_json()
    assert body['error_code'] == 'unprocessable'
    assert 'name' in body['detail']


def test_body_that_is_a_json_array_is_422_not_500(client):
    resp = client.post('/echo', data=json.dumps([1, 2, 3]), content_type='application/json')
    assert resp.status_code == 422
    assert resp.get_json()['error_code'] == 'unprocessable'


def test_absent_body_is_422_for_required_model(client):
    resp = client.post('/echo')
    assert resp.status_code == 422
    assert 'name' in resp.get_json()['detail']


def test_read_json_body_preserves_missing_and_non_object_values():
    app = Flask(__name__)
    with app.test_request_context('/body', method='POST'):
        assert read_json_body() is None
    with app.test_request_context(
        '/body', method='POST', data='[]', content_type='application/json'
    ):
        assert read_json_body() == []


def test_detail_carries_no_input_url_or_ctx(client):
    """The offending value, pydantic's help URL and ctx must not leak out."""
    secret = '/etc/passwd-secret-token'
    resp = client.post('/echo', json={'name': '', 'count': secret})
    assert resp.status_code == 422
    raw = resp.get_data(as_text=True)
    assert secret not in raw
    assert 'errors.pydantic.dev' not in raw
    # detail is a flat {field: message-or-list}
    for value in resp.get_json()['detail'].values():
        assert isinstance(value, (str, list))


def test_all_optional_model_accepts_empty_body():
    app = Flask(__name__)
    app.config.update(TESTING=True)

    class _Opt(BaseModel):
        model_config = ConfigDict(extra='forbid')
        note: str | None = None

    @app.post('/opt')
    @validate_body(_Opt)
    def opt(body: _Opt):  # noqa: D401 - test route
        return {'note': body.note}

    resp = app.test_client().post('/opt')
    assert resp.status_code == 200
    assert resp.get_json() == {'note': None}


def test_format_validation_errors_dotted_nested_loc():
    class _Inner(BaseModel):
        id: str

    class _Outer(BaseModel):
        items: list[_Inner]

    try:
        _Outer.model_validate({'items': [{'id': 'ok'}, {}]})
    except Exception as exc:  # pydantic.ValidationError
        formatted = format_validation_errors(exc)
    else:  # pragma: no cover - must raise
        raise AssertionError('expected ValidationError')

    assert 'items[1].id' in formatted


class _Batch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uuids: list
    favorite: bool


@pytest.fixture
def batch_app():
    app = Flask(__name__)
    app.config.update(TESTING=True)

    @app.post('/batch')
    @validate_batch_body(_Batch, limit=100)
    def batch(body: _Batch):  # noqa: D401 - test route
        return {
            'ok': True,
            'uuids': body.uuids,
            'favorite': body.favorite,
            'updated': [],
            'skipped': [],
            'errors': [],
            'limit': 100,
        }

    return app


@pytest.fixture
def batch_client(batch_app):
    return batch_app.test_client()


def test_batch_valid_body_passes_through(batch_client):
    resp = batch_client.post('/batch', json={'uuids': ['a'], 'favorite': False})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['favorite'] is False
    assert body['uuids'] == ['a']


def test_batch_missing_field_is_422_with_partial_success_keys(batch_client):
    resp = batch_client.post('/batch', json={'uuids': ['a']})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body['ok'] is False
    assert body['error'] == 'Invalid request.'
    assert body['error_code'] == 'unprocessable'
    assert 'favorite' in body['detail']
    assert body['updated'] == []
    assert body['skipped'] == []
    assert body['errors'] == []
    assert body['limit'] == 100


def test_batch_non_list_uuids_is_422_not_400(batch_client):
    resp = batch_client.post('/batch', json={'uuids': 'nope', 'favorite': True})
    assert resp.status_code == 422
    body = resp.get_json()
    assert 'uuids' in body['detail']
    assert body['limit'] == 100


def test_batch_flat_validate_body_does_not_stamp_partial_keys(client):
    """The companion exists because the flat helper would drop these keys."""
    resp = client.post('/echo', json={})
    assert resp.status_code == 422
    body = resp.get_json()
    assert 'updated' not in body
    assert 'skipped' not in body
    assert 'errors' not in body
    assert 'limit' not in body
