"""Phase 4 of the security/legal playbook — auth hardening (S6, S8, S10, S11).

The expiry tests carry the migration stance as much as the behaviour: a NULL
``expires_at`` means "never", because every token that existed before the column
did is NULL, and an upgrade that logged out live companions would be a worse
outcome than the finding it fixed.

See docs/strategy/security-legal-playbook.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from oneirodex.models import ApiToken, User
from oneirodex.utils import api_tokens
from oneirodex.utils.api_tokens import (
    generate_api_token,
    require_api_scope,
    user_has_scope,
    verify_bearer_token_detailed,
)
from oneirodex.utils.auth import safe_next_url


@pytest.fixture
def member(db_session):
    user_uuid = str(uuid4())
    user = User(
        name=f'member_{user_uuid[:8]}',
        email=f'member_{user_uuid[:8]}@example.com',
        password_hash='hashed',
        role='user',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
    )
    user.set_password('memberpassword123')
    db_session.add(user)
    db_session.commit()
    return user


# --- S8: open redirect ----------------------------------------------------

class TestSafeNextUrl:
    @pytest.mark.parametrize('candidate', [
        '/admin/dashboard',
        '/library?q=zelda&page=2',
        '/games/abc#screenshots',
    ])
    def test_same_site_paths_pass_through(self, app, candidate):
        with app.test_request_context('/'):
            assert safe_next_url(candidate) == candidate

    @pytest.mark.parametrize('candidate', [
        'http://evil.com/steal',
        'https://evil.com/steal',
        '//evil.com/steal',
        # The bypass the old netloc check missed: empty netloc, but a browser
        # normalises the leading /\ to // and treats it as protocol-relative.
        '/\\evil.com/steal',
        '\\\\evil.com/steal',
        'javascript:alert(1)',
        'evil.com',
        '',
        None,
    ])
    def test_off_site_candidates_fall_back(self, app, candidate):
        with app.test_request_context('/'):
            result = safe_next_url(candidate)
            assert result != candidate
            assert result.startswith('/')
            assert not result.startswith('//')

    def test_fallback_is_a_real_route(self, app):
        with app.test_request_context('/'):
            assert safe_next_url(None).startswith('/')


# --- S6: token expiry -----------------------------------------------------

class TestTokenExpiry:
    def test_token_without_expiry_never_expires(self, db_session, member):
        row, raw = generate_api_token(member, 'legacy')
        assert row.expires_at is None
        assert row.is_expired() is False
        assert row.is_active() is True

        user, token, reason = verify_bearer_token_detailed(raw)
        assert reason is None
        assert user.id == member.id

    def test_pre_existing_null_rows_keep_working(self, db_session, member):
        """The upgrade must not log out a live companion."""
        row, raw = generate_api_token(member, 'companion')
        row.expires_at = None
        db_session.commit()

        _user, _token, reason = verify_bearer_token_detailed(raw)
        assert reason is None

    def test_expiry_is_applied_when_requested(self, db_session, member):
        row, _raw = generate_api_token(member, 'scoped', expires_in_days=30)
        assert row.expires_at is not None
        # The column is TIMESTAMP, so Postgres hands it back naive after the
        # commit — which is the case is_expired() normalises. Do the same here.
        stored = row.expires_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        remaining = stored - datetime.now(timezone.utc)
        assert timedelta(days=29) < remaining <= timedelta(days=30)

    def test_expired_token_is_rejected(self, db_session, member):
        row, raw = generate_api_token(member, 'stale', expires_in_days=1)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        user, token, reason = verify_bearer_token_detailed(raw)
        assert user is None
        assert token is None
        assert reason == 'expired'

    def test_unexpired_token_still_verifies(self, db_session, member):
        _row, raw = generate_api_token(member, 'fresh', expires_in_days=7)
        _user, _token, reason = verify_bearer_token_detailed(raw)
        assert reason is None

    def test_expiry_checked_after_the_hash(self, db_session, member):
        """A wrong secret must not be distinguishable from an expired one."""
        row, raw = generate_api_token(member, 'stale', expires_in_days=1)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        prefix = raw.rsplit('_', 1)[0]
        _u, _t, reason = verify_bearer_token_detailed(f'{prefix}_wrongsecret')
        assert reason == 'bad_hash'

    def test_naive_timestamps_compare_as_utc(self, member):
        row = ApiToken(
            user_id=member.id,
            name='naive',
            token_prefix='deadbeef',
            token_hash='x',
            scopes=['read:library'],
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        )
        assert row.is_expired() is True

    def test_negative_expiry_is_refused(self, db_session, member):
        with pytest.raises(ValueError):
            generate_api_token(member, 'bad', expires_in_days=0)

    def test_public_dict_reports_expiry(self, db_session, member):
        row, _raw = generate_api_token(member, 'shown', expires_in_days=5)
        public = row.to_public_dict()
        assert public['expires_at'] is not None
        assert public['expired'] is False

    def test_public_dict_serializes_aware_timestamps_as_legacy_utc(self):
        row = ApiToken(
            name='aware timestamps',
            token_prefix='deadbeef',
            token_hash='x',
            scopes=['read:library'],
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            last_used_at=datetime(2026, 1, 1, 5, 0, tzinfo=timezone(timedelta(hours=5))),
            expires_at=datetime(2026, 1, 1, 6, 0, tzinfo=timezone(timedelta(hours=5))),
        )

        public = row.to_public_dict()

        assert public['created_at'] == '2026-01-01T00:00:00'
        assert public['last_used_at'] == '2026-01-01T00:00:00'
        assert public['expires_at'] == '2026-01-01T01:00:00'


# --- S10: session-cookie scopes -------------------------------------------

class TestSessionScopes:
    @pytest.fixture(autouse=True)
    def _no_bearer_token(self, app, monkeypatch):
        monkeypatch.setattr(api_tokens, 'g', SimpleNamespace(api_token=None))

    def _as(self, monkeypatch, role):
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=True, role=role),
        )

    @pytest.mark.parametrize('scope', ['admin', 'write:library', 'write:download'])
    def test_child_is_denied_write_and_admin_scopes(self, monkeypatch, scope):
        self._as(monkeypatch, 'child')
        assert user_has_scope(scope) is False

    @pytest.mark.parametrize('scope', ['read:library', 'read:social', 'write:presence'])
    def test_child_keeps_read_and_presence(self, monkeypatch, scope):
        self._as(monkeypatch, 'child')
        assert user_has_scope(scope) is True

    @pytest.mark.parametrize('scope', ['read:library', 'write:library', 'write:download'])
    def test_member_keeps_every_non_admin_scope(self, monkeypatch, scope):
        self._as(monkeypatch, 'user')
        assert user_has_scope(scope) is True

    def test_member_is_still_denied_admin(self, monkeypatch):
        self._as(monkeypatch, 'user')
        assert user_has_scope('admin') is False

    def test_admin_gets_everything(self, monkeypatch):
        self._as(monkeypatch, 'admin')
        assert user_has_scope('admin') is True
        assert user_has_scope('write:library') is True

    def test_anonymous_gets_nothing(self, monkeypatch):
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=False, role=None),
        )
        assert user_has_scope('read:library') is False


# --- S11: envelope on the scope decorator ---------------------------------

class TestScopeDecoratorEnvelope:
    def _route(self, app, scope='admin'):
        @require_api_scope(scope)
        def handler():
            return {'ok': True}

        return handler

    def test_unauthenticated_returns_the_envelope(self, app, monkeypatch):
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=False, role=None),
        )
        with app.test_request_context('/api/thing'):
            response, status = self._route(app)()
            assert status == 401
            body = response.get_json()
            assert body['ok'] is False
            assert body['error_code'] == 'unauthorized'

    def test_missing_scope_returns_the_envelope(self, app, monkeypatch):
        monkeypatch.setattr(api_tokens, 'g', SimpleNamespace(api_token=None))
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=True, role='user'),
        )
        with app.test_request_context('/api/thing'):
            response, status = self._route(app)()
            assert status == 403
            body = response.get_json()
            assert body['ok'] is False
            assert body['error_code'] == 'forbidden'
            assert body['detail']['required_scope'] == 'admin'


# --- Child ACL: Bearer deny-list, minting, acquire, companion commands ------

def _login(client, app, user):
    from flask_login import login_user

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


@pytest.fixture
def child_user(db_session):
    user_uuid = str(uuid4())
    user = User(
        name=f'child_{user_uuid[:8]}',
        email=f'child_{user_uuid[:8]}@example.com',
        password_hash='hashed',
        role='child',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        state=True,
    )
    user.set_password('childpassword123')
    db_session.add(user)
    db_session.commit()
    return user


class TestBearerRoleScopes:
    def test_child_bearer_cannot_use_denied_scopes_even_when_token_has_them(
        self, monkeypatch,
    ):
        token = SimpleNamespace(has_scope=lambda scope: True)
        monkeypatch.setattr(api_tokens, 'g', SimpleNamespace(api_token=token))
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=True, role='child'),
        )
        assert user_has_scope('write:download') is False
        assert user_has_scope('write:library') is False
        assert user_has_scope('admin') is False
        assert user_has_scope('read:library') is True

    def test_member_bearer_keeps_write_download(self, monkeypatch):
        token = SimpleNamespace(has_scope=lambda scope: scope == 'write:download')
        monkeypatch.setattr(api_tokens, 'g', SimpleNamespace(api_token=token))
        monkeypatch.setattr(
            api_tokens,
            'current_user',
            SimpleNamespace(is_authenticated=True, role='user'),
        )
        assert user_has_scope('write:download') is True


class TestChildTokenMinting:
    def test_generate_refuses_denied_scopes(self, db_session, child_user):
        with pytest.raises(ValueError, match='not allowed'):
            generate_api_token(child_user, 'box', ['write:download'])

    def test_generate_still_mints_read_library(self, db_session, child_user):
        row, raw = generate_api_token(child_user, 'ok', ['read:library'])
        assert 'write:download' not in (row.scopes or [])
        assert 'read:library' in row.scopes
        assert raw.startswith('gt_')

    def test_child_cannot_mint_companion_preset(self, client, app, child_user):
        _login(client, app, child_user)
        resp = client.post(
            '/api/tokens',
            json={'name': 'box', 'preset': 'companion'},
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body['error_code'] == 'forbidden'
        assert 'write:download' in (body.get('detail') or {}).get('denied_scopes', [])

    def test_child_can_mint_thin_preset(self, client, app, child_user):
        _login(client, app, child_user)
        resp = client.post(
            '/api/tokens',
            json={'name': 'thin', 'preset': 'thin'},
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert 'write:download' not in body['token']['scopes']

    def test_child_token_list_hides_companion_preset(self, client, app, child_user):
        _login(client, app, child_user)
        listed = client.get('/api/tokens')
        assert listed.status_code == 200
        body = listed.get_json()
        assert 'companion' not in body['scope_presets']
        assert 'thin' in body['scope_presets']
        assert 'write:download' not in body['valid_scopes']


class TestChildAcquireAndCommands:
    def test_child_cannot_search_acquire(self, client, app, child_user):
        _login(client, app, child_user)
        resp = client.get('/api/acquire/search?q=Stub')
        assert resp.status_code == 403
        body = resp.get_json()
        assert body['error_code'] == 'forbidden'
        assert 'child' in (body.get('error') or '').lower()

    def test_child_cannot_queue_install(self, client, app, child_user):
        _login(client, app, child_user)
        resp = client.post(
            '/api/client/commands',
            json={'game_uuid': str(uuid4()), 'action': 'install'},
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body['error_code'] == 'forbidden'
        assert body['detail']['required_scope'] == 'write:download'
