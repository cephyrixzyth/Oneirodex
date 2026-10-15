from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.hltb_stats import create_hltb_stats_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


def _client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-hltb-stats-secret', CSP_ENABLED=False)
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
    router = create_hltb_stats_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=data or SimpleNamespace(read=lambda: {
            'total_games': 10,
            'games_with_hltb': 4,
            'games_without_hltb': 6,
            'coverage_percentage': 40.0,
        }),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set(
        'session',
        dump_session_cookie(
            {'_user_id': '71:fingerprint', '_fresh': True},
            flask_app.config['SECRET_KEY'],
        ),
    )
    return client


def test_hltb_stats_keeps_payload_and_head_contract():
    client = _client()
    response = client.get('/api/hltb/stats')
    head = client.head('/api/hltb/stats')

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['stats'] == {
        'total_games': 10,
        'games_with_hltb': 4,
        'games_without_hltb': 6,
        'coverage_percentage': 40.0,
    }
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_hltb_stats_requires_admin():
    response = _client(role='user').get('/api/hltb/stats', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
