from __future__ import annotations

from contextlib import nullcontext
import os
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.hltb_refresh import create_hltb_refresh_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


def test_hltb_utility_import_does_not_require_flask_runtime():
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            "import sys; sys.modules['flask'] = None; import oneirodex.utils.hltb",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def _client(*, role='admin', outcome=('updated', {
    'message': 'HLTB data updated for Test', 'data': {'hltb_id': 123},
}), bulk_outcome=('complete', {
    'message': 'Processed 2 games: 1 successful, 1 failed',
    'processed': 2, 'successful': 1, 'failed': 1, 'errors': ['Failed: Not found on HLTB'],
})):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-hltb-refresh-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='hltb-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    bulk_limits = []
    router = create_hltb_refresh_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=SimpleNamespace(
            refresh=lambda _uuid: outcome,
            bulk_refresh=lambda limit: bulk_limits.append(limit) or bulk_outcome,
        ),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    )
    client.bulk_limits = bulk_limits
    return client


def test_hltb_refresh_checks_csrf_and_keeps_success_payload():
    client = _client()
    missing_csrf = client.post('/api/hltb/refresh/game-1')
    response = client.post(
        '/api/hltb/refresh/game-1', headers={'X-CSRFToken': client.csrf_token}
    )
    assert missing_csrf.status_code == 400
    assert response.status_code == 200
    assert response.json()['message'] == 'HLTB data updated for Test'
    assert response.json()['data']['hltb_id'] == 123


def test_hltb_refresh_maps_disabled_missing_and_unmatched_outcomes():
    cases = [
        (('disabled', None), 400, 'HLTB integration is not enabled'),
        (('missing', None), 404, 'Game not found'),
        (('unmatched', None), 404, 'Failed to fetch HLTB data.'),
    ]
    for outcome, expected_status, text in cases:
        client = _client(outcome=outcome)
        response = client.post(
            '/api/hltb/refresh/game-1', headers={'X-CSRFToken': client.csrf_token}
        )
        assert response.status_code == expected_status
        assert text in response.json()['error']


def test_hltb_refresh_requires_admin():
    client = _client(role='user')
    response = client.post(
        '/api/hltb/refresh/game-1', headers={'X-CSRFToken': client.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_hltb_bulk_refresh_checks_csrf_clamps_limit_and_keeps_counts():
    client = _client(bulk_outcome=('complete', {
        'message': 'Processed 2 games: 1 successful, 1 failed',
        'processed': 2, 'successful': 1, 'failed': 1,
    }))
    response = client.post(
        '/api/hltb/bulk-refresh', json={'limit': 999},
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()['processed'] == 2
    assert response.json()['successful'] == 1
    assert response.json()['failed'] == 1
    assert client.bulk_limits == [200]


def test_hltb_bulk_refresh_maps_disabled_and_requires_csrf():
    client = _client(bulk_outcome=('disabled', None))
    missing_csrf = client.post('/api/hltb/bulk-refresh', json={})
    disabled = client.post(
        '/api/hltb/bulk-refresh', json={}, headers={'X-CSRFToken': client.csrf_token}
    )
    assert missing_csrf.status_code == 400
    assert disabled.status_code == 400
    assert disabled.json()['error'] == 'HLTB integration is not enabled'
