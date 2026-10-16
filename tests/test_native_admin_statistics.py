from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_statistics import create_admin_statistics_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-stats-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='stats-user', name='stats-admin', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_admin_statistics_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        statistics_reader=lambda: {
            'totals': {'games': 12},
            'top_games_table': [{'name': 'Sample', 'downloads': 4}],
        },
        database_scope=lambda _app: __import__('contextlib').nullcontext(),
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
    return client, user


def test_admin_statistics_retains_envelope_and_head_behavior():
    client, _user = _client()
    get = client.get('/api/admin/statistics')
    head = client.head('/api/admin/statistics')
    legacy = client.get('/admin/statistics/data')
    legacy_head = client.head('/admin/statistics/data')

    assert get.status_code == 200
    assert get.json()['ok'] is True
    assert get.json()['totals'] == {'games': 12}
    assert get.json()['top_games_table'][0]['name'] == 'Sample'
    assert get.headers['cache-control'] == 'no-store'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
    assert legacy.status_code == 200
    assert legacy.json() == {
        'totals': {'games': 12},
        'top_games_table': [{'name': 'Sample', 'downloads': 4}],
    }
    assert 'ok' not in legacy.json()
    assert legacy_head.status_code == 200
    assert legacy_head.content == b''
    assert legacy_head.headers['content-length'] == str(len(legacy.content))


def test_non_admin_cannot_read_admin_statistics():
    client, _user = _client(role='user')
    response = client.get('/api/admin/statistics', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
