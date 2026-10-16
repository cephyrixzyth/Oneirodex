"""GT-B1 — API envelope contract.

These assertions are the contract the SPA error component (PageStatus) relies
on. The back-compat mirrors are tested deliberately: ~699 legacy call sites read
`error` / `message` / `success`, and migration is incremental, so breaking those
keys would break unmigrated pages silently.
"""

import json

import pytest
from flask import Flask

from oneirodex.utils.api_response import api_error, api_ok, ERROR_CODES
from oneirodex.utils.api_contract import api_error_payload, api_ok_payload


@pytest.fixture()
def app():
    return Flask(__name__)


def _body(app, rv):
    response, status = rv
    with app.app_context():
        return json.loads(response.get_data(as_text=True)), status


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def test_api_error_shape(app):
    with app.test_request_context():
        body, status = _body(app, api_error('Admin required', code='forbidden'))

    assert status == 403
    assert body['ok'] is False
    assert body['error'] == 'Admin required'
    assert body['error_code'] == 'forbidden'


def test_api_error_keeps_error_as_a_string(app):
    """`error` must stay a plain string.

    Unmigrated callers render `data.error` directly; making it an object would
    put "[object Object]" on screen across the whole product.
    """
    with app.test_request_context():
        body, _ = _body(app, api_error('Nope', code='not_found', detail={'field': 'uuid'}))

    assert isinstance(body['error'], str)
    assert body['detail'] == {'field': 'uuid'}


def test_api_error_legacy_mirrors(app):
    with app.test_request_context():
        body, _ = _body(app, api_error('Boom', code='internal'))

    assert body['message'] == 'Boom'
    assert body['success'] is False


def test_api_error_explicit_status_wins(app):
    """Existing 403-vs-503 route contracts must not shift when migrated."""
    with app.test_request_context():
        body, status = _body(app, api_error('Disabled', code='forbidden', status=503))

    assert status == 503
    assert body['error_code'] == 'forbidden'


def test_api_error_blank_message_falls_back(app):
    with app.test_request_context():
        body, _ = _body(app, api_error('   '))

    assert body['error'] == 'Request failed'


def test_api_error_unknown_code_defaults_to_400(app):
    with app.test_request_context():
        _, status = _body(app, api_error('Weird', code='not_a_real_code'))

    assert status == 400


def test_api_error_body_status_does_not_shift_http(app):
    """Classic JS reads `data.status`; HTTP `status=` must stay the code."""
    with app.test_request_context():
        body, status = _body(app, api_error(
            'Could not clear the entry',
            code='internal',
            body_status='error',
        ))

    assert status == 500
    assert body['ok'] is False
    assert body['status'] == 'error'
    assert body['error'] == 'Could not clear the entry'
    assert body['message'] == 'Could not clear the entry'


def test_api_error_body_code_keeps_honesty_markers(app):
    with app.test_request_context():
        body, status = _body(app, api_error(
            'Version file is missing on disk',
            code='not_found',
            status=410,
            body_code='path_missing',
            path_missing=True,
        ))

    assert status == 410
    assert body['error_code'] == 'not_found'
    assert body['code'] == 'path_missing'
    assert body['path_missing'] is True


def test_api_error_body_error_keeps_machine_token(app):
    with app.test_request_context():
        body, _ = _body(app, api_error(
            'Type the exact library name to confirm.',
            code='bad_request',
            body_status='rejected',
            body_error='confirm_name_required',
        ))

    assert body['error'] == 'confirm_name_required'
    assert body['message'] == 'Type the exact library name to confirm.'
    assert body['status'] == 'rejected'


@pytest.mark.parametrize(
    ('message', 'options'),
    [
        ('Admin required', {'code': 'forbidden'}),
        ('  ', {}),
        ('Method not allowed', {'code': 'bad_request', 'status': 405}),
        ('Disabled', {'code': 'forbidden', 'status': 503}),
        ('Missing', {'code': 'not_found', 'detail': {'field': 'id'}, 'path': '/safe'}),
        (
            'Type the exact library name to confirm.',
            {'code': 'bad_request', 'body_status': 'rejected',
             'body_error': 'confirm_name_required'},
        ),
    ],
)
def test_framework_independent_error_contract_matches_flask(app, message, options):
    """Native ASGI errors and legacy Flask errors must serialize identically."""
    with app.test_request_context():
        flask_body, flask_status = _body(app, api_error(message, **options))
    native_body, native_status = api_error_payload(message, **options)

    assert (native_body, native_status) == (flask_body, flask_status)


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------

def test_api_ok_merges_payload_at_top_level(app):
    """Payload keys stay where they are — migration must not move fields."""
    with app.test_request_context():
        body, status = _body(app, api_ok({'games': 12, 'libraries': 3}))

    assert status == 200
    assert body['ok'] is True
    assert body['games'] == 12
    assert body['libraries'] == 3
    assert body['success'] is True
    # `error` and `error_code` are on *every* response, not just failures, so a
    # client reading them does not get `undefined` on the way through.
    assert body['error'] is None
    assert body['error_code'] is None


def test_api_ok_payload_cannot_override_envelope(app):
    with app.test_request_context():
        body, _ = _body(app, api_ok({'ok': False, 'error': 'sneaky', 'error_code': 'x'}))

    assert body['ok'] is True
    # Neutralised rather than absent: the caller's values are still discarded,
    # which is what this pins, but the keys stay present per the contract above.
    assert body['error'] is None
    assert body['error_code'] is None


def test_framework_independent_success_contract_matches_flask(app):
    payload = {'games': 12, 'libraries': 3, 'success': False}
    with app.test_request_context():
        flask_body, _ = _body(app, api_ok(payload, source='native'))

    assert api_ok_payload(payload, source='native') == flask_body


def test_error_codes_map_to_sane_statuses():
    assert ERROR_CODES['forbidden'] == 403
    assert ERROR_CODES['not_found'] == 404
    assert ERROR_CODES['internal'] == 500


def test_upstream_failure_is_distinguishable_from_our_own():
    """`bad_gateway` exists so an operator can tell "the provider answered
    badly" from "we broke" and from "the integration is switched off" — three
    different next actions. Fifteen route sites returned a bare 502 before."""
    assert ERROR_CODES['bad_gateway'] == 502
    assert ERROR_CODES['internal'] == 500
    assert ERROR_CODES['unavailable'] == 503
