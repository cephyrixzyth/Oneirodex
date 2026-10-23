from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect

from oneirodex.runtime_native.admin_scan_filters import create_admin_scan_filters_router
from oneirodex.runtime_native.response_compat import flask_redirect_response
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeFilters:
    def __init__(self):
        self.rows = [SimpleNamespace(id=1, filter_pattern='re:.*demo.*', case_sensitive='no')]
        self.next_id = 2
        self.deleted = []

    def list(self):
        return self.rows

    def add(self, pattern, case_sensitive):
        row = SimpleNamespace(id=self.next_id, filter_pattern=pattern, case_sensitive='yes' if case_sensitive else 'no')
        self.next_id += 1
        self.rows.append(row)
        return row

    def delete(self, filter_id):
        self.deleted.append(filter_id)
        return filter_id == 1

    def rollback(self):
        return None


def make_client(data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-scan-filters-secret', WTF_CSRF_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=15, role='admin', is_active=True, state=True, is_authenticated=True, session_fingerprint=lambda: 'fp')
    manager = SimpleNamespace(login_view='login.login', blueprint_login_views={}, login_message='Please log in.', login_message_category='message', localize_callback=None, session_protection='basic')
    app = FastAPI()
    app.include_router(create_admin_scan_filters_router(
        flask_app, find_user=lambda value: user if value == 15 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('15:') else None,
        login_manager=manager, data_access=data or FakeFilters(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '15:fp', '_fresh': True}, 'native-scan-filters-secret'))
    return client


def test_scan_filter_form_redirect_matches_werkzeug_response_exactly():
    legacy = flask_redirect('/admin/edit_filters', code=302)
    current = flask_redirect_response('/admin/edit_filters', status_code=302)

    assert current.status_code == legacy.status_code
    assert current.headers['location'] == legacy.headers['Location']
    assert current.headers['content-type'] == legacy.headers['Content-Type']
    assert current.body == legacy.get_data()


def test_scan_filter_read_create_and_regex_validation():
    data = FakeFilters()
    client = make_client(data)
    read = client.get('/api/admin/scan-filters')
    created = client.post('/api/admin/scan-filters', json={'kind': 'dir', 'pattern': 'Nintendo'})
    invalid = client.post('/api/admin/scan-filters', json={'kind': 'regex', 'pattern': '['})

    assert read.status_code == 200 and read.json()['filters'][0]['kind'] == 'regex'
    assert created.status_code == 201 and created.json()['filter']['filter_pattern'] == 'dir:Nintendo'
    assert invalid.status_code == 400
    assert len(data.rows) == 2


def test_scan_filter_create_rejects_non_string_patterns_without_writes():
    data = FakeFilters()
    client = make_client(data)
    for pattern in (['Nintendo'], {'name': 'Nintendo'}, 7, True):
        response = client.post(
            '/api/admin/scan-filters', json={'kind': 'name', 'pattern': pattern},
        )
        assert response.status_code == 400
        assert response.json()['ok'] is False
    assert len(data.rows) == 1


def test_scan_filter_delete_reports_missing_rows():
    client = make_client()
    removed = client.delete('/api/admin/scan-filters/1')
    missing = client.delete('/api/admin/scan-filters/2')

    assert removed.status_code == 200
    assert missing.status_code == 404


def test_legacy_scan_filter_post_redirects_and_flashes_after_deletion(monkeypatch):
    tokens = []
    monkeypatch.setattr(
        'oneirodex.runtime_native.csrf_compat.csrf_error_response',
        lambda _request, _session, _config, *, token=None: tokens.append(token),
    )
    data = FakeFilters()
    client = make_client(data)

    response = client.post(
        '/delete_filter/1', data={'csrf_token': 'form-token'}, follow_redirects=False,
    )

    assert response.status_code == 302, response.text
    assert response.headers['location'] == '/admin/edit_filters'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert '<a href="/admin/edit_filters">/admin/edit_filters</a>' in response.text
    assert data.deleted == [1]
    assert tokens == ['form-token']
    session = load_session_cookie(
        response.cookies.get('session'), 'native-scan-filters-secret', max_age=3600,
    )
    assert session['_flashes'] == [('message', 'Scanning filter removed.')]


def test_legacy_scan_filter_add_redirects_and_flashes(monkeypatch):
    from oneirodex.runtime_native import csrf_compat

    monkeypatch.setattr(csrf_compat, 'csrf_error_response', lambda *_args, **_kwargs: None)
    data = FakeFilters()
    client = make_client(data)
    response = client.post(
        '/admin/edit_filters',
        data={'csrf_token': 'form-token', 'filter_pattern': 'Scene Release', 'case_sensitive': 'yes'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/edit_filters'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert '<a href="/admin/edit_filters">/admin/edit_filters</a>' in response.text
    assert data.rows[-1].filter_pattern == 'Scene Release'
    assert data.rows[-1].case_sensitive == 'yes'
    session = load_session_cookie(
        response.cookies.get('session'), 'native-scan-filters-secret', max_age=3600,
    )
    assert session['_flashes'] == [('message', 'New scanning filter added.')]


def test_legacy_scan_filter_blank_validation_matches_wtforms(monkeypatch):
    from oneirodex.runtime_native import csrf_compat

    monkeypatch.setattr(csrf_compat, 'csrf_error_response', lambda *_args, **_kwargs: None)
    data = FakeFilters()
    client = make_client(data)
    response = client.post(
        '/admin/edit_filters',
        data={'csrf_token': 'form-token', 'filter_pattern': '   ', 'case_sensitive': 'no'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    session = load_session_cookie(
        response.cookies.get('session'), 'native-scan-filters-secret', max_age=3600,
    )
    assert session['_flashes'] == [('danger', 'This field is required.')]
    assert len(data.rows) == 1


def test_legacy_scan_filter_invalid_choice_matches_wtforms(monkeypatch):
    from oneirodex.runtime_native import csrf_compat

    monkeypatch.setattr(csrf_compat, 'csrf_error_response', lambda *_args, **_kwargs: None)
    data = FakeFilters()
    client = make_client(data)
    response = client.post(
        '/admin/edit_filters',
        data={'csrf_token': 'form-token', 'filter_pattern': 'Scene', 'case_sensitive': ''},
        follow_redirects=False,
    )

    assert response.status_code == 302
    session = load_session_cookie(
        response.cookies.get('session'), 'native-scan-filters-secret', max_age=3600,
    )
    assert session['_flashes'] == [('danger', 'Not a valid choice.')]
    assert len(data.rows) == 1


def test_legacy_scan_filter_preserves_whitespace_accepted_by_wtforms(monkeypatch):
    from oneirodex.runtime_native import csrf_compat

    monkeypatch.setattr(csrf_compat, 'csrf_error_response', lambda *_args, **_kwargs: None)
    data = FakeFilters()
    client = make_client(data)
    response = client.post(
        '/admin/edit_filters',
        data={'csrf_token': 'form-token', 'filter_pattern': ' Scene Release ', 'case_sensitive': 'yes'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/edit_filters'
    assert data.rows[-1].filter_pattern == ' Scene Release '
