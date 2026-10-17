from __future__ import annotations

import hashlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.download_mutations import create_download_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeDownloads:
    def __init__(self):
        self.created = None
        self.cleaned = []
        self.legacy_existing = None
        self.legacy_zip = '/storage/fixture/game.zip'
        self.other_record = SimpleNamespace(file_path='/storage/fixture/update.zip', times_downloaded=0)

    def game(self, game_uuid):
        return SimpleNamespace(uuid=game_uuid, name='Fixture', full_disk_path='/storage/fixture',
                               size=1024, times_downloaded=2)

    def can_access(self, _user, _game):
        return True

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


def test_legacy_game_download_creates_request_and_redirects_to_downloads():
    data = FakeDownloads()
    response = make_client(data=data, role='user').post(
        '/download_game/12345678-1234-1234-1234-123456789abc',
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/downloads'
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
