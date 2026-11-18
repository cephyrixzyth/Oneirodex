"""FEAT-D1 — version / updates / DLC checked as part of a scan."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask import json
from sqlalchemy import text

from oneirodex import db
from oneirodex.models import Game, Library, LibraryPlatform, User
from oneirodex.utils.freshness.service import check_library_freshness

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- scan freshness gate over the library.


@pytest.fixture(scope='function', autouse=True)
def clean(db_session):
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE libraries RESTART IDENTITY CASCADE'))
    db_session.commit()


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'admin_{uid[:8]}',
        email=f'admin_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10,
        is_email_verified=True,
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def library(db_session):
    lib = Library(name='Fresh Lib', platform=LibraryPlatform.PCWIN, display_order=1)
    db_session.add(lib)
    db_session.flush()
    for i in range(3):
        db_session.add(Game(
            library_uuid=lib.uuid, name=f'Game {i}', igdb_id=8800000 + i,
        ))
    db_session.commit()
    return lib


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestLibraryPass:
    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_checks_titles_and_reports_counts(self, mock_check, app, db_session, library):
        mock_check.return_value = {'status': 'current'}
        with app.app_context():
            result = check_library_freshness(library.uuid, limit=10)
            assert result['checked'] == 3
            assert result['failed'] == 0

    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_counts_titles_that_are_behind(self, mock_check, app, db_session, library):
        mock_check.return_value = {'status': 'behind'}
        with app.app_context():
            assert check_library_freshness(library.uuid, limit=10)['behind'] == 3

    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_a_store_outage_does_not_fail_the_pass(self, mock_check, app, db_session, library):
        """The scan already succeeded — a store being down must not undo that."""
        mock_check.side_effect = RuntimeError('store down')
        with app.app_context():
            result = check_library_freshness(library.uuid, limit=10)
            assert result['failed'] == 3
            assert result['checked'] == 0

    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_limit_caps_the_work(self, mock_check, app, db_session, library):
        mock_check.return_value = {'status': 'current'}
        with app.app_context():
            assert check_library_freshness(library.uuid, limit=2)['checked'] == 2

    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_only_missing_skips_titles_already_known(self, mock_check, app, db_session, library):
        mock_check.return_value = {'status': 'current'}
        with app.app_context():
            known = db.session.execute(
                db.select(Game).filter_by(library_uuid=library.uuid)
            ).scalars().first()
            known.freshness_status = 'current'
            db.session.commit()

            result = check_library_freshness(library.uuid, limit=10, only_missing=True)
            assert result['considered'] == 2

            everything = check_library_freshness(library.uuid, limit=10, only_missing=False)
            assert everything['considered'] == 3


class TestApi:
    @patch('oneirodex.utils.freshness.service.check_and_store_freshness')
    def test_runs_against_an_existing_library(self, mock_check, client, app, db_session, admin_user, library):
        mock_check.return_value = {'status': 'current'}
        _login(client, admin_user)
        response = client.post(
            '/api/library_tools/check_freshness',
            json={'library_uuid': library.uuid, 'limit': 5},
        )
        assert response.status_code == 200
        assert json.loads(response.data)['checked'] == 3

    def test_missing_library_is_404(self, client, admin_user):
        _login(client, admin_user)
        response = client.post(
            '/api/library_tools/check_freshness',
            json={'library_uuid': str(uuid4())},
        )
        assert response.status_code == 404

    def test_library_uuid_is_required(self, client, admin_user):
        _login(client, admin_user)
        response = client.post('/api/library_tools/check_freshness', json={})
        assert response.status_code == 422
        body = response.get_json()
        assert body['error_code'] == 'unprocessable'
        assert 'library_uuid' in body['detail']
