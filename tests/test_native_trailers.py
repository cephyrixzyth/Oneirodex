from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.trailers import (
    TrailerAuthCallbacks,
    create_trailers_router,
    parse_integer_list,
    parse_year,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeData:
    def __init__(self, *, filters=None, ids=None, game=None):
        self.filter_payload = filters or {
            'libraries': [{'uuid': 'lib-1', 'name': 'Main'}],
            'genres': [{'id': 2, 'name': 'Puzzle'}],
            'themes': [],
            'date_range': {'min_year': 1980, 'max_year': 2025},
        }
        self.ids = [1] if ids is None else ids
        self.game_row = game
        self.seen_params = None

    def filters(self, user):
        assert user.id == 7
        return self.filter_payload

    def random_game_ids(self, user, params):
        assert user.id == 7
        self.seen_params = dict(params)
        return self.ids

    def game(self, game_id):
        assert game_id == 1
        return self.game_row


def make_client(
    data,
    *,
    authenticated=True,
    login_view='login',
    blueprint_login_view=None,
    login_message='Please log in.',
):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-test-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, is_active=True, state=True, role='user')
    callbacks = TrailerAuthCallbacks(
        find_user=lambda user_id: user if authenticated and user_id == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '7' else None,
        login_manager=SimpleNamespace(
            login_view=login_view,
            login_message=login_message,
            login_message_category='message',
            localize_callback=None,
            blueprint_login_views=(
                {'site': blueprint_login_view} if blueprint_login_view else {}
            ),
            unauthorized_callback=None,
        ),
    )
    app = FastAPI()
    app.include_router(create_trailers_router(
        flask_app,
        auth=callbacks,
        data_access=data,
        choose=lambda values: values[0],
    ))
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native trailer route pushed a Flask app context')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session',
            dump_session_cookie({'_user_id': '7:fp'}, 'native-test-secret'),
        )
    return client


def test_filters_anonymous_request_redirects_to_configured_login_with_next():
    response = make_client(FakeData(), authenticated=False).get(
        '/api/trailers/filters', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Ftrailers%2Ffilters'
    )
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        '<a href="/login?next=%2Fapi%2Ftrailers%2Ffilters">'
        '/login?next=%2Fapi%2Ftrailers%2Ffilters</a>. If not, click the link.\n'
    )
    assert len(response.headers.get_list('set-cookie')) == 1
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'cookie' in response.headers['vary'].lower()
    session = load_session_cookie(
        response.cookies.get('session'), 'native-test-secret', max_age=3600,
    )
    assert session['_flashes'] == [('message', 'Please log in.')]

    random_response = make_client(FakeData(), authenticated=False).get(
        '/api/trailers/random', follow_redirects=False,
    )
    assert random_response.status_code == 302
    assert random_response.headers['location'] == '/login?next=%2Fapi%2Ftrailers%2Frandom'
    assert random_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert random_response.text.endswith(
        '<a href="/login?next=%2Fapi%2Ftrailers%2Frandom">'
        '/login?next=%2Fapi%2Ftrailers%2Frandom</a>. If not, click the link.\n'
    )


def test_anonymous_redirect_preserves_absolute_next_for_external_login_origin():
    response = make_client(
        FakeData(), authenticated=False, login_view='https://login.example/login',
    ).get('/api/trailers/filters', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == (
        'https://login.example/login?next=http%3A%2F%2Ftestserver%2Fapi%2Ftrailers%2Ffilters'
    )


def test_anonymous_redirect_uses_blueprint_specific_login_view():
    response = make_client(
        FakeData(), authenticated=False, login_view='login',
        blueprint_login_view='/member/sign-in', login_message='',
    ).get('/api/trailers/filters', follow_redirects=False)
    assert response.headers['location'] == '/member/sign-in?next=%2Fapi%2Ftrailers%2Ffilters'


def test_empty_login_flash_message_does_not_set_a_session_cookie():
    response = make_client(
        FakeData(), authenticated=False, login_message='',
    ).get('/api/trailers/filters', follow_redirects=False)
    assert response.status_code == 302
    assert 'set-cookie' not in response.headers


def test_filters_serialization_uses_legacy_top_level_fields():
    response = make_client(FakeData()).get('/api/trailers/filters')
    assert response.status_code == 200
    assert response.json() == {
        'libraries': [{'uuid': 'lib-1', 'name': 'Main'}],
        'genres': [{'id': 2, 'name': 'Puzzle'}],
        'themes': [],
        'date_range': {'min_year': 1980, 'max_year': 2025},
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }


def test_filters_supports_head_and_keeps_legacy_cache_behavior():
    response = make_client(FakeData()).head('/api/trailers/filters')
    assert response.status_code == 200
    assert response.content == b''
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    # Flask JSON responses did not add an explicit cache or Vary header.
    assert 'cache-control' not in response.headers
    assert 'vary' not in response.headers


def test_integer_and_year_query_parsing_matches_legacy_rules():
    assert parse_integer_list(None) == []
    assert parse_integer_list('  ') == []
    assert parse_integer_list('1, 2,,3') == [1, 2, 3]
    assert parse_year('2001', 1, 1).isoformat() == '2001-01-01T00:00:00'
    assert parse_year('not-a-year', 12, 31) is None
    assert parse_year('10000', 12, 31) is None


def test_random_malformed_genre_query_returns_safe_internal_envelope():
    response = make_client(FakeData()).get('/api/trailers/random?genres=bad')
    assert response.status_code == 500
    assert response.json() == {
        'has_videos': False,
        'empty': False,
        'ok': False,
        'error': 'Error fetching trailer',
        'error_code': 'internal',
        'message': 'Error fetching trailer',
        'success': False,
    }


def test_random_no_candidates_returns_legacy_empty_payload():
    response = make_client(FakeData(ids=[])).get('/api/trailers/random')
    assert response.status_code == 200
    body = response.json()
    assert body['has_videos'] is False
    assert body['empty'] is True
    assert body['code'] == 'no_trailers'
    assert body['cta']['href'] == '/admin/library/add'
    assert body['ok'] is True


def test_random_game_selects_first_video_and_converts_youtube_url():
    data = FakeData(game=SimpleNamespace(
        uuid='game-uuid',
        name='Demo game',
        video_urls=' https://youtu.be/abc123 , https://cdn.example/video.mp4 ',
    ))
    response = make_client(data).get(
        '/api/trailers/random?library_uuid=lib-1&genres=3%2C4&themes=8&date_from=1990&date_to=2020'
    )
    assert response.status_code == 200
    assert data.seen_params == {
        'library_uuid': 'lib-1',
        'genres': '3,4',
        'themes': '8',
        'date_from': '1990',
        'date_to': '2020',
    }
    body = response.json()
    assert body['has_videos'] is True
    assert body['game_uuid'] == 'game-uuid'
    assert body['game_name'] == 'Demo game'
    assert body['video_url'] == 'https://www.youtube.com/embed/abc123?autoplay=1&rel=0'


def test_random_invalid_game_url_returns_no_valid_urls_payload():
    data = FakeData(game=SimpleNamespace(uuid='g', name='Demo', video_urls=', ,'))
    response = make_client(data).get('/api/trailers/random')
    assert response.status_code == 200
    assert response.json()['code'] == 'no_valid_urls'
    assert response.json()['empty'] is True


def test_random_provider_exception_does_not_leak_internal_details():
    class BrokenData(FakeData):
        def random_game_ids(self, user, params):
            raise RuntimeError('secret database connection string')

    response = make_client(BrokenData()).get('/api/trailers/random')
    assert response.status_code == 500
    assert 'secret database connection string' not in response.text
    assert response.json()['error_code'] == 'internal'
