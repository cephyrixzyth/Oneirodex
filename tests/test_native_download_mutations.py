from __future__ import annotations

import hashlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect

from oneirodex.runtime_native.download_mutations import create_download_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeDownloads:
    def __init__(self):
        self.created = None
        self.cleaned = []
        self.legacy_existing = None
        self.legacy_zip = '/storage/fixture/game.zip'
        self.missing_game = False
        self.access_allowed = True
        self.other_record = SimpleNamespace(file_path='/storage/fixture/update.zip', times_downloaded=0)

    def game(self, game_uuid):
        if self.missing_game:
            return None
        return SimpleNamespace(uuid=game_uuid, name='Fixture', full_disk_path='/storage/fixture',
                               size=1024, times_downloaded=2)

    def can_access(self, _user, _game):
        return self.access_allowed

    def resolve_version(self, _game, *, kind, version_uuid):
        return '/storage/fixture', '/storage/fixture', version_uuid or 'version-1'

    def exists(self, _path):
        return True

    def allowed_bases(self, _app):
        return ['/storage']

    def safe_path(self, _path, _bases):
        return True, None

    def legacy_download_request(self, _user, _game):
        return self.legacy_existing

    def other_file(self, _file_type, _game_uuid, _file_token):
        return self.other_record

    def other_download_request(self, _user, _path):
        return self.legacy_existing

    def legacy_zip_path(self, _game):
        return self.legacy_zip

    def create_legacy_download_request(self, game, user, zip_file_path):
        self.created = (game.uuid, user.id, game.full_disk_path, zip_file_path)
        return SimpleNamespace(id=80, status='available')

    def create_other_download_request(self, game_uuid, user, record, path):
        self.created = (game_uuid, user.id, path, path)
        return SimpleNamespace(id=82, status='available')

    def log_legacy_event(self, *_args, **_kwargs):
        pass

    def zip_path(self, _game, path, **_kwargs):
        return path

    def create_request(self, game, user, *, file_location, zip_file_path, kind='base', version_uuid=None):
        self.created = (game.uuid, user.id, file_location, zip_file_path)
        return SimpleNamespace(id=81, status='available')

    def cleanup_orphans(self, game):
        self.cleaned.append(game.uuid)
        return {'removed': [], 'kept': []}

    def log_cleanup(self, *_args, **_kwargs):
        pass


def make_client(*, data=None, role='admin', csrf_enabled=False, token_scopes=None):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-download-mutations-secret', TESTING=True,
        WTF_CSRF_ENABLED=csrf_enabled,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role=role, is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    token = None
    if token_scopes is not None:
        token = SimpleNamespace(
            user_id=7,
            token_hash=hashlib.sha256(b'secret').hexdigest(),
            revoked_at=None,
            expires_at=None,
            scopes=token_scopes,
            is_expired=lambda _now: False,
        )
    app = FastAPI()
    app.include_router(create_download_mutation_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda prefix: token if prefix == 'test' else None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('7:') else None,
        login_manager=manager, data_access=data or FakeDownloads(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-download-mutations-secret'))
    return client


def test_download_request_creation_checks_scope_path_and_returns_stream_url():
    data = FakeDownloads()
    response = make_client(role='user', data=data).post(
        '/api/downloads/games/12345678-1234-1234-1234-123456789abc',
        json={'kind': 'base'},
    )

    assert response.status_code == 200
    assert response.json()['download_id'] == 81
    assert response.json()['stream_url'] == '/download_zip/81'
    assert data.created == ('12345678-1234-1234-1234-123456789abc', 7, '/storage/fixture', '/storage/fixture')


def test_orphan_version_cleanup_requires_librarian_and_reports_api_envelope():
    data = FakeDownloads()
    response = make_client(data=data).post(
        '/api/games/12345678-1234-1234-1234-123456789abc/versions/cleanup_orphans',
    )

    assert response.status_code == 200
    assert response.json()['removed'] == []
    assert response.json()['ok'] is True
    assert data.cleaned == ['12345678-1234-1234-1234-123456789abc']


@pytest.mark.parametrize('role', [None, 'user', 'child'])
def test_orphan_cleanup_auth_matches_legacy_flask(role):
    from flask_login import LoginManager

    from oneirodex.routes_apis import apis_bp
    import oneirodex.routes_apis.download  # register the legacy cleanup route

    secret = 'orphan-cleanup-parity-secret'
    user = SimpleNamespace(
        id=7, role=role, name='ParityUser', is_active=True, state=True,
        is_authenticated=True,
    )
    legacy_app = Flask('legacy-orphan-cleanup-parity')
    legacy_app.config.update(
        SECRET_KEY=secret, TESTING=True, WTF_CSRF_ENABLED=False,
    )
    manager = LoginManager(legacy_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: user if key == '7:fp' and role is not None else None)
    legacy_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_client = legacy_app.test_client()
    if role is not None:
        with legacy_client.session_transaction() as session:
            session['_user_id'] = '7:fp'
            session['_fresh'] = True

    path = '/api/games/12345678-1234-1234-1234-123456789abc/versions/cleanup_orphans'
    legacy = legacy_client.post(path, follow_redirects=False)
    current = make_client(data=FakeDownloads(), role=role or 'user')
    if role is None:
        current.cookies.clear()
    native = current.post(path, follow_redirects=False)

    assert native.status_code == legacy.status_code
    assert native.headers.get('location') == legacy.headers.get('Location')
    assert native.headers.get('content-type') == legacy.headers.get('Content-Type')
    if role is None:
        assert native.content == legacy.get_data()
    else:
        assert native.json() == legacy.get_json()


@pytest.mark.parametrize('access_allowed', [True, False])
def test_orphan_cleanup_mutation_and_game_acl_match_legacy_flask(access_allowed, monkeypatch):
    from flask_login import LoginManager

    from oneirodex.routes_apis import apis_bp
    from oneirodex.utils.api_response import api_error
    import oneirodex.routes_apis.download as legacy_routes

    secret = 'orphan-cleanup-mutation-parity-secret'
    admin = SimpleNamespace(
        id=7, role='admin', name='ParityAdmin', is_active=True, state=True,
        is_authenticated=True,
    )
    game = SimpleNamespace(uuid='12345678-1234-1234-1234-123456789abc', name='Fixture')
    legacy_cleanup_calls = []
    expected_result = {'removed': [{'id': 4}], 'kept': [{'id': 5}]}

    def legacy_downloadable(_game_uuid):
        if not access_allowed:
            return None, api_error('Access denied', code='forbidden')
        return game, None

    monkeypatch.setattr(legacy_routes, '_downloadable_game', legacy_downloadable)
    monkeypatch.setattr(
        legacy_routes, 'cleanup_orphan_versions',
        lambda target: legacy_cleanup_calls.append(target) or expected_result,
    )
    monkeypatch.setattr(legacy_routes, 'log_system_event', lambda *_args, **_kwargs: None)

    legacy_app = Flask('legacy-orphan-cleanup-mutation-parity')
    legacy_app.config.update(
        SECRET_KEY=secret, TESTING=True, WTF_CSRF_ENABLED=False,
    )
    manager = LoginManager(legacy_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: admin if key == '7:fp' else None)
    legacy_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_client = legacy_app.test_client()
    with legacy_client.session_transaction() as session:
        session['_user_id'] = '7:fp'
        session['_fresh'] = True

    path = f'/api/games/{game.uuid}/versions/cleanup_orphans'
    legacy = legacy_client.post(path, follow_redirects=False)
    current_data = FakeDownloads()
    current_data.can_access = lambda _user, _game: access_allowed
    current_data.cleanup_orphans = lambda target: current_data.cleaned.append(target.uuid) or expected_result
    current = make_client(data=current_data, role='admin').post(path, follow_redirects=False)

    assert current.status_code == legacy.status_code
    assert current.headers.get('content-type') == legacy.headers.get('Content-Type')
    assert current.json() == legacy.get_json()
    assert legacy_cleanup_calls == ([game] if access_allowed else [])
    assert current_data.cleaned == ([game.uuid] if access_allowed else [])


def test_orphan_cleanup_failure_and_rollback_match_legacy_flask(monkeypatch):
    from flask_login import LoginManager

    from oneirodex.routes_apis import apis_bp
    import oneirodex.routes_apis.download as legacy_routes

    secret = 'orphan-cleanup-failure-parity-secret'
    admin = SimpleNamespace(
        id=7, role='admin', name='ParityAdmin', is_active=True, state=True,
        is_authenticated=True,
    )
    game = SimpleNamespace(uuid='12345678-1234-1234-1234-123456789abc', name='Fixture')
    rollback_calls = []
    error_logs = []
    monkeypatch.setattr(legacy_routes, '_downloadable_game', lambda _uuid: (game, None))
    monkeypatch.setattr(
        legacy_routes, 'cleanup_orphan_versions',
        lambda _game: (_ for _ in ()).throw(RuntimeError('synthetic cleanup failure')),
    )
    monkeypatch.setattr(legacy_routes.db.session, 'rollback', lambda: rollback_calls.append('flask'))
    monkeypatch.setattr(legacy_routes, 'log_system_event', lambda message, **_kwargs: error_logs.append(message))

    legacy_app = Flask('legacy-orphan-cleanup-failure-parity')
    legacy_app.config.update(
        SECRET_KEY=secret, TESTING=True, WTF_CSRF_ENABLED=False,
    )
    manager = LoginManager(legacy_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: admin if key == '7:fp' else None)
    legacy_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_client = legacy_app.test_client()
    with legacy_client.session_transaction() as session:
        session['_user_id'] = '7:fp'
        session['_fresh'] = True

    path = f'/api/games/{game.uuid}/versions/cleanup_orphans'
    legacy = legacy_client.post(path, follow_redirects=False)

    current_data = FakeDownloads()
    current_data.cleanup_orphans = lambda _game: (_ for _ in ()).throw(
        RuntimeError('synthetic cleanup failure'),
    )
    current_data.log_cleanup = lambda _game, _result, error=False: error_logs.append(
        'native-error' if error else 'native-success',
    )
    current = make_client(data=current_data, role='admin').post(path, follow_redirects=False)

    assert current.status_code == legacy.status_code
    assert current.headers.get('content-type') == legacy.headers.get('Content-Type')
    assert current.json() == legacy.get_json()
    assert rollback_calls == ['flask', 'flask']
    assert error_logs[-1] == 'native-error'


@pytest.mark.parametrize('scenario', ['acl_denied', 'invalid_kind', 'missing_version'])
def test_download_api_acl_and_version_errors_match_legacy_flask(scenario, monkeypatch):
    from flask_login import LoginManager

    from oneirodex.routes_apis import apis_bp
    from oneirodex.utils.api_response import api_error
    import oneirodex.routes_apis.download as legacy_routes

    secret = 'download-api-error-parity-secret'
    user = SimpleNamespace(
        id=7, role='user', name='ParityUser', is_active=True, state=True,
        is_authenticated=True,
    )
    game = SimpleNamespace(
        uuid='12345678-1234-1234-1234-123456789abc', name='Fixture',
    )
    if scenario == 'acl_denied':
        monkeypatch.setattr(
            legacy_routes, '_downloadable_game',
            lambda _uuid: (None, api_error('Access denied', code='forbidden')),
        )
        body = {'kind': 'base'}
        legacy_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('ACL refusal must precede version resolution'),
        )
        current_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('ACL refusal must precede version resolution'),
        )
    elif scenario == 'invalid_kind':
        monkeypatch.setattr(legacy_routes, '_downloadable_game', lambda _uuid: (game, None))
        body = {'kind': 'invalid'}
        legacy_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError('Invalid download kind'),
        )
        current_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError('Invalid download kind'),
        )
    else:
        monkeypatch.setattr(legacy_routes, '_downloadable_game', lambda _uuid: (game, None))
        body = {'kind': 'update', 'version_uuid': 'missing-version'}
        legacy_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LookupError('Version not found'),
        )
        current_resolver = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LookupError('Version not found'),
        )

    monkeypatch.setattr(legacy_routes, 'resolve_version_file', legacy_resolver)
    legacy_app = Flask(f'legacy-download-api-{scenario}')
    legacy_app.config.update(
        SECRET_KEY=secret, TESTING=True, WTF_CSRF_ENABLED=False,
    )
    manager = LoginManager(legacy_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: user if key == '7:fp' else None)
    legacy_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_client = legacy_app.test_client()
    with legacy_client.session_transaction() as session:
        session['_user_id'] = '7:fp'
        session['_fresh'] = True

    path = f'/api/downloads/games/{game.uuid}'
    legacy = legacy_client.post(path, json=body, follow_redirects=False)
    current_data = FakeDownloads()
    current_data.can_access = lambda _user, _game: scenario != 'acl_denied'
    current_data.resolve_version = current_resolver
    current = make_client(data=current_data, role='user').post(
        path, json=body, follow_redirects=False,
    )

    assert current.status_code == legacy.status_code
    assert current.headers.get('content-type') == legacy.headers.get('Content-Type')
    assert current.json() == legacy.get_json()
    assert current_data.created is None


def test_legacy_game_download_creates_request_and_redirects_to_downloads():
    data = FakeDownloads()
    response = make_client(data=data, role='user').post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/downloads'
    expected = flask_redirect('/downloads', code=302)
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()
    assert data.created == (
        '12345678-1234-1234-1234-123456789abc', 7,
        '/storage/fixture', '/storage/fixture/game.zip',
    )


def test_legacy_download_get_and_head_never_create_requests():
    data = FakeDownloads()
    client = make_client(data=data, role='user')
    game_path = '/download_game/12345678-1234-1234-1234-123456789abc'

    get_response = client.get(game_path, follow_redirects=False)
    head_response = client.head(game_path, follow_redirects=False)

    assert get_response.status_code == 405
    assert head_response.status_code == 405
    assert data.created is None


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
@pytest.mark.parametrize(('rule', 'path'), [
    ('/download_game/<game_uuid>', '/download_game/12345678-1234-1234-1234-123456789abc'),
    ('/download_other/<file_type>/<game_uuid>/<file_id>',
     '/download_other/update/12345678-1234-1234-1234-123456789abc/42'),
])
def test_native_post_only_download_methods_match_current_flask_bridge(method, rule, path):
    legacy = Flask(__name__)
    legacy.add_url_rule(
        rule, endpoint='download', view_func=lambda **_kwargs: 'ok', methods=['POST'],
    )
    expected = legacy.test_client().open(path, method=method)

    data = FakeDownloads()
    response = make_client(data=data, role='user').request(method, path, follow_redirects=False)

    assert response.status_code == expected.status_code
    assert set(response.headers.get('allow', '').split(', ')) == set(expected.headers.get('Allow', '').split(', '))
    assert response.headers.get('content-type') == expected.headers.get('Content-Type')
    assert response.headers.get('content-length') == expected.headers.get('Content-Length')
    assert response.content == expected.get_data()
    assert data.created is None


def test_legacy_download_post_requires_csrf_for_session_auth():
    data = FakeDownloads()
    response = make_client(data=data, role='user', csrf_enabled=True).post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert data.created is None


def test_legacy_download_denies_child_session_scope():
    data = FakeDownloads()
    client = make_client(data=data, role='child')

    response = client.post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert data.created is None


@pytest.mark.parametrize('path', [
    '/download_game/12345678-1234-1234-1234-123456789abc',
    '/download_other/update/12345678-1234-1234-1234-123456789abc/42',
])
def test_download_child_scope_denial_matches_legacy_flask(path):
    from flask_login import LoginManager

    from oneirodex.routes_downloads_ext import download_bp

    secret = 'download-child-parity-secret'
    child = SimpleNamespace(
        id=7, role='child', name='ParityChild', is_active=True, state=True,
        is_authenticated=True,
    )
    legacy_app = Flask('legacy-download-child-parity')
    legacy_app.config.update(
        SECRET_KEY=secret, TESTING=True, WTF_CSRF_ENABLED=False,
    )
    manager = LoginManager(legacy_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: child if key == '7:fp' else None)
    legacy_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    legacy_app.register_blueprint(download_bp)
    legacy_client = legacy_app.test_client()
    with legacy_client.session_transaction() as session:
        session['_user_id'] = '7:fp'
        session['_fresh'] = True

    legacy = legacy_client.post(path, follow_redirects=False)
    current_data = FakeDownloads()
    current = make_client(data=current_data, role='child').post(path, follow_redirects=False)

    assert current.status_code == legacy.status_code
    assert current.headers.get('content-type') == legacy.headers.get('Content-Type')
    assert current.json() == legacy.get_json()
    assert current_data.created is None


def test_legacy_download_bearer_requires_write_download_scope():
    data = FakeDownloads()
    client = make_client(data=data, role='user', csrf_enabled=True, token_scopes=['read:library'])
    client.cookies.delete('session')

    for path in (
        '/download_game/12345678-1234-1234-1234-123456789abc',
        '/download_other/update/12345678-1234-1234-1234-123456789abc/42',
    ):
        response = client.post(
            path,
            headers={'Authorization': 'Bearer gt_test_secret'},
            follow_redirects=False,
        )
        assert response.status_code == 403
    assert data.created is None


def test_legacy_download_accepts_csrf_free_bearer_with_write_download_scope():
    data = FakeDownloads()
    client = make_client(data=data, role='user', csrf_enabled=True, token_scopes=['write:download'])
    client.cookies.delete('session')

    response = client.post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        headers={'Authorization': 'Bearer gt_test_secret'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert data.created == (
        '12345678-1234-1234-1234-123456789abc', 7,
        '/storage/fixture', '/storage/fixture/game.zip',
    )


def test_legacy_game_download_preserves_duplicate_request_flash():
    data = FakeDownloads()
    data.legacy_existing = object()
    response = make_client(data=data, role='user').post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/downloads'
    expected = flask_redirect('/downloads', code=302)
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()
    assert data.created is None
    assert response.headers.get('set-cookie', '').startswith('session=')


def test_legacy_game_download_rejects_unsafe_path_without_creating_request():
    data = FakeDownloads()
    data.safe_path = lambda _path, _bases: (False, 'outside allowed root')
    response = make_client(data=data, role='user').post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/downloads'
    assert data.created is None


def test_legacy_update_download_creates_request_and_redirects_to_downloads():
    data = FakeDownloads()
    response = make_client(data=data, role='user').post(
        '/download_other/update/12345678-1234-1234-1234-123456789abc/42',
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/downloads'
    assert data.created == (
        '12345678-1234-1234-1234-123456789abc', 7,
        '/storage/fixture/update.zip', '/storage/fixture/update.zip',
    )


def test_legacy_other_missing_disk_get_keeps_warning_without_queueing():
    from oneirodex.runtime_native.session_compat import load_session_cookie

    data = FakeDownloads()
    data.exists = lambda _path: False
    response = make_client(data=data, role='user').get(
        '/download_other/update/12345678-1234-1234-1234-123456789abc/42',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/game_details/12345678-1234-1234-1234-123456789abc'
    cookie = response.headers['set-cookie'].split(';', 1)[0].split('=', 1)[1]
    session = load_session_cookie(cookie, 'native-download-mutations-secret', max_age=3600)
    assert session['_flashes'][-1] == ('error', 'File not found on disk')
    assert data.created is None


def test_legacy_other_download_rejects_invalid_type_and_file_id():
    data = FakeDownloads()
    client = make_client(data=data, role='user')
    invalid_type = client.post(
        '/download_other/mod/12345678-1234-1234-1234-123456789abc/42',
        follow_redirects=False,
    )
    invalid_id = client.post(
        '/download_other/update/12345678-1234-1234-1234-123456789abc/not-an-id',
        follow_redirects=False,
    )

    assert invalid_type.status_code == 302
    assert invalid_type.headers['location'] == '/game_details/12345678-1234-1234-1234-123456789abc'
    assert invalid_id.status_code == 400
    assert data.created is None


@pytest.mark.parametrize(
    ('error', 'message', 'event_prefix'),
    [
        (None, 'Database error occurred', 'Database error creating update download request:'),
        (RuntimeError('fixture failure'), 'An error occurred processing your request.',
         'Error creating update download request:'),
    ],
)
def test_legacy_other_download_failure_matches_v118_flash_and_event(
    error, message, event_prefix, monkeypatch,
):
    from sqlalchemy.exc import OperationalError
    from oneirodex.runtime_native.session_compat import load_session_cookie

    rollback_calls = []
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.runtime_native.db_session',
        SimpleNamespace(native_db=SimpleNamespace(
            session=SimpleNamespace(rollback=lambda: rollback_calls.append(True)),
        )),
    )

    class FailingDownloads(FakeDownloads):
        def __init__(self):
            super().__init__()
            self.events = []

        def create_other_download_request(self, *_args):
            if error is None:
                raise OperationalError('INSERT', {}, RuntimeError('db fixture failure'))
            raise error

        def log_legacy_event(self, message, **kwargs):
            self.events.append((message, kwargs))

    data = FailingDownloads()
    response = make_client(data=data, role='user').post(
        '/download_other/update/12345678-1234-1234-1234-123456789abc/42',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/game_details/12345678-1234-1234-1234-123456789abc'
    cookie = response.headers['set-cookie'].split(';', 1)[0].split('=', 1)[1]
    session = load_session_cookie(cookie, 'native-download-mutations-secret', max_age=3600)
    assert session['_flashes'][-1] == ('error', message)
    assert data.events[-1][0].startswith(event_prefix)
    assert data.events[-1][1] == {'event_type': 'system', 'event_level': 'error'}
    assert rollback_calls == [True]


@pytest.mark.parametrize(
    ('path', 'error_type', 'missing_game', 'access_allowed'),
    [
        ('/download_game/not-a-uuid', 'bad_request', False, True),
        ('/download_game/12345678-1234-1234-1234-123456789abc', 'not_found', True, True),
        ('/download_game/12345678-1234-1234-1234-123456789abc', 'forbidden', False, False),
        ('/download_other/update/not-a-uuid/42', 'bad_request', False, True),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/42', 'not_found', True, True),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/42', 'forbidden', False, False),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/not-an-id', 'bad_request', False, True),
    ],
)
def test_legacy_download_validation_errors_match_werkzeug_abort(
    path, error_type, missing_game, access_allowed,
):
    from werkzeug.exceptions import BadRequest, Forbidden, NotFound

    error_classes = {
        'bad_request': BadRequest,
        'forbidden': Forbidden,
        'not_found': NotFound,
    }
    data = FakeDownloads()
    data.missing_game = missing_game
    data.access_allowed = access_allowed
    response = make_client(data=data, role='user').post(path, follow_redirects=False)
    expected = error_classes[error_type]().get_response()

    assert response.status_code == expected.status_code
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.headers['content-length'] == expected.headers['Content-Length']
    assert response.content == expected.get_data()


@pytest.mark.parametrize(
    ('path', 'error_type', 'missing_game', 'access_allowed'),
    [
        ('/download_other/update/not-a-uuid/42', 'bad_request', False, True),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/42', 'not_found', True, True),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/42', 'forbidden', False, False),
        ('/download_other/update/12345678-1234-1234-1234-123456789abc/not-an-id', 'bad_request', False, True),
    ],
)
def test_legacy_other_get_preflight_errors_match_werkzeug_abort(
    path, error_type, missing_game, access_allowed,
):
    from werkzeug.exceptions import BadRequest, Forbidden, NotFound

    error_classes = {
        'bad_request': BadRequest,
        'forbidden': Forbidden,
        'not_found': NotFound,
    }
    data = FakeDownloads()
    data.missing_game = missing_game
    data.access_allowed = access_allowed
    response = make_client(data=data, role='user').get(path, follow_redirects=False)
    expected = error_classes[error_type]().get_response()

    assert response.status_code == expected.status_code
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.headers['content-length'] == expected.headers['Content-Length']
    assert response.content == expected.get_data()


def test_legacy_other_safe_get_preflight_does_not_require_write_csrf():
    from werkzeug.exceptions import BadRequest

    response = make_client(role='user', csrf_enabled=True).get(
        '/download_other/update/not-a-uuid/42', follow_redirects=False,
    )
    expected = BadRequest().get_response()

    assert response.status_code == expected.status_code
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()


def test_version_download_request_records_actual_file_size(tmp_path, monkeypatch):
    from oneirodex.runtime_native.download_mutations import DownloadMutationData

    class ScalarResult:
        def scalars(self):
            return self

        def first(self):
            return None

    class Session:
        def __init__(self):
            self.added = []
            self.commits = 0

        def execute(self, _statement):
            return ScalarResult()

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.commits += 1

    session = Session()
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.runtime_native.db_session',
        SimpleNamespace(native_db=SimpleNamespace(session=session)),
    )
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.utils.event_bus',
        SimpleNamespace(publish_download_event=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        'oneirodex.utils.event_logging',
        SimpleNamespace(log_system_event=lambda *_args, **_kwargs: None),
    )

    update_file = tmp_path / 'update.bin'
    update_file.write_bytes(b'legacy-sized-update')
    game = SimpleNamespace(
        uuid='12345678-1234-1234-1234-123456789abc',
        name='Fixture', full_disk_path='/storage/base', size=999,
        times_downloaded=0,
    )
    user = SimpleNamespace(id=7)

    DownloadMutationData().create_request(
        game,
        user,
        file_location=str(update_file),
        zip_file_path=str(update_file),
        kind='update',
        version_uuid='22345678-1234-1234-1234-123456789abc',
    )

    assert len(session.added) == 1
    assert session.added[0].download_size == len(b'legacy-sized-update')
    assert session.commits == 1
    assert game.times_downloaded == 0


@pytest.mark.parametrize('kind', ['update', 'extra'])
def test_selected_version_directory_is_zip_path_when_base_is_not_installed(tmp_path, kind):
    from oneirodex.runtime_native.download_mutations import DownloadMutationData

    version_dir = tmp_path / 'update-version'
    version_dir.mkdir()
    (version_dir / 'patch.dat').write_bytes(b'patch')
    game = SimpleNamespace(full_disk_path=None)

    assert DownloadMutationData().zip_path(
        game, str(version_dir), kind=kind, zip_hint=None,
    ) == str(version_dir)
