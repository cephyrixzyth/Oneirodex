"""DB-free transport checks for the opt-in native shell adapter."""
import asyncio
import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import validate_csrf

from oneirodex.runtime_native.admin_pilot import create_admin_pilot
from oneirodex.runtime_native import ADMIN_STATIC_ROUTES
from oneirodex.utils.security_headers import apply_security_headers


class PilotUser(UserMixin):
    state = True

    def __init__(self, role):
        self.id = {'admin': 7, 'member': 8}[role]
        self.name = 'Pilot account'
        self.role = role

    def session_fingerprint(self):
        return f'{self.role}-fingerprint'

    def get_id(self):
        return f'{self.id}:{self.session_fingerprint()}'


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='test-only-native-pilot', TESTING=True)
    manager = LoginManager(flask_app)
    manager.login_view = 'login'
    flask_app.add_url_rule('/login', 'login', lambda: 'Sign in')
    flask_app.add_url_rule('/login', 'login.login', lambda: 'Sign in')
    users = {7: PilotUser('admin'), 8: PilotUser('member')}
    flask_app._native_users = users
    entity_exists = {'value': True}
    flask_app._pilot_shell_entity_exists = entity_exists
    manager.user_loader(
        lambda identity: next((user for user in users.values() if user.get_id() == identity), None)
    )
    from oneirodex.runtime_native import admin_pilot

    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda user_id: users.get(user_id), lambda _prefix: None, lambda _token: None,
    ))
    apply_security_headers(flask_app)
    shell_path = tmp_path / 'shell.html'
    shell_path.write_text('<html><head></head><body><div id="admin-app-root"></div></body></html>', encoding='utf-8')
    return flask_app, create_admin_pilot(flask_app, shell_path=shell_path, chrome_fields=lambda: {
        'avatar_url': '/static/avatar.svg', 'preferences_url': '/settings_panel',
        'theme': {'name': 'default', 'era': 'wood_den_80s', 'icon_pack': 'outline', 'stylesheets': []},
    }, database_scope=lambda _app: nullcontext(),
        shell_entity_exists=lambda _request: entity_exists['value'])


def fetch(app, path, cookie=None, headers=None, method='GET', data=None):
    async def perform():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, headers=headers, data=data)
    return asyncio.run(perform())


def signed_cookie(flask_app, role):
    user = flask_app._native_users.get({'admin': 7, 'member': 8}.get(role))
    identity = (
        f'{user.id}:{user.session_fingerprint()}'
        if user is not None else '999:invalid-fingerprint'
    )
    return flask_app.session_interface.get_signing_serializer(flask_app).dumps(
        {'_user_id': identity, '_fresh': True}
    )


def test_existing_signed_session_and_csrf_roundtrip(pilot):
    flask_app, app = pilot
    response = fetch(app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['user']['role'] == 'admin'
    assert response.headers['cache-control'] == 'no-store'
    assert "script-src 'self'" in response.headers['content-security-policy']
    token = response.json()['csrf_token']
    cookie = response.cookies.get('session')
    assert cookie
    with flask_app.test_request_context(headers={'Cookie': f'session={cookie}'}):
        validate_csrf(token)
    page = fetch(app, '/admin/users', cookie)
    assert page.status_code == 200
    assert 'meta name="csrf-token"' not in page.text
    assert 'id="admin-app-root"' in page.text
    assert response.json()['theme']['name'] == 'default'


def test_admin_shell_head_matches_get_without_body(pilot):
    flask_app, app = pilot
    cookie = signed_cookie(flask_app, 'admin')
    get_response = fetch(app, '/admin/users', cookie)
    head_response = fetch(app, '/admin/users', cookie, method='HEAD')

    assert get_response.status_code == head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['cache-control'] == 'no-store'


def test_admin_shell_consumes_and_escapes_queued_flash_messages(pilot):
    flask_app, app = pilot
    user = flask_app._native_users[7]
    serializer = flask_app.session_interface.get_signing_serializer(flask_app)
    cookie = serializer.dumps({
        '_user_id': user.get_id(), '_fresh': True,
        '_flashes': [
            ('success', 'Invite quota updated.'),
            ('danger', '<script>alert(1)</script>'),
        ],
    })

    response = fetch(app, '/admin/manage_invites', cookie)
    assert response.status_code == 200
    assert 'Invite quota updated.' in response.text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text
    assert '<script>alert(1)</script>' not in response.text
    updated_cookie = response.cookies.get('session')
    assert updated_cookie
    assert '_flashes' not in serializer.loads(updated_cookie)

    next_page = fetch(app, '/admin/manage_invites', updated_cookie)
    assert 'Invite quota updated.' not in next_page.text


@pytest.mark.parametrize('path', ['/admin/help', '/admin/smtp_settings', '/admin/igdb_settings'])
def test_admin_page_paths_render_the_shell_when_compatibility_posts_share_the_path(pilot, path):
    flask_app, app = pilot
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200
    assert 'id="admin-app-root"' in response.text


def test_native_admin_bootstrap_does_not_call_flask_login_user_loader(pilot):
    flask_app, app = pilot
    flask_app.login_manager._user_callback = lambda _identity: (_ for _ in ()).throw(
        AssertionError('native admin bootstrap called Flask-Login user_loader')
    )

    response = fetch(
        app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, 'admin'),
    )

    assert response.status_code == 200
    assert response.json()['user']['role'] == 'admin'


def test_native_admin_bootstrap_does_not_push_flask_app_context(pilot, monkeypatch):
    flask_app, app = pilot
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('native bootstrap pushed Flask context')),
    )

    response = fetch(app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, 'admin'))

    assert response.status_code == 200
    assert response.json()['user']['role'] == 'admin'


@pytest.mark.parametrize('role,status', [(None, 401), ('member', 403), ('invalid', 401)])
def test_bootstrap_guards(pilot, role, status):
    flask_app, app = pilot
    response = fetch(app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, role) if role else None)
    assert response.status_code == status
    assert response.json()['ok'] is False
    assert response.headers['cache-control'] == 'no-store'


def test_shell_uses_login_redirect(pilot):
    _, app = pilot
    response = fetch(app, '/admin/users')
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text.startswith('<!doctype html>\n<html lang=en>\n<title>Redirecting...</title>')
    assert len(response.headers.get_list('set-cookie')) == 1


def test_admin_shell_page_skips_flask_request_context(pilot, monkeypatch):
    flask_app, app = pilot
    monkeypatch.setattr(
        flask_app, 'preprocess_request',
        lambda: (_ for _ in ()).throw(AssertionError('admin shell ran Flask hooks')),
    )
    monkeypatch.setattr(
        flask_app, 'request_context',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('admin shell created Flask request')),
    )

    response = fetch(app, '/admin/ops', signed_cookie(flask_app, 'admin'))

    assert response.status_code == 200
    assert 'id="admin-app-root"' in response.text


def test_bad_shell_fails_before_exposure(pilot, tmp_path):
    flask_app, _ = pilot
    invalid = tmp_path / 'bad.html'
    invalid.write_text('<html></html>', encoding='utf-8')
    with pytest.raises(ValueError):
        create_admin_pilot(flask_app, shell_path=invalid)


def test_session_identifier_keeps_existing_freshness(pilot):
    from flask_login.utils import _create_identifier
    flask_app, app = pilot
    with flask_app.test_request_context(environ_base={'REMOTE_ADDR': '127.0.0.1'},
                                        headers={'User-Agent': 'Pilot browser'}):
        identity = _create_identifier()
    user = flask_app._native_users[7]
    cookie = flask_app.session_interface.get_signing_serializer(flask_app).dumps({
        '_user_id': f'{user.id}:{user.session_fingerprint()}', '_fresh': True, '_id': identity,
    })
    response = fetch(app, '/admin/api/runtime-bootstrap', cookie, {'User-Agent': 'Pilot browser'})
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(response.cookies.get('session'))
    assert decoded['_fresh'] is True


@pytest.mark.parametrize('identity,status', [
    ('7:stale-fingerprint', 401),
    ('disabled', 401),
])
def test_bootstrap_rejects_stale_or_disabled_session_users(pilot, identity, status):
    flask_app, app = pilot
    if identity == 'disabled':
        class DisabledUser(PilotUser):
            is_active = False
        flask_app._native_users[7] = DisabledUser('admin')
        cookie_id = f"7:{flask_app._native_users[7].session_fingerprint()}"
    else:
        cookie_id = identity
    response = fetch(app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, cookie_id))
    assert response.status_code == status
    assert response.json()['error_code'] == 'unauthorized'
    assert response.headers['cache-control'] == 'no-store'


def test_bootstrap_basic_session_protection_downgrades_freshness(pilot):
    flask_app, app = pilot
    cookie = signed_cookie(flask_app, 'admin')
    response = fetch(app, '/admin/api/runtime-bootstrap', cookie)
    assert response.status_code == 200
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(
        response.cookies.get('session')
    )
    assert decoded['_fresh'] is False


def test_bootstrap_strong_session_protection_clears_auth_and_remember(pilot):
    flask_app, app = pilot
    flask_app.login_manager.session_protection = 'strong'
    user = flask_app._native_users[7]
    cookie = flask_app.session_interface.get_signing_serializer(flask_app).dumps({
        '_user_id': f'{user.id}:{user.session_fingerprint()}', '_fresh': True, '_id': 'other-client',
    })
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Cookie': f'session={cookie}; remember_token=old-value',
    })
    assert response.status_code == 401
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(
        response.cookies.get('session')
    )
    assert '_user_id' not in decoded
    assert '_remember' not in decoded
    assert any('remember_token=""' in value for value in response.headers.get_list('set-cookie'))


def test_bootstrap_honors_session_protection_config_override(pilot):
    flask_app, app = pilot
    flask_app.config['SESSION_PROTECTION'] = 'strong'
    user = flask_app._native_users[7]
    cookie = flask_app.session_interface.get_signing_serializer(flask_app).dumps({
        '_user_id': f'{user.id}:{user.session_fingerprint()}', '_fresh': True, '_id': 'other-client',
    })
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Cookie': f'session={cookie}; remember_token=old-value',
    })
    assert response.status_code == 401
    assert response.headers['x-request-id']
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(
        response.cookies.get('session')
    )
    assert '_user_id' not in decoded
    assert any('remember_token=""' in value for value in response.headers.get_list('set-cookie'))


def test_bootstrap_accepts_signed_remember_cookie_and_issues_nonfresh_session(pilot):
    from flask_login import encode_cookie

    flask_app, app = pilot
    user = flask_app._native_users[7]
    user_id = f'{user.id}:{user.session_fingerprint()}'
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Cookie': 'remember_token=' + encode_cookie(user_id, key=flask_app.secret_key),
    })
    assert response.status_code == 200
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(
        response.cookies.get('session')
    )
    assert decoded['_user_id'] == user_id
    assert decoded['_fresh'] is False


@dataclass
class PilotToken:
    user_id: int = 7
    token_hash: str = hashlib.sha256(b'secret').hexdigest()
    scopes: list[str] | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None

    def is_expired(self, now=None):
        return bool(self.expires_at and self.expires_at <= (now or datetime.now(timezone.utc)))

    def has_scope(self, scope):
        return 'admin' in (self.scopes or []) or scope in (self.scopes or [])


def _token_backend(user, token):
    touched = []
    return lambda _app: (
        lambda user_id: user if user_id == user.id else None,
        lambda prefix: token if prefix == 'deadbeef' else None,
        lambda row: touched.append(row),
    ), touched


def _token_pilot(pilot, user, token, tmp_path, monkeypatch):
    from oneirodex.runtime_native import admin_pilot

    flask_app, _ = pilot
    shell = tmp_path / 'token-shell.html'
    shell.write_text('<html><head></head><body><div id="admin-app-root"></div></body></html>', encoding='utf-8')
    backend, touched = _token_backend(user, token)
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', backend)
    app = create_admin_pilot(flask_app, shell_path=shell,
                             chrome_fields=lambda: {'theme': {}, 'preferences_url': '/settings_panel'},
                             database_scope=lambda _app: nullcontext())
    return flask_app, app, touched


def test_bootstrap_bearer_admin_scope_is_required(pilot, tmp_path, monkeypatch):
    user = PilotUser('admin')
    user.id = 7
    token = PilotToken(scopes=['read:library'])
    flask_app, app, touched = _token_pilot(pilot, user, token, tmp_path, monkeypatch)
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Authorization': 'Bearer gt_deadbeef_secret',
    })
    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert touched == [token]
    assert token.last_used_at is not None


@pytest.mark.parametrize('change', [
    {'revoked_at': datetime(2025, 1, 1, tzinfo=timezone.utc)},
    {'expires_at': datetime(2025, 1, 1, tzinfo=timezone.utc)},
    {'inactive': True},
])
def test_bootstrap_rejects_revoked_expired_or_inactive_bearer(pilot, tmp_path, change, monkeypatch):
    user = PilotUser('admin')
    user.id = 7
    token_kwargs = {key: value for key, value in change.items() if key != 'inactive'}
    token = PilotToken(scopes=['admin'], **token_kwargs)
    if change.get('inactive'):
        user.state = False
    flask_app, app, touched = _token_pilot(pilot, user, token, tmp_path, monkeypatch)
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Authorization': 'Bearer gt_deadbeef_secret',
    })
    assert response.status_code == 401
    assert response.json()['error_code'] == 'unauthorized'
    assert touched == []


def test_bootstrap_bearer_with_admin_scope_is_allowed(pilot, tmp_path, monkeypatch):
    user = PilotUser('admin')
    user.id = 7
    token = PilotToken(scopes=['admin'])
    flask_app, app, touched = _token_pilot(pilot, user, token, tmp_path, monkeypatch)
    response = fetch(app, '/admin/api/runtime-bootstrap', headers={
        'Authorization': 'Bearer gt_deadbeef_secret',
    })
    assert response.status_code == 200
    assert response.json()['user']['role'] == 'admin'
    assert touched == [token]


def test_cache_policy_survives_response_hooks(pilot):
    flask_app, app = pilot
    @flask_app.after_request
    def change_cache(response):
        response.headers['Cache-Control'] = 'public, max-age=600'
        return response
    response = fetch(app, '/admin/api/runtime-bootstrap', signed_cookie(flask_app, 'admin'))
    assert response.headers['cache-control'] == 'no-store'


def test_native_bootstrap_error_envelope_keeps_security_and_no_store(pilot):
    flask_app, app = pilot
    response = fetch(app, '/admin/api/runtime-bootstrap')
    assert response.status_code == 401
    assert response.json() == {
        'ok': False,
        'error': 'Sign in required',
        'error_code': 'unauthorized',
        'message': 'Sign in required',
        'success': False,
    }
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['vary'] == 'Cookie'
    assert response.headers['x-request-id']
    assert "script-src 'self'" in response.headers['content-security-policy']


@pytest.mark.parametrize('path', ADMIN_STATIC_ROUTES)
def test_static_route_admin_authorization_and_identical_shell(pilot, path):
    flask_app, app = pilot
    assert fetch(app, path).status_code == 302
    denied = fetch(app, path, signed_cookie(flask_app, 'member'))
    assert denied.status_code == 302
    assert denied.headers['location'].startswith('/login')
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.text == fetch(app, '/admin/users', signed_cookie(flask_app, 'admin')).text


@pytest.mark.parametrize('path', ['/admin/newsletter/7', '/admin/newsletter/0007', '/admin/newsletter/0', '/admin/newsletter/999999999999999999999'])
def test_numeric_newsletter_shell_retains_session_boundary(pilot, path):
    flask_app, app = pilot
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200 and 'admin-app-root' in response.text
    assert fetch(app, path).status_code == 302
    assert fetch(app, path, signed_cookie(flask_app, 'member')).status_code == 302

@pytest.mark.parametrize('path', ['/admin/newsletter/no', '/admin/newsletter/-1', '/admin/newsletter/7/extra', '/admin/newsletter/7/'])
def test_numeric_newsletter_shell_rejects_adjacent_paths(pilot, path):
    flask_app, app = pilot
    assert fetch(app, path, signed_cookie(flask_app, 'admin')).status_code == 404


def test_game_edit_dynamic_shell_retains_session_boundary(pilot):
    flask_app, app = pilot
    path = '/game_edit/123e4567-e89b-12d3-a456-426614174000'
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200 and 'admin-app-root' in response.text
    assert fetch(app, path).status_code == 302
    assert fetch(app, path, signed_cookie(flask_app, 'member')).status_code == 302


def test_game_images_edit_dynamic_shell_retains_session_boundary(pilot):
    flask_app, app = pilot
    path = '/edit_game_images/123e4567-e89b-12d3-a456-426614174000'
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200 and 'admin-app-root' in response.text
    assert fetch(app, path).status_code == 302
    assert fetch(app, path, signed_cookie(flask_app, 'member')).status_code == 302
    assert fetch(app, path + '/', signed_cookie(flask_app, 'admin')).status_code == 404


def test_library_edit_dynamic_shell_retains_session_boundary(pilot):
    flask_app, app = pilot
    path = '/admin/library/edit/123e4567-e89b-12d3-a456-426614174000'
    response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    assert response.status_code == 200 and 'admin-app-root' in response.text
    assert fetch(app, path).status_code == 302
    assert fetch(app, path, signed_cookie(flask_app, 'member')).status_code == 302
    assert fetch(app, path + '/', signed_cookie(flask_app, 'admin')).status_code == 404


@pytest.mark.parametrize('path', [
    '/admin/newsletter/999',
    '/admin/library/edit/123e4567-e89b-12d3-a456-426614174000',
    '/game_edit/123e4567-e89b-12d3-a456-426614174000',
    '/edit_game_images/123e4567-e89b-12d3-a456-426614174000',
])
def test_missing_admin_dynamic_entities_keep_404_and_render_shell(pilot, path):
    flask_app, app = pilot
    flask_app._pilot_shell_entity_exists['value'] = False

    get_response = fetch(app, path, signed_cookie(flask_app, 'admin'))
    head_response = fetch(app, path, signed_cookie(flask_app, 'admin'), method='HEAD')

    assert get_response.status_code == head_response.status_code == 404
    assert 'admin-app-root' in get_response.text
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert fetch(app, path).status_code == 302
    assert fetch(app, path, signed_cookie(flask_app, 'member')).status_code == 302


def test_admin_shell_default_entity_lookup_checks_only_the_expected_records(monkeypatch):
    from types import SimpleNamespace
    from oneirodex.models import Game, Library, Newsletter
    from oneirodex.runtime_native import admin_pilot
    from oneirodex.runtime_native import db_session

    calls = []

    class MissingSession:
        def get(self, model, identifier):
            calls.append(('get', model, identifier))
            return None

        def execute(self, statement):
            model = statement.column_descriptions[0]['entity']
            calls.append(('select', model, statement.compile().params))
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    paths = [
        '/admin/newsletter/999',
        '/admin/library/edit/123e4567-e89b-12d3-a456-426614174000',
        '/game_edit/123e4567-e89b-12d3-a456-426614174000',
        '/edit_game_images/123e4567-e89b-12d3-a456-426614174000',
    ]

    session_token = db_session._native_session.set(MissingSession())
    try:
        assert all(
            not admin_pilot._admin_shell_entity_exists(
                SimpleNamespace(url=SimpleNamespace(path=path)),
            )
            for path in paths
        )
        assert calls[0] == ('get', Newsletter, 999)
        assert [call[1] for call in calls[1:]] == [Library, Game, Game]
    finally:
        db_session._native_session.reset(session_token)



def test_legacy_manage_downloads_post_preserves_admin_shell_and_csrf(pilot):
    flask_app, app = pilot
    cookie = signed_cookie(flask_app, 'admin')
    bootstrap = fetch(app, '/admin/api/runtime-bootstrap', cookie)
    csrf = bootstrap.json()['csrf_token']
    refreshed_cookie = bootstrap.cookies.get('session') or cookie

    rejected = fetch(
        app, '/admin/manage-downloads', refreshed_cookie, method='POST', data={},
    )
    accepted = fetch(
        app, '/admin/manage-downloads', refreshed_cookie,
        headers={'X-CSRFToken': csrf}, method='POST', data={},
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert 'id="admin-app-root"' in accepted.text
