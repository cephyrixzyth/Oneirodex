from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.browse import create_browse_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie
from oneirodex.utils.filter_tree import FilterTreeError


class FakeBrowseData:
    def __init__(self, *, error=None, payload=None):
        self.error = error
        self.payload_value = payload or {
            'games': [], 'total': 0, 'pages': 0, 'current_page': 1,
        }
        self.args = None
        self.user = None

    def query(self, args, user):
        self.args = args
        self.user = user
        if self.error:
            raise self.error
        return object()

    def payload(self, _result):
        return self.payload_value


def make_client(data, *, authenticated=True, login_message='Please log in.'):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='browse-test-secret', TESTING=True)
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
    app.include_router(create_browse_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '7' else None,
        login_manager=login_manager,
        data_access=data,
    ))
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '7:fp'}, 'browse-test-secret'),
        )
    return client


def test_anonymous_browse_redirects_with_path_next_flash_and_signed_cookie():
    response = make_client(FakeBrowseData(), authenticated=False).get(
        '/browse_games?page=2&sort_by=name', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fbrowse_games%3Fpage%3D2%26sort_by%3Dname'
    )
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    session = load_session_cookie(
        response.cookies.get('session'), 'browse-test-secret', max_age=3600,
    )
    assert session['_flashes'] == [('message', 'Please log in.')]


def test_empty_login_message_does_not_set_session_cookie():
    response = make_client(
        FakeBrowseData(), authenticated=False, login_message='',
    ).get('/browse_games', follow_redirects=False)
    assert response.status_code == 302
    assert 'set-cookie' not in response.headers


def test_query_parsing_uses_werkzeug_typed_multidict_semantics():
    data = FakeBrowseData()
    response = make_client(data).get('/browse_games?page=12&rating=bad&rating=4&sort_by=recent')
    assert response.status_code == 200
    assert data.args.get('page', 1, type=int) == 12
    assert data.args.get('rating', type=int) is None
    assert data.args.get('sort_by') == 'recent'
    assert data.user.id == 7


def test_filter_tree_error_keeps_bad_request_envelope_and_path_detail():
    data = FakeBrowseData(error=FilterTreeError('Unknown field "genre"', path='parts.1.field'))
    response = make_client(data).get('/browse_games')
    assert response.status_code == 400
    assert response.json() == {
        'ok': False,
        'error': 'Unknown field "genre" (at parts.1.field)',
        'error_code': 'bad_request',
        'detail': {'path': 'parts.1.field'},
        'message': 'Unknown field "genre" (at parts.1.field)',
        'success': False,
    }


def test_success_shape_is_exact_and_uses_flask_json_provider_serialization():
    data = FakeBrowseData(payload={
        'games': [{
            'uuid': UUID('12345678-1234-5678-1234-567812345678'),
            'identified_at': datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            'weight': Decimal('1.25'),
        }],
        'total': 1,
        'pages': 1,
        'current_page': 1,
    })
    response = make_client(data).get('/browse_games')
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'games', 'total', 'pages', 'current_page'}
    assert body == {
        'games': [{
            'uuid': '12345678-1234-5678-1234-567812345678',
            'identified_at': 'Fri, 02 Jan 2026 03:04:05 GMT',
            'weight': '1.25',
        }],
        'total': 1,
        'pages': 1,
        'current_page': 1,
    }
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_browse_head_is_supported_and_has_no_body():
    response = make_client(FakeBrowseData()).head('/browse_games')
    assert response.status_code == 200
    assert response.content == b''
