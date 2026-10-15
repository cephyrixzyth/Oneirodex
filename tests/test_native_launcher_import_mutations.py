from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.launcher_import_mutations import create_launcher_import_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class Result:
    def __init__(self, **values):
        self.__dict__.update({'errors': [], 'imported': 2, 'matched': 1, 'updated': 0, 'skipped': 0, **values})

    def to_dict(self):
        return {'imported': self.imported, 'matched': self.matched, 'updated': self.updated, 'skipped': self.skipped}


class FakeImports:
    def __init__(self):
        self.calls = []

    def enabled(self):
        return True

    def playnite_json(self, user_id, value):
        self.calls.append(('playnite-json', user_id, value))
        return Result()

    def playnite_csv(self, user_id, value):
        self.calls.append(('playnite-csv', user_id, value))
        return Result()

    def launcher(self, user_id, value, *, filename, launcher):
        self.calls.append(('launcher', user_id, value, filename, launcher))
        return Result()


def make_client(*, data=None, token_scopes=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-import-mutations-secret', TESTING=True, WTF_CSRF_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role='user', is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Please log in.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    token = None
    if token_scopes is not None:
        token = SimpleNamespace(
            user_id=7, scopes=list(token_scopes),
            token_hash=hashlib.sha256(b'secret').hexdigest(),
            has_scope=lambda scope: scope in token_scopes,
            is_expired=lambda _now=None: False, revoked_at=None,
        )
    app = FastAPI()
    app.include_router(create_launcher_import_mutation_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: token, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('7:') else None,
        login_manager=manager, data_access=data or FakeImports(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-import-mutations-secret'))
    return client


def test_playnite_json_import_delegates_authenticated_user_and_payload():
    data = FakeImports()
    response = make_client(data=data).post('/api/imports/playnite', json={'games': [{'Name': 'Fixture'}]})

    assert response.status_code == 200
    assert response.json()['imported'] == 2
    assert data.calls[0][0:2] == ('playnite-json', 7)


def test_read_only_bearer_cannot_import_launcher_library_data():
    data = FakeImports()
    client = make_client(data=data, token_scopes=['read:library'])
    client.cookies.clear()
    response = client.post(
        '/api/imports/playnite', json={'games': [{'Name': 'Fixture'}]},
        headers={'Authorization': 'Bearer gt_deadbeef_secret'},
    )

    assert response.status_code == 403
    assert response.json()['error'] == 'Bearer token requires write:library scope'
    assert data.calls == []


def test_write_scoped_bearer_can_import_launcher_library_data():
    data = FakeImports()
    client = make_client(data=data, token_scopes=['read:library', 'write:library'])
    client.cookies.clear()
    response = client.post(
        '/api/imports/playnite', json={'games': [{'Name': 'Fixture'}]},
        headers={'Authorization': 'Bearer gt_deadbeef_secret'},
    )

    assert response.status_code == 200
    assert data.calls[0][0:2] == ('playnite-json', 7)


def test_launcher_csv_upload_is_bounded_and_keeps_selected_format():
    data = FakeImports()
    response = make_client(data=data).post(
        '/api/imports/launcher?launcher=heroic',
        files={'file': ('library.csv', b'Name,Id\nFixture,123\n', 'text/csv')},
    )

    assert response.status_code == 200
    assert data.calls == [('launcher', 7, b'Name,Id\nFixture,123\n', 'library.csv', 'heroic')]
