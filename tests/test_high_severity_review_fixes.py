"""Regression tests for the password-reset crash and the library-root delete."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex import db
from oneirodex.models import User
from oneirodex.utils.security import is_safe_path_strict


def _reset_user(token, issued_at):
    user = User(
        user_id=str(uuid4()),
        name=f'reset-{uuid4().hex[:8]}',
        email=f'{uuid4().hex[:8]}@example.com',
        role='user',
        is_email_verified=True,
        password_reset_token=token,
        token_creation_time=issued_at,
        created=datetime.now(timezone.utc),
    )
    user.set_password('Sup3r-secret-pass!')
    db.session.add(user)
    db.session.commit()
    # Reload from Postgres so the column comes back naive, as it does in production.
    db.session.expire_all()
    return user


class TestPasswordResetLink:
    def test_fresh_link_renders_the_form(self, client, configured_install, global_settings, db_session):
        _reset_user('fresh-token', datetime.now(timezone.utc))
        response = client.get('/reset_password/fresh-token')
        assert response.status_code == 200

    def test_expired_link_redirects(self, client, configured_install, global_settings, db_session):
        _reset_user('old-token', datetime.now(timezone.utc) - timedelta(hours=1))
        response = client.get('/reset_password/old-token')
        assert response.status_code == 302

    def test_unknown_token_redirects(self, client, configured_install, global_settings, db_session):
        response = client.get('/reset_password/no-such-token')
        assert response.status_code == 302


class TestStrictPathCheck:
    def test_root_itself_is_refused(self, app, tmp_path):
        with app.app_context():
            ok, error = is_safe_path_strict(str(tmp_path), [str(tmp_path)])
        assert ok is False
        assert 'library root' in error

    def test_root_with_trailing_slash_is_refused(self, app, tmp_path):
        with app.app_context():
            ok, _ = is_safe_path_strict(str(tmp_path) + '/', [str(tmp_path)])
        assert ok is False

    def test_item_inside_root_is_allowed(self, app, tmp_path):
        with app.app_context():
            ok, error = is_safe_path_strict(str(tmp_path / 'Some Game'), [str(tmp_path)])
        assert ok is True
        assert error is None

    def test_outside_root_is_refused(self, app, tmp_path):
        with app.app_context():
            ok, _ = is_safe_path_strict(str(tmp_path.parent), [str(tmp_path)])
        assert ok is False


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'root_del_admin_{uid[:8]}',
        email=f'root_del_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


class TestDeleteFolderRoute:
    @pytest.fixture
    def library(self, app, tmp_path):
        root = tmp_path / 'library'
        (root / 'Game A').mkdir(parents=True)
        (root / 'Game A' / 'game.iso').write_bytes(b'x')
        with patch(
            'oneirodex.routes_admin_ext.game_delete.get_allowed_base_directories',
            return_value=[str(root)],
        ):
            yield root

    def _login_admin(self, client, admin_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

    def test_refuses_to_delete_the_library_root(self, client, db_session, admin_user, library):
        self._login_admin(client, admin_user)
        response = client.post('/delete_folder', json={'folder_path': str(library)})
        assert response.status_code == 403
        assert (library / 'Game A' / 'game.iso').exists()

    def test_deletes_a_folder_inside_the_root(self, client, db_session, admin_user, library):
        self._login_admin(client, admin_user)
        response = client.post('/delete_folder', json={'folder_path': str(library / 'Game A')})
        assert response.status_code == 200
        assert not (library / 'Game A').exists()
        assert library.exists()

    def test_refuses_while_a_scan_runs(self, client, db_session, admin_user, library):
        self._login_admin(client, admin_user)
        with patch('oneirodex.routes_admin_ext.game_delete.is_scan_job_running', return_value=True):
            response = client.post('/delete_folder', json={'folder_path': str(library / 'Game A')})
        assert response.status_code == 403
        assert (library / 'Game A').exists()
