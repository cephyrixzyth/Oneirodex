import asyncio

import httpx
from flask import Flask

import asgi
from oneirodex.runtime_native.admin_csrf_preflight import (
    admin_request_wants_json,
    empty_admin_mutation_csrf_error,
    inspect_multipart_csrf_body,
    inspect_urlencoded_csrf_body,
    native_route_matches,
)


def _scope(path='/admin/api/ops/mutate', method='POST', headers=()):
    return {'type': 'http', 'path': path, 'method': method, 'headers': headers}


def test_empty_admin_mutation_without_csrf_is_preflighted():
    assert empty_admin_mutation_csrf_error(_scope(), {}) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(headers=[(b'content-length', b'0')]), {},
    ) == 'The CSRF token is missing.'


def test_admin_csrf_preflight_skips_populated_or_tokened_requests():
    assert empty_admin_mutation_csrf_error(
        _scope(headers=[
            (b'content-type', b'application/json'),
            (b'content-length', b'16'),
        ]), {},
    ) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(headers=[
            (b'content-type', b'application/x-www-form-urlencoded'),
            (b'content-length', b'16'),
        ]), {},
    ) is None
    assert empty_admin_mutation_csrf_error(
        _scope(headers=[(b'x-csrftoken', b'token')]), {},
    ) == 'The CSRF session token is missing.'
    assert empty_admin_mutation_csrf_error(_scope(headers=[(b'content-length', b'16')]), {}) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(headers=[(b'transfer-encoding', b'chunked'), (b'content-type', b'multipart/form-data')]), {},
    ) is None


def test_admin_csrf_preflight_is_scoped_by_method_path_and_config():
    assert empty_admin_mutation_csrf_error(
        _scope(path='/api/admin/mutate'), {},
    ) is None
    assert empty_admin_mutation_csrf_error(
        _scope(path='/adminish/mutate'), {},
    ) is None
    assert empty_admin_mutation_csrf_error(_scope(method='GET'), {}) is None
    assert empty_admin_mutation_csrf_error(
        _scope(), {'WTF_CSRF_ENABLED': False},
    ) is None


def test_system_log_clear_bearer_reaches_route_scope_check_only():
    bearer = (b'authorization', b'Bearer synthetic-token')
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/system_logs/clear', method='DELETE', headers=[bearer]), {},
    ) is None
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/users', method='DELETE', headers=[bearer]), {},
    ) == 'The CSRF token is missing.'


def test_admin_user_mutation_bearer_reaches_route_scope_check_only():
    bearer = (b'authorization', b'Bearer synthetic-token')
    for method in ('PUT', 'DELETE'):
        assert empty_admin_mutation_csrf_error(
            _scope(path='/admin/api/user/42', method=method, headers=[bearer]), {},
        ) is None
        assert empty_admin_mutation_csrf_error(
            _scope(path='/admin/api/user/42', method=method), {},
        ) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/user/not-an-id', method='PUT', headers=[bearer]), {},
    ) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/users', method='DELETE', headers=[bearer]), {},
    ) == 'The CSRF token is missing.'


def test_admin_user_create_bearer_reaches_route_scope_check_only():
    bearer = (b'authorization', b'Bearer synthetic-token')
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/user/0', method='PUT', headers=[bearer]), {},
    ) is None
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/user/0', method='PUT'), {},
    ) == 'The CSRF token is missing.'
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/user/00', method='PUT', headers=[bearer]), {},
    ) == 'The CSRF token is missing.'


def test_empty_theme_font_path_miss_is_not_masked_by_csrf_preflight():
    assert empty_admin_mutation_csrf_error(
        _scope(path='/admin/api/theme/fonts/', method='DELETE'), {},
    ) is None


def test_native_route_match_distinguishes_path_misses_from_method_misses():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_api_route(
        '/admin/api/discovery_sections/{section_id:int}',
        lambda section_id: {'id': section_id},
        methods=['PUT', 'DELETE'],
    )
    scope = _scope(path='/admin/api/discovery_sections/9', method='DELETE')
    assert native_route_matches(app, scope)
    assert native_route_matches(
        app, _scope(path='/admin/api/discovery_sections/not-an-integer', method='DELETE'),
    ) is False
    assert native_route_matches(
        app, _scope(path='/admin/api/discovery_sections/9', method='POST'),
    ) is False


def test_valid_header_token_uses_signed_flask_session():
    from oneirodex.runtime_native.session_compat import (
        dump_session_cookie,
        generate_csrf_token,
    )

    secret = 'csrf-preflight-test-secret'
    session = {}
    token = generate_csrf_token(session, secret)
    cookie = dump_session_cookie(session, secret)
    scope = _scope(headers=[
        (b'content-length', b'0'),
        (b'content-type', b'application/json'),
        (b'x-csrftoken', token.encode()),
        (b'cookie', f'session={cookie}'.encode()),
    ])
    assert empty_admin_mutation_csrf_error(scope, {'SECRET_KEY': secret}) is None


def test_urlencoded_form_csrf_inspection_replays_request_body():
    async def run():
        sent = False
        body = b'csrf_token=token-value&field=' + (b'x' * (70 * 1024))

        async def receive():
            nonlocal sent
            if sent:
                return {'type': 'http.disconnect'}
            sent = True
            return {
                'type': 'http.request',
                'body': body,
                'more_body': False,
            }

        scope = _scope(headers=[
            (b'content-type', b'application/x-www-form-urlencoded'),
            (b'content-length', str(len(body)).encode()),
        ])
        token, replay, inspected = await inspect_urlencoded_csrf_body(
            scope, receive, {},
        )
        assert token == 'token-value'
        assert inspected
        assert await replay() == {
            'type': 'http.request',
            'body': body,
            'more_body': False,
        }

    asyncio.run(run())


def test_multipart_form_csrf_inspection_replays_request_body():
    async def run():
        boundary = b'parity-boundary'
        body = (
            b'--parity-boundary\r\n'
            b'Content-Disposition: form-data; name="csrf_token"\r\n\r\n'
            b'token-value\r\n'
            b'--parity-boundary\r\n'
            b'Content-Disposition: form-data; name="upload"; filename="probe.bin"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n'
            + (b'x' * (2 * 1024 * 1024))
            + b'\r\n'
            b'--parity-boundary--\r\n'
        )
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {'type': 'http.disconnect'}
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}

        scope = _scope(headers=[
            (b'content-type', b'multipart/form-data; boundary=parity-boundary'),
            (b'content-length', str(len(body)).encode()),
        ])
        token, replay, inspected = await inspect_multipart_csrf_body(
            scope, receive, {},
        )
        assert token == 'token-value'
        assert inspected
        assert await replay() == {
            'type': 'http.request', 'body': body, 'more_body': False,
        }

    asyncio.run(run())


def test_multipart_preflight_over_limit_replays_unconsumed_body_tail():
    async def run():
        messages = [
            {'type': 'http.request', 'body': b'--boundary', 'more_body': True},
            {'type': 'http.request', 'body': b'--\r\n', 'more_body': False},
        ]

        async def receive():
            return messages.pop(0)

        scope = _scope(headers=[
            (b'content-type', b'multipart/form-data; boundary=boundary'),
            (b'transfer-encoding', b'chunked'),
        ])
        token, replay, inspected = await inspect_multipart_csrf_body(
            scope, receive, {'MAX_CONTENT_LENGTH': 3},
        )
        assert token is None
        assert not inspected
        assert (await replay())['body'] == b'--boundary'
        assert (await replay())['body'] == b'--\r\n'

    asyncio.run(run())


def test_admin_error_format_matches_legacy_negotiation():
    assert not admin_request_wants_json(_scope(path='/admin/api/action'))
    assert admin_request_wants_json(_scope(path='/api/admin/action'))
    assert admin_request_wants_json(
        _scope(headers=[(b'accept', b'application/json')]),
    )
    assert admin_request_wants_json(
        _scope(headers=[(b'x-requested-with', b'XMLHttpRequest')]),
    )


def test_lazy_asgi_returns_legacy_csrf_failure_before_route_auth(monkeypatch):
    runtime = asgi.LazyASGIApp()
    runtime._flask_app = Flask(__name__)
    runtime._flask_app.config.update(SECRET_KEY='test-secret')

    async def ready():
        return None

    monkeypatch.setattr(runtime, '_ensure_flask', ready)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
            follow_redirects=False,
        ) as client:
            return await client.post('/admin/api/art-studio/apply')

    response = asyncio.run(run())
    assert response.status_code == 400
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n<html lang=en>\n'
        '<title>400 Bad Request</title>\n<h1>Bad Request</h1>\n'
        '<p>The CSRF token is missing.</p>\n'
    )

    async def run_invalid_token():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
            follow_redirects=False,
        ) as client:
            return await client.post(
                '/admin/api/art-studio/apply', headers={'X-CSRFToken': 'invalid'},
            )

    invalid = asyncio.run(run_invalid_token())
    assert invalid.status_code == 400
    assert '<p>The CSRF session token is missing.</p>' in invalid.text

    async def run_urlencoded_form():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
            follow_redirects=False,
        ) as client:
            return await client.post(
                '/admin/api/art-studio/apply',
                data={'parity_probe': 'x' * (70 * 1024)},
            )

    form = asyncio.run(run_urlencoded_form())
    assert form.status_code == 400
    assert '<p>The CSRF token is missing.</p>' in form.text

    async def run_multipart_form():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
            follow_redirects=False,
        ) as client:
            return await client.post(
                '/admin/api/art-studio/apply',
                files={'parity_probe': ('probe.txt', b'x', 'text/plain')},
            )

    multipart = asyncio.run(run_multipart_form())
    assert multipart.status_code == 400
    assert '<p>The CSRF token is missing.</p>' in multipart.text
