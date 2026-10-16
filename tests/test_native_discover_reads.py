from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.discover_reads import create_discover_reads_router
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token, load_session_cookie,
)


class FakeDiscoverData:
    def __init__(self, *, row_payload=None):
        self.sections_calls = []
        self.row_calls = []
        self.zone_calls = []
        self.genre_calls = []
        self.genre_id_calls = []
        self.surprise_calls = []
        self.pins_calls = []
        self.save_pins_calls = []
        self.row_payload = row_payload if row_payload is not None else {
            'identifier': 'recent',
            'title': 'Recently added',
            'games': [{'uuid': 'game-1', 'name': 'Example'}],
            'offset': 15,
            'next_offset': 30,
            'feed_token': 'feed-abc',
        }
        self.sections_payload = {
            'sections': [{'id': 'recent', 'title': 'Recently added', 'games': []}],
            'zones': [{'slug': 'era', 'title': 'By era'}],
            'feed_token': 'feed-abc',
        }

    def sections(self, user):
        self.sections_calls.append(user.id)
        return self.sections_payload

    def row(self, user, identifier, *, offset, feed_token, **kwargs):
        self.row_calls.append((user.id, identifier, offset, feed_token, dict(kwargs)))
        return self.row_payload

    def zone(self, user, slug):
        self.zone_calls.append((user.id, slug))
        return {'slug': slug, 'sections': [{'id': 'row-1'}], 'feed_token': 'zone-feed'}

    def genre_hub(self, user, genre):
        self.genre_calls.append((user.id, genre))
        return {'genre': genre, 'sections': [{'id': 'genre-row'}], 'feed_token': 'genre-feed'}

    def genre_by_id(self, genre_id):
        self.genre_id_calls.append(genre_id)
        return SimpleNamespace(id=genre_id, name=f'Genre {genre_id}')

    def surprise(self, user, genre, exclude):
        self.surprise_calls.append((user.id, genre, exclude))
        return {
            'game': None,
            'reason': 'no_games',
            'genre': {'id': genre.id, 'name': genre.name} if genre else None,
            'genres': [{'id': 5, 'name': 'Genre 5'}],
        }

    def pins(self, user):
        self.pins_calls.append(user.id)
        return {
            'pins': ['recent'],
            'hidden': ['played'],
            'max_pins': 3,
            'available': ['recent', 'played', 'genre:5'],
        }

    def save_pins(self, user, payload):
        self.save_pins_calls.append((user.id, payload))
        return {'pins': payload.get('pins', ['recent']), 'hidden': payload.get('hidden', []), 'max_pins': 3}


def make_client(*, authenticated=True, data=None, blueprint_login_view=None):
    flask_app = Flask(__name__)
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('Flask app context used'))
    flask_app.config.update(SECRET_KEY='native-discover-reads-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule('/member-login', endpoint='member_login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=151, role='user', is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={'apis': blueprint_login_view} if blueprint_login_view else {},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_discover_reads_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 151 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '151' else None,
        login_manager=manager,
        data_access=data or FakeDiscoverData(),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '151:fp'}, 'native-discover-reads-secret')
        )
    return client


def test_sections_returns_bare_json_feed_with_feed_token():
    data = FakeDiscoverData()
    response = make_client(data=data).get('/api/discover/sections')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.sections_payload
    assert 'ok' not in response.json()
    assert data.sections_calls == [151]


def test_row_uses_first_query_values_and_omits_zero_limit():
    data = FakeDiscoverData()
    response = make_client(data=data).get(
        '/api/discover/rows/recent?offset=7&offset=99&limit=0&limit=50&feed_token=feed%2Babc&feed_token=ignored'
    )
    assert response.status_code == 200
    assert response.json() == {
        **data.row_payload,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.row_calls == [(151, 'recent', 7, 'feed+abc', {})]


def test_row_passes_nonzero_limit_to_existing_service():
    data = FakeDiscoverData()
    response = make_client(data=data).get(
        '/api/discover/rows/recent?offset=-2&limit=20&feed_token=token-1'
    )
    assert response.status_code == 200
    assert data.row_calls == [(151, 'recent', -2, 'token-1', {'limit': 20})]


def test_invalid_offset_or_limit_returns_bad_request_envelope():
    for query in ('?offset=nope', '?limit=wide'):
        data = FakeDiscoverData()
        response = make_client(data=data).get('/api/discover/rows/recent' + query)
        assert response.status_code == 400
        assert response.json() == {
            'ok': False,
            'error': 'Row offset and limit must be whole numbers.',
            'error_code': 'bad_request',
            'message': 'Row offset and limit must be whole numbers.',
            'success': False,
        }
        assert data.row_calls == []


def test_missing_row_returns_not_found_with_identifier_detail():
    data = FakeDiscoverData()
    data.row_payload = None
    response = make_client(data=data).get('/api/discover/rows/gone')
    assert response.status_code == 404
    assert response.json() == {
        'ok': False,
        'error': 'That Discover row is not available.',
        'error_code': 'not_found',
        'detail': 'gone',
        'message': 'That Discover row is not available.',
        'success': False,
    }


def test_anonymous_requests_redirect_with_login_flash_and_next():
    data = FakeDiscoverData()
    client = make_client(authenticated=False, data=data, blueprint_login_view='/member-login')
    for path in ('/api/discover/sections?from=home', '/api/discover/rows/recent?offset=10'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'].startswith('/member-login?next=')
        session = load_session_cookie(
            response.cookies['session'], 'native-discover-reads-secret', max_age=31_536_000
        )
        assert session['_flashes'][-1] == ('message', 'Please log in to access this page.')
    assert data.sections_calls == []
    assert data.row_calls == []


def test_head_sections_and_row_keep_headers_length_and_empty_body():
    data = FakeDiscoverData()
    client = make_client(data=data)
    for path in ('/api/discover/sections', '/api/discover/rows/recent?offset=1'):
        get_response = client.get(path)
        head_response = client.head(path)
        assert head_response.status_code == 200
        assert head_response.content == b''
        assert head_response.headers['content-length'] == str(len(get_response.content))
        assert head_response.headers['X-Content-Type-Options'] == 'nosniff'


def test_zone_success_uses_api_ok_and_preserves_slug():
    data = FakeDiscoverData()
    response = make_client(data=data).get('/api/discover/zones/by-era')
    payload = {'slug': 'by-era', 'sections': [{'id': 'row-1'}], 'feed_token': 'zone-feed'}
    assert response.status_code == 200
    assert response.json() == {
        **payload, 'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert data.zone_calls == [(151, 'by-era')]


def test_zone_not_found_includes_slug_detail():
    data = FakeDiscoverData()
    data.zone = lambda _user, _slug: None
    response = make_client(data=data).get('/api/discover/zones/missing-zone')
    assert response.status_code == 404
    assert response.json() == {
        'ok': False,
        'error': 'That Discover zone is not available.',
        'error_code': 'not_found',
        'detail': 'missing-zone',
        'message': 'That Discover zone is not available.',
        'success': False,
    }


def test_genre_hub_preserves_multi_segment_decoded_genre_path():
    data = FakeDiscoverData()
    response = make_client(data=data).get('/api/discover/hubs/genre/Action/Adventure')
    payload = {
        'genre': 'Action/Adventure',
        'sections': [{'id': 'genre-row'}],
        'feed_token': 'genre-feed',
    }
    assert response.status_code == 200
    assert response.json() == {
        **payload, 'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert data.genre_calls == [(151, 'Action/Adventure')]


def test_genre_not_found_has_no_detail_field():
    data = FakeDiscoverData()
    data.genre_hub = lambda _user, _genre: None
    response = make_client(data=data).get('/api/discover/hubs/genre/unknown/category')
    assert response.status_code == 404
    assert response.json() == {
        'ok': False,
        'error': 'That genre is not in this library.',
        'error_code': 'not_found',
        'message': 'That genre is not in this library.',
        'success': False,
    }
    assert 'detail' not in response.json()


def test_anonymous_zone_and_genre_reads_redirect_without_adapter_calls():
    data = FakeDiscoverData()
    client = make_client(authenticated=False, data=data)
    for path in (
        '/api/discover/zones/by-era',
        '/api/discover/hubs/genre/Action/Adventure',
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'].startswith('/login?next=')
    assert data.zone_calls == []
    assert data.genre_calls == []


def test_head_zone_and_genre_keep_content_length_but_return_no_body():
    data = FakeDiscoverData()
    client = make_client(data=data)
    for path in (
        '/api/discover/zones/by-era',
        '/api/discover/hubs/genre/Action/Adventure',
    ):
        get_response = client.get(path)
        head_response = client.head(path)
        assert head_response.status_code == 200
        assert head_response.content == b''
        assert head_response.headers['content-length'] == str(len(get_response.content))
        assert head_response.headers['X-Content-Type-Options'] == 'nosniff'


def test_pins_put_requires_csrf_before_auth_or_data_access():
    data = FakeDiscoverData()
    client = make_client(data=data)
    response = client.put('/api/discover/pins', json={'pins': ['recent']})
    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.save_pins_calls == []


def test_pins_put_preserves_member_csrf_and_response_contract():
    data = FakeDiscoverData()
    client = make_client(data=data)
    session_data = {'_user_id': '151:fp'}
    csrf = generate_csrf_token(session_data, 'native-discover-reads-secret')
    client.cookies.set('session', dump_session_cookie(session_data, 'native-discover-reads-secret'))
    response = client.put(
        '/api/discover/pins',
        json={'pins': ['recent'], 'hidden': ['played']},
        headers={'X-CSRFToken': csrf},
    )
    assert response.status_code == 200
    assert response.json() == {
        'pins': ['recent'], 'hidden': ['played'], 'max_pins': 3,
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert data.save_pins_calls == [(151, {'pins': ['recent'], 'hidden': ['played']})]


def test_pins_put_maps_validation_errors_to_legacy_api_codes():
    class ErrorData(FakeDiscoverData):
        def save_pins(self, _user, payload):
            return {'error': ('That row is not on your Discover feed.', 'not_found', 'missing')}

    client = make_client(data=ErrorData())
    session_data = {'_user_id': '151:fp'}
    csrf = generate_csrf_token(session_data, 'native-discover-reads-secret')
    client.cookies.set('session', dump_session_cookie(session_data, 'native-discover-reads-secret'))
    response = client.put(
        '/api/discover/pins', json={'pins': ['missing']}, headers={'X-CSRFToken': csrf},
    )
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
    assert response.json()['detail'] == 'missing'


def test_surprise_parses_first_trimmed_genre_and_exclude_values():
    data = FakeDiscoverData()
    response = make_client(data=data).get(
        '/api/discover/surprise?genre=%205%20&genre=8&exclude=game-a%2C%2C+game-b&exclude=ignored'
    )
    assert response.status_code == 200
    assert response.json() == {
        'game': None,
        'reason': 'no_games',
        'genre': {'id': 5, 'name': 'Genre 5'},
        'genres': [{'id': 5, 'name': 'Genre 5'}],
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.genre_id_calls == [5]
    assert data.surprise_calls == [(151, SimpleNamespace(id=5, name='Genre 5'), ['game-a', ' game-b'])]


def test_surprise_invalid_genre_returns_bad_request_and_does_not_pick():
    data = FakeDiscoverData()
    response = make_client(data=data).get('/api/discover/surprise?genre=action')
    assert response.status_code == 400
    assert response.json()['error'] == 'Genre must be a genre id.'
    assert response.json()['error_code'] == 'bad_request'
    assert data.genre_id_calls == []
    assert data.surprise_calls == []


def test_surprise_unknown_genre_returns_not_found_without_pick():
    data = FakeDiscoverData()
    data.genre_by_id = lambda genre_id: None
    response = make_client(data=data).get('/api/discover/surprise?genre=44')
    assert response.status_code == 404
    assert response.json()['error'] == 'That genre is not in this library.'
    assert response.json()['error_code'] == 'not_found'
    assert data.surprise_calls == []


def test_pins_get_returns_member_settings_with_api_ok_envelope():
    data = FakeDiscoverData()
    response = make_client(data=data).get('/api/discover/pins')
    assert response.status_code == 200
    assert response.json() == {
        'pins': ['recent'],
        'hidden': ['played'],
        'max_pins': 3,
        'available': ['recent', 'played', 'genre:5'],
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.pins_calls == [151]


def test_anonymous_surprise_and_pins_redirect_without_adapter_calls():
    data = FakeDiscoverData()
    client = make_client(authenticated=False, data=data)
    for path in ('/api/discover/surprise?genre=5', '/api/discover/pins'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'].startswith('/login?next=')
    assert data.genre_id_calls == []
    assert data.surprise_calls == []
    assert data.pins_calls == []


def test_head_surprise_and_pins_keep_content_length_but_return_no_body():
    data = FakeDiscoverData()
    client = make_client(data=data)
    for path in ('/api/discover/surprise', '/api/discover/pins'):
        get_response = client.get(path)
        head_response = client.head(path)
        assert head_response.status_code == 200
        assert head_response.content == b''
        assert head_response.headers['content-length'] == str(len(get_response.content))
        assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
