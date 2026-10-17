from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.release_calendar import create_release_calendar_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


def make_client(fetch_calendar, *, authenticated=True, login_message='Please log in.'):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='calendar-test-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, is_active=True, state=True, role='user')
    login_manager = SimpleNamespace(
        login_view='login',
        blueprint_login_views={},
        unauthorized_callback=None,
        login_message=login_message,
        login_message_category='message',
        localize_callback=None,
    )
    app = FastAPI()
    app.include_router(create_release_calendar_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '7' else None,
        login_manager=login_manager,
        fetch_calendar=fetch_calendar,
    ))
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '7:fp'}, 'calendar-test-secret'),
        )
    return client


def test_anonymous_calendar_redirects_with_path_next_flash_and_signed_cookie():
    response = make_client(lambda **_kwargs: [], authenticated=False).get(
        '/api/calendar?days_ahead=20', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Fcalendar%3Fdays_ahead%3D20'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        '<a href="/login?next=%2Fapi%2Fcalendar%3Fdays_ahead%3D20">'
        '/login?next=%2Fapi%2Fcalendar%3Fdays_ahead%3D20</a>. If not, click the link.\n'
    )
    assert len(response.headers.get_list('set-cookie')) == 1
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'cookie' in response.headers['vary'].lower()
    session = load_session_cookie(
        response.cookies.get('session'), 'calendar-test-secret', max_age=3600,
    )
    assert session['_flashes'] == [('message', 'Please log in.')]


def test_empty_login_message_does_not_set_session_cookie():
    response = make_client(
        lambda **_kwargs: [], authenticated=False, login_message='',
    ).get('/api/calendar', follow_redirects=False)
    assert response.status_code == 302
    assert 'set-cookie' not in response.headers


def test_invalid_query_values_keep_api_error_envelope():
    response = make_client(lambda **_kwargs: []).get('/api/calendar?limit=nope')
    assert response.status_code == 400
    assert response.json() == {
        'ok': False,
        'error': 'Invalid query parameters',
        'error_code': 'bad_request',
        'message': 'Invalid query parameters',
        'success': False,
    }


def test_query_values_are_clamped_and_empty_igdb_response_is_honest():
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        kwargs['status'].update(reason='not_configured', detail='omitted from response')
        return []

    response = make_client(fetch).get(
        '/api/calendar?days_ahead=999&days_behind=-5&limit=999'
    )
    assert response.status_code == 200
    assert calls[0]['days_ahead'] == 180
    assert calls[0]['days_behind'] == 0
    assert calls[0]['limit'] == 100
    body = response.json()
    assert body['days_ahead'] == 180
    assert body['days_behind'] == 0
    assert body['limit'] == 100
    assert body['count'] == 0
    assert body['releases'] == []
    assert body['empty_reason'] == 'not_configured'
    assert body['source'] == 'igdb'
    assert 'cookie' in response.headers['vary'].lower()
    assert 'cache-control' not in response.headers
    assert 'omitted from response' not in response.text
    datetime.fromisoformat(body['generated_at'])


def test_query_values_apply_lower_and_upper_clamps():
    seen = {}

    def fetch(**kwargs):
        seen.update({key: value for key, value in kwargs.items() if key != 'status'})
        return []

    response = make_client(fetch).get(
        '/api/calendar?days_ahead=0&days_behind=999&limit=0'
    )
    assert response.status_code == 200
    assert seen == {'days_ahead': 1, 'days_behind': 90, 'limit': 1}


def test_fetch_exception_degrades_to_empty_unavailable_payload():
    def fail(**_kwargs):
        raise RuntimeError('private upstream error')

    response = make_client(fail).get('/api/calendar')
    assert response.status_code == 200
    assert response.json()['releases'] == []
    assert response.json()['count'] == 0
    assert response.json()['empty_reason'] == 'unavailable'
    assert 'private upstream error' not in response.text


def test_nonempty_payload_keeps_bare_legacy_shape():
    release = {
        'igdb_id': 42,
        'name': 'Upcoming demo',
        'slug': 'upcoming-demo',
        'first_release_date': '2026-12-01',
        'cover_url': None,
        'rating': 87.5,
        'window': 'upcoming',
    }
    response = make_client(lambda **_kwargs: [release]).get('/api/calendar')
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        'days_ahead', 'days_behind', 'limit', 'count', 'releases',
        'generated_at', 'source', 'empty_reason',
    }
    assert body['count'] == 1
    assert body['releases'] == [release]
    assert body['empty_reason'] is None


def test_calendar_head_is_supported_and_has_no_body():
    response = make_client(lambda **_kwargs: []).head('/api/calendar')
    assert response.status_code == 200
    assert response.content == b''
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
