"""The scan page's manual-identify preview: admin only, never cached."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from tests.fixtures.native_auth import login_identity_for, persistent_login_store  # noqa: F401 (autouse fixture)

from oneirodex.runtime_native.manual_identify_session_preview import (
    create_manual_identify_session_preview_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie


def test_manual_identify_session_preview_is_admin_only_and_never_caches_paths(monkeypatch):
    from oneirodex.runtime_native import manual_identify_session_preview as native_preview

    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', SESSION_PROTECTION='none',
    )
    admin = SimpleNamespace(
        id=7, name='Admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    member = SimpleNamespace(
        id=8, name='Member', role='user', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    app = FastAPI()
    app.include_router(create_manual_identify_session_preview_router(
        flask_app,
        find_user=lambda uid: {7: admin, 8: member}.get(uid),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: {'7': admin, '8': member}.get(value.split(':', 1)[0]),
        login_manager=manager,
        database_scope=lambda _app: nullcontext(),
    ))
    path = '/storage/PrivateCandidate/Example Game'
    admin_session = {
        '_user_id': login_identity_for(7), '_fresh': True,
        'game_paths': {'Example Game': path},
        'selected_library_uuid': 'library-1',
    }
    member_session = {
        '_user_id': login_identity_for(8), '_fresh': True,
        'game_paths': {'Example Game': path},
        'selected_library_uuid': 'library-1',
    }

    admin_client = TestClient(app)
    admin_client.cookies.set(
        'session', dump_session_cookie(admin_session, 'legacy-scan-secret'),
    )
    allowed = admin_client.get('/api/admin/scan/manual-identify/session-preview')
    assert allowed.status_code == 200
    assert allowed.headers['cache-control'] == 'no-store'
    assert allowed.json()['games'] == [{'name': 'Example Game', 'full_path': path}]

    anonymous = TestClient(app).get(
        '/api/admin/scan/manual-identify/session-preview', follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert path not in anonymous.text

    member_client = TestClient(app)
    member_client.cookies.set(
        'session', dump_session_cookie(member_session, 'legacy-scan-secret'),
    )
    denied_member = member_client.get(
        '/api/admin/scan/manual-identify/session-preview', follow_redirects=False,
    )
    assert denied_member.status_code == 302
    assert denied_member.headers['location'] == '/login'
    assert path not in denied_member.text

    token_context = SimpleNamespace(
        user=admin,
        token=object(),
        has_scope=lambda scope: scope == 'library:read',
        session_data={
            'game_paths': {'Example Game': path},
            'selected_library_uuid': 'library-1',
        },
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(
        native_preview, 'request_auth_context',
        lambda *_args, **_kwargs: token_context,
    )
    denied_token = TestClient(app).get(
        '/api/admin/scan/manual-identify/session-preview',
        headers={'Authorization': 'Bearer synthetic-token'},
    )
    assert denied_token.status_code == 403
    assert denied_token.json()['error_code'] == 'forbidden'
    assert path not in denied_token.text
