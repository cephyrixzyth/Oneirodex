from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.licensed_catalog_reads import (
    create_licensed_catalog_reads_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.runtime_native.session_compat import generate_csrf_token


class FakeCatalogData:
    def __init__(self):
        self.reports = []
        self.statuses = []

    def report(self, platform, user):
        self.reports.append((platform, user.id))
        return {'platform': platform, 'unique_titles': 2}

    def status(self, platform):
        self.statuses.append(platform)
        return {'platform': platform, 'age_seconds': 30}

    def refresh(self, platform):
        self.statuses.append(f'refresh:{platform}')
        return {'library_platform': platform, 'unique_titles': 4, 'pages': 1}


def _client(*, role='user'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-licensed-catalog-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=62, user_id='catalog-user', name='catalog-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeCatalogData()
    router = create_licensed_catalog_reads_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 62 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '62' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '62:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, csrf


def test_member_catalog_and_admin_status_keep_envelopes_and_scope():
    client, data, _csrf = _client(role='admin')
    report = client.get('/api/licensed-catalog?library_platform=NES')
    status = client.get('/api/licensed-catalog/status?platform=NES')

    assert report.status_code == 200
    assert report.json()['ok'] is True
    assert report.json()['unique_titles'] == 2
    assert status.status_code == 200
    assert status.json()['age_seconds'] == 30
    assert data.reports == [('NES', 62)]
    assert data.statuses == ['NES']


def test_catalog_validation_and_admin_gate_precede_data_reads():
    admin_client, admin_data, _csrf = _client(role='admin')
    missing_platform = admin_client.get('/api/licensed-catalog/status')
    client, data, _csrf = _client(role='user')
    non_admin = client.get('/api/licensed-catalog/status?platform=NES', follow_redirects=False)

    assert missing_platform.status_code == 400
    assert missing_platform.json()['error_code'] == 'bad_request'
    assert non_admin.status_code == 302
    assert admin_data.statuses == []
    assert data.statuses == []


def test_refresh_requires_csrf_before_provider_action(monkeypatch):
    from oneirodex.utils import event_logging

    monkeypatch.setattr(event_logging, 'log_system_event', lambda *_args, **_kwargs: None)
    client, data, csrf = _client(role='admin')
    response = client.post(
        '/api/licensed-catalog/refresh',
        json={'library_platform': 'NES'},
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['unique_titles'] == 4
    assert data.statuses == ['refresh:NES']


def test_refresh_rejects_missing_csrf_without_provider_action():
    client, data, _csrf = _client(role='admin')
    response = client.post(
        '/api/licensed-catalog/refresh',
        json={'library_platform': 'NES'},
    )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.statuses == []
