from __future__ import annotations

import asyncio
import json
import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask import request as flask_request
from flask_login import LoginManager
from types import SimpleNamespace

from oneirodex.runtime_native.scan_unmatched_feedback import (
    BAD_MATCH_REASONS,
    create_scan_unmatched_feedback_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeFeedbackData:
    def __init__(self):
        self.calls = []
        self.row = SimpleNamespace(
            folder_path='/fake/games/Example', bad_match_reason=None,
            bad_match_note=None, bad_match_at=None, bad_match_by_user_id=None,
        )

    def reclassify_duplicates(self):
        self.calls.append(('reclassify',))
        return {
            'reclassified_to_unmatched': ['/fake/a'], 'kept_as_duplicate': ['/fake/b'],
            'changed_count': 1, 'kept_count': 1,
        }

    def backfill_suggested_kind(self, *, limit, dry_run):
        self.calls.append(('backfill', limit, dry_run))
        return {'ok': True, 'scanned': 4, 'updated': 2, 'dry_run': dry_run,
                'committed': not dry_run}

    def unmatched_folder(self, folder_id):
        self.calls.append(('get', folder_id))
        return self.row if folder_id == 'existing' else None

    def commit(self):
        self.calls.append(('commit',))

    def rollback(self):
        self.calls.append(('rollback',))

    def log_bad_match(self, path, reason, actor_id):
        self.calls.append(('log', path, reason, actor_id))


@pytest.fixture
def runtime():
    flask_app = Flask('unmatched-feedback-test')
    flask_app.config.update(
        SECRET_KEY='unmatched-feedback-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
    )
    users = {
        'admin': SimpleNamespace(id=1, name='Admin', role='admin', state=True,
                                 is_active=True, is_authenticated=True,
                                 session_fingerprint=lambda: 'fp'),
        'librarian': SimpleNamespace(id=2, name='Librarian', role='librarian', state=True,
                                     is_active=True, is_authenticated=True,
                                     session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=3, name='Member', role='user', state=True,
                                  is_active=True, is_authenticated=True,
                                  session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeFeedbackData()
    app = FastAPI()
    app.include_router(create_scan_unmatched_feedback_router(
        flask_app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=data,
    ))
    cookies = {
        name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                  'unmatched-feedback-secret')
        for name, user in users.items()
    }
    return app, flask_app, data, users, cookies


def request(app, path, *, cookie=None, method='GET', json=None, headers=None):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, json=json, headers=headers, follow_redirects=False)

    return asyncio.run(perform())


def test_admin_maintenance_routes_keep_legacy_shapes_and_forward_inputs(runtime):
    app, _flask, data, _users, cookies = runtime
    classified = request(app, '/api/unmatched_folders/reclassify_duplicates',
                         cookie=cookies['admin'], method='POST', json={})
    assert classified.status_code == 200
    assert classified.json() == {
        'reclassified_to_unmatched': ['/fake/a'], 'kept_as_duplicate': ['/fake/b'],
        'changed_count': 1, 'kept_count': 1,
    }
    backfilled = request(app, '/api/unmatched_folders/backfill_suggested_kind',
                         cookie=cookies['admin'], method='POST',
                         json={'limit': 7, 'dry_run': True})
    assert backfilled.status_code == 200
    assert backfilled.json()['ok'] is True
    assert backfilled.json()['status'] == 'ok'
    assert data.calls == [('reclassify',), ('backfill', 7, True)]


def test_bad_match_reasons_are_librarian_readable(runtime):
    app, _flask, _data, _users, cookies = runtime
    response = request(app, '/api/unmatched/bad_match_reasons', cookie=cookies['librarian'])
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['reasons'] == [
        {'id': key, 'label': label} for key, label in BAD_MATCH_REASONS.items()
    ]


def test_feedback_route_does_not_require_a_flask_app_context(runtime):
    app, flask_app, _data, _users, cookies = runtime
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))

    response = request(app, '/api/unmatched/bad_match_reasons', cookie=cookies['librarian'])

    assert response.status_code == 200
    assert response.json()['reasons'][0]['id'] == 'wrong_game'


def test_bad_match_sets_clears_and_rejects_invalid_feedback(runtime):
    app, _flask, data, _users, cookies = runtime
    flagged = request(app, '/api/unmatched/existing/bad_match', cookie=cookies['librarian'],
                      method='POST', json={'reason': 'wrong_edition'})
    assert flagged.status_code == 200
    assert flagged.json()['reason'] == 'wrong_edition'
    assert data.row.bad_match_reason == 'wrong_edition'
    assert data.row.bad_match_by_user_id == 2
    assert data.row.bad_match_at is not None
    assert data.calls[-2:] == [('commit',), ('log', '/fake/games/Example', 'wrong_edition', 2)]

    invalid = request(app, '/api/unmatched/existing/bad_match', cookie=cookies['librarian'],
                      method='POST', json={'reason': 'unknown'})
    other_without_note = request(
        app, '/api/unmatched/existing/bad_match', cookie=cookies['librarian'],
        method='POST', json={'reason': 'other'},
    )
    assert invalid.status_code == 400 and invalid.json()['error_code'] == 'bad_request'
    assert other_without_note.status_code == 400
    cleared = request(app, '/api/unmatched/existing/bad_match', cookie=cookies['librarian'],
                      method='POST', json={'reason': None})
    assert cleared.status_code == 200 and cleared.json()['cleared'] is True
    assert data.row.bad_match_reason is None and data.row.bad_match_at is None


def test_bad_match_accepts_vendor_json_like_legacy_request_parser(runtime):
    app, flask_app, data, _users, cookies = runtime
    vendor_type = 'application/vnd.oneirodex+json'
    body = {'reason': 'other', 'note': 'Wrong release'}

    with flask_app.test_request_context(
        '/api/unmatched/existing/bad_match',
        method='POST', data=json.dumps(body), content_type=vendor_type,
    ):
        legacy_body = flask_request.get_json(silent=True)

    current = request(
        app, '/api/unmatched/existing/bad_match', cookie=cookies['librarian'],
        method='POST', json=body, headers={'Content-Type': vendor_type},
    )

    assert legacy_body == body
    assert current.status_code == 200
    assert current.json()['reason'] == 'other'
    assert current.json()['note'] == 'Wrong release'
    assert data.row.bad_match_reason == 'other'
    assert data.row.bad_match_note == 'Wrong release'


def test_role_and_csrf_gates_precede_data_access(runtime):
    app, flask_app, data, _users, cookies = runtime
    admin_only = request(app, '/api/unmatched_folders/reclassify_duplicates',
                         cookie=cookies['librarian'], method='POST', json={})
    denied_librarian = request(app, '/api/unmatched/existing/bad_match',
                               cookie=cookies['member'], method='POST', json={'reason': 'wrong_game'})
    denied_anonymous = request(app, '/api/unmatched/bad_match_reasons')
    assert admin_only.status_code == 302 and admin_only.headers['location'] == '/login'
    assert denied_librarian.status_code == 403
    assert denied_anonymous.status_code == 302
    assert not data.calls

    flask_app.config['WTF_CSRF_ENABLED'] = True
    csrf_denied = request(app, '/api/unmatched/existing/bad_match', method='POST',
                          json={'reason': 'wrong_game'})
    assert csrf_denied.status_code == 400
    assert not data.calls


def test_bad_match_missing_folder_returns_404_without_writes(runtime):
    app, _flask, data, _users, cookies = runtime
    response = request(app, '/api/unmatched/missing/bad_match', cookie=cookies['admin'],
                       method='POST', json={'reason': 'wrong_game'})
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
    assert data.calls == [('get', 'missing')]
