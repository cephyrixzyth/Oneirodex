"""Challenge solver client + wiring (CH-1…CH-5)."""

from __future__ import annotations

import ipaddress
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import requests

from oneirodex.utils.challenge_solver import (
    ChallengeSolverClient,
    SolverSolution,
    TokenCaptchaClient,
    fetch_with_challenge_retry,
    is_challenge_response,
)


def _mock_response(status: int, text: str = '', headers: dict | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = text.encode('utf-8')
    resp.headers = headers or {}
    resp.url = 'https://example.test/page'
    return resp


def _stream_response(status: int, body: bytes, headers: dict | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.headers.update(headers or {})
    resp.raw = BytesIO(body)
    resp._content = False
    resp.url = 'https://example.test/search'
    return resp


def test_is_challenge_response_cloudflare_503():
    body = '<html><title>Just a moment...</title><body>Checking your browser before accessing cloudflare</body></html>'
    assert is_challenge_response(_mock_response(503, body)) is True


def test_is_challenge_response_normal_json_200():
    assert is_challenge_response(_mock_response(200, '[{"title":"Game"}]')) is False


def test_is_challenge_response_403_single_marker_not_enough():
    assert is_challenge_response(_mock_response(403, 'access denied for this resource')) is False


def test_challenge_solver_client_parses_flaresolverr_solution():
    session = MagicMock()
    response = MagicMock(
        status_code=200,
        content=b'{"status":"ok","solution":{"url":"https://idx.test/results","status":200,"response":"[{\\"title\\":\\"Ok\\"}]","cookies":[{"name":"cf_clearance","value":"abc"}],"userAgent":"Mozilla/5.0"}}',
        json=lambda: {
            'status': 'ok',
            'solution': {
                'url': 'https://idx.test/results',
                'status': 200,
                'response': '[{"title":"Ok"}]',
                'cookies': [{'name': 'cf_clearance', 'value': 'abc'}],
                'userAgent': 'Mozilla/5.0 Test',
            },
        },
    )
    client = ChallengeSolverClient('http://solver:8191', session=session)
    with patch('oneirodex.utils.challenge_solver.safe_request_limited', return_value=response) as safe_post:
        solution = client.request_get('https://idx.test/results')
    assert isinstance(solution, SolverSolution)
    assert solution.status_code == 200
    assert solution.body == '[{"title":"Ok"}]'
    assert solution.cookie_header() == 'cf_clearance=abc'
    assert solution.user_agent == 'Mozilla/5.0 Test'
    safe_post.assert_called_once()
    call_args = safe_post.call_args
    assert call_args[0] == ('POST', 'http://solver:8191/v1')
    assert call_args[1]['json']['cmd'] == 'request.get'
    assert call_args[1]['validator'].__name__ == 'validate_connector_http_url'
    assert call_args[1]['max_redirects'] == 0
    assert call_args[1]['max_response_bytes'] == 16 * 1024 * 1024
    assert call_args[1]['session'] is session


def test_challenge_solver_rejects_redirects():
    session = MagicMock()
    client = ChallengeSolverClient('http://solver:8191', session=session)
    with patch(
        'oneirodex.utils.challenge_solver.safe_request_limited',
        side_effect=requests.TooManyRedirects,
    ) as safe_post:
        with pytest.raises(RuntimeError, match='redirect refused'):
            client.request_get('https://idx.test/results')
    assert safe_post.call_args.kwargs['max_redirects'] == 0


def test_challenge_solver_transport_pins_the_resolved_destination(monkeypatch):
    solver_body = b'{"status":"ok","solution":{"url":"https://idx.test/x","status":200,"response":"ok"}}'

    class NoNetworkSession(requests.Session):
        def __init__(self):
            super().__init__()
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            response = requests.Response()
            response.status_code = 200
            response.url = url
            response.raw = BytesIO(solver_body)
            response._content = False
            return response

    monkeypatch.setattr(
        'oneirodex.utils.security._resolve_host',
        lambda _host: [ipaddress.ip_address('93.184.216.34')],
    )
    session = NoNetworkSession()
    client = ChallengeSolverClient('http://solver.example:8191', session=session)

    solution = client.request_get('https://idx.test/x')

    assert solution.body == 'ok'
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == 'POST'
    assert url == 'http://93.184.216.34:8191/v1'
    assert kwargs['headers']['Host'] == 'solver.example:8191'
    assert kwargs['stream'] is True
    assert kwargs['json']['cmd'] == 'request.get'
    session.close()


def test_challenge_solver_client_trawl_scrape():
    session = MagicMock()
    response = MagicMock(
        status_code=200,
        content=b'{}',
        json=lambda: {
            'tier': 2,
            'timings': {'total': 1.2},
            'solution': {
                'url': 'https://idx.test/x',
                'status': 200,
                'response': 'ok',
                'cookies': [],
            },
        },
    )
    client = ChallengeSolverClient('http://trawl:8191', provider='trawl', max_tier=5, session=session)
    with patch('oneirodex.utils.challenge_solver.safe_request_limited', return_value=response) as safe_post:
        solution = client.request_get('https://idx.test/x')
    assert solution.body == 'ok'
    assert safe_post.call_args[0][1] == 'http://trawl:8191/scrape'
    assert safe_post.call_args.kwargs['json']['maxTier'] == 4


def test_challenge_solver_trawl_fallback_does_not_log_remote_error_text(caplog):
    secret_url = 'https://indexer.example/search?passkey=private-passkey'
    session = MagicMock()
    responses = [
        MagicMock(
            status_code=200,
            content=b'{"status":"error"}',
            json=lambda: {'status': 'error', 'message': f'failed: {secret_url}'},
        ),
        MagicMock(
            status_code=200,
            content=b'{"status":"ok"}',
            json=lambda: {
                'status': 'ok',
                'solution': {
                    'url': 'https://indexer.example/search',
                    'status': 200,
                    'response': 'ok',
                    'cookies': [],
                },
            },
        ),
    ]
    client = ChallengeSolverClient('http://solver:8191', provider='trawl', session=session)

    with caplog.at_level('DEBUG', logger='oneirodex.utils.challenge_solver'):
        with patch(
            'oneirodex.utils.challenge_solver.safe_request_limited',
            side_effect=responses,
        ):
            solution = client.request_get(secret_url)

    assert solution.body == 'ok'
    assert 'private-passkey' not in caplog.text


def test_token_captcha_client_create_task_never_logs_key(caplog):
    session = MagicMock()
    secret = 'super-secret-capsolver-key'
    session.post.return_value = MagicMock(
        status_code=200,
        content=b'{}',
        json=lambda: {'errorId': 0, 'taskId': 'task-123'},
    )
    client = TokenCaptchaClient('https://api.capsolver.com', secret, session=session)
    task_id = client.create_task(
        'ReCaptchaV2TaskProxyLess',
        website_url='https://example.test',
        website_key='site-key',
    )
    assert task_id == 'task-123'
    posted = session.post.call_args[1]['json']
    assert posted['clientKey'] == secret
    assert secret not in caplog.text
    assert session.post.call_args.kwargs['allow_redirects'] is False


def test_token_captcha_client_rejects_redirects_without_forwarding_key():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=308)
    client = TokenCaptchaClient('https://api.capsolver.com', 'secret', session=session)
    with pytest.raises(RuntimeError, match='Token API redirect refused'):
        client.create_task('ReCaptchaV2TaskProxyLess', website_url='https://example.test', website_key='site-key')
    assert session.post.call_args.kwargs['allow_redirects'] is False


def test_fetch_with_challenge_retry_solver_once(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ENABLE_CHALLENGE_SOLVER', True)
    monkeypatch.setitem(app.config, 'CHALLENGE_SOLVER_URL', 'http://solver:8191')
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)

    challenged = _mock_response(
        503,
        '<html><title>Just a moment...</title>cloudflare challenge-platform</html>',
    )
    success = _mock_response(200, '[{"title":"Hit"}]')

    with app.app_context():
        with patch('oneirodex.utils.challenge_solver.requests.get', side_effect=[challenged, success]) as mock_get:
            with patch('oneirodex.utils.challenge_solver.ChallengeSolverClient.request_get') as mock_solve:
                mock_solve.return_value = SolverSolution(
                    url='https://idx.test/search',
                    status_code=200,
                    body='[{"title":"Hit"}]',
                    headers={},
                    cookies=[{'name': 'cf_clearance', 'value': 'xyz'}],
                    user_agent='UA/1.0',
                )
                resp = fetch_with_challenge_retry(
                    'get',
                    'https://idx.test/search',
                    headers={'X-Api-Key': 'k'},
                    timeout=5,
                )
    assert mock_get.call_count == 2
    assert mock_solve.call_count == 1
    assert resp.status_code == 200


def _disable_challenge_solver(app, db_session, monkeypatch):
    """Env off + clear DB toggle (test DB may retain prior saves)."""
    from sqlalchemy.orm.attributes import flag_modified

    from oneirodex.models import GlobalSettings

    monkeypatch.setitem(app.config, 'ENABLE_CHALLENGE_SOLVER', False)
    row = db_session.query(GlobalSettings).order_by(GlobalSettings.id).first()
    if row is None:
        return
    cfg = dict(row.arr_settings) if isinstance(row.arr_settings, dict) else {}
    cfg['challenge_solver_enabled'] = False
    cfg.pop('challenge_solver_max_tier', None)
    row.arr_settings = cfg
    flag_modified(row, 'arr_settings')
    db_session.commit()
    monkeypatch.setitem(app.config, 'CHALLENGE_SOLVER_MAX_TIER', 5)


def test_fetch_with_challenge_retry_disabled_unchanged(app, db_session, monkeypatch):
    _disable_challenge_solver(app, db_session, monkeypatch)
    challenged = _mock_response(
        503,
        '<html><title>Just a moment...</title>cloudflare challenge-platform</html>',
    )
    with app.app_context():
        with patch('oneirodex.utils.challenge_solver.requests.get', return_value=challenged) as mock_get:
            with patch('oneirodex.utils.challenge_solver.ChallengeSolverClient.request_get') as mock_solve:
                resp = fetch_with_challenge_retry('get', 'https://idx.test/search', timeout=5)
    assert mock_get.call_count == 1
    assert mock_solve.call_count == 0
    assert resp.status_code == 503


def test_fetch_with_challenge_retry_bounds_streamed_response_and_keeps_small_control(monkeypatch):
    from oneirodex.utils.http_safe import ResponseTooLarge

    small = _stream_response(200, b'{"results":[]}')
    session = requests.Session()
    monkeypatch.setattr(session, 'get', MagicMock(return_value=small))
    response = fetch_with_challenge_retry(
        'get', 'https://indexer.example/search', session=session,
        max_response_bytes=64,
    )
    assert response.text == '{"results":[]}'
    assert session.get.call_args.kwargs['stream'] is True
    session.close()

    large = _stream_response(200, b'x' * 65)
    session = requests.Session()
    monkeypatch.setattr(session, 'get', MagicMock(return_value=large))
    with pytest.raises(ResponseTooLarge):
        fetch_with_challenge_retry(
            'get', 'https://indexer.example/search', session=session,
            max_response_bytes=64,
        )
    assert large.raw.closed
    session.close()


def test_bounded_fetch_keeps_the_validated_safe_request_path(monkeypatch):
    from oneirodex.utils import http_safe

    response = _stream_response(200, b'{"results":[]}')
    session = requests.Session()
    seen = {}

    def fake_safe_request(method, url, *, validator, session, **kwargs):
        seen.update(method=method, url=url, validator=validator, session=session, **kwargs)
        return response

    monkeypatch.setattr(http_safe, 'safe_request', fake_safe_request)

    def validator(url):
        return True, url

    bounded = fetch_with_challenge_retry(
        'get', 'https://indexer.example/search', session=session,
        validator=validator, max_response_bytes=64,
    )

    assert bounded.text == '{"results":[]}'
    assert seen['session'] is session
    assert seen['validator'] is validator
    assert seen['stream'] is True
    session.close()


def test_fetch_with_challenge_retry_bounds_challenge_detection_and_retry(monkeypatch):
    from oneirodex.utils import challenge_solver
    from oneirodex.utils.http_safe import ResponseTooLarge

    challenge = _stream_response(
        503, b'<title>Just a moment...</title>' + b'x' * 80,
    )
    session = requests.Session()
    monkeypatch.setattr(session, 'get', MagicMock(return_value=challenge))
    solver = MagicMock()
    monkeypatch.setattr(challenge_solver, 'challenge_solver_enabled', lambda *_args: True)
    monkeypatch.setattr(challenge_solver, '_solver_client', lambda *_args: solver)
    with pytest.raises(ResponseTooLarge):
        fetch_with_challenge_retry(
            'get', 'https://indexer.example/search', session=session,
            max_response_bytes=64,
        )
    solver.request_get.assert_not_called()
    session.close()

    first = _stream_response(503, b'<title>Just a moment...</title>')
    retry = _stream_response(503, b'<title>Just a moment...</title>')
    session = requests.Session()
    monkeypatch.setattr(session, 'get', MagicMock(side_effect=[first, retry]))
    solver.request_get.return_value = SolverSolution(
        url='https://indexer.example/search', status_code=200,
        body='x' * 65, headers={}, cookies=[], user_agent=None,
    )
    with pytest.raises(ResponseTooLarge):
        fetch_with_challenge_retry(
            'get', 'https://indexer.example/search', session=session,
            max_response_bytes=64,
        )
    assert session.get.call_count == 2
    session.close()


def test_challenge_solver_failure_does_not_retain_or_log_url_secrets(monkeypatch, caplog):
    from oneirodex.utils import challenge_solver

    source_url = 'https://indexer.example/search?passkey=private-passkey'
    exception_text = f'failed to contact {source_url}; token=private-token'
    challenged = _mock_response(
        503,
        '<html><title>Just a moment...</title>cloudflare challenge-platform</html>',
    )
    monkeypatch.setattr(challenge_solver, 'challenge_solver_enabled', lambda *_args: True)
    monkeypatch.setattr(
        challenge_solver,
        '_solver_client',
        lambda *_args: MagicMock(request_get=MagicMock(side_effect=RuntimeError(exception_text))),
    )
    monkeypatch.setattr(
        challenge_solver.requests,
        'get',
        MagicMock(return_value=challenged),
    )
    monkeypatch.setattr(challenge_solver, '_arr_cfg', lambda: {})

    with caplog.at_level('WARNING', logger='oneirodex.utils.challenge_solver'):
        response = challenge_solver.fetch_with_challenge_retry('get', source_url)

    status = challenge_solver.challenge_solver_status(
        config={
            'ENABLE_CHALLENGE_SOLVER': True,
            'CHALLENGE_SOLVER_URL': 'http://solver:8191',
            'CHALLENGE_SOLVER_PROVIDER': 'flaresolverr_compat',
        },
    )

    assert response.status_code == 503
    assert 'private-passkey' not in caplog.text
    assert 'private-token' not in caplog.text
    assert 'private-passkey' not in (status['last_error'] or '')
    assert 'private-token' not in (status['last_error'] or '')


def test_challenge_solver_status_api(client, app, db_session, monkeypatch):
    _disable_challenge_solver(app, db_session, monkeypatch)
    from uuid import uuid4

    from oneirodex.models import User

    admin = User(
        user_id=str(uuid4()),
        name=f'chadmin_{uuid4().hex[:8]}',
        email=f'chadmin_{uuid4().hex[:8]}@test.local',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True
    resp = client.get('/api/admin/challenge-solver/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['enabled'] is False
    assert data['provider'] == 'flaresolverr_compat'
    assert data['max_tier'] == 5


def test_save_challenge_config_validates_url(app, db_session, global_settings, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        from oneirodex.utils.challenge_solver import save_challenge_config

        saved = save_challenge_config({
            'enabled': True,
            'url': 'http://192.168.1.10:8191',
            'max_tier': 6,
        })
        assert saved['db_enabled'] is True
        assert saved['url'] == 'http://192.168.1.10:8191'
        assert saved['max_tier'] == 6

        with pytest.raises(ValueError, match='not allowed'):
            save_challenge_config({'url': 'http://169.254.169.254/'})
