"""W22-1: admin batch library scan / edit / delete (+ force delete)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.models import Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_batch import (
    LIBRARY_BATCH_DELETE_CAP,
    names_match,
    parse_library_uuids,
    require_confirm_or_force,
)


@pytest.fixture
def admin_user(db_session):
    unique = uuid4().hex[:8]
    admin = User(
        user_id=str(uuid4()),
        name=f'Admin_{unique}',
        email=f'admin_{unique}@test.com',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    unique = uuid4().hex[:8]
    user = User(
        user_id=str(uuid4()),
        name=f'User_{unique}',
        email=f'user_{unique}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_library(db_session, *, name=None, folder=None, scan_depth=1):
    unique = uuid4().hex[:8]
    lib = Library(
        uuid=str(uuid4()),
        name=name or f'Lib_{unique}',
        platform=LibraryPlatform.PCWIN,
        scan_depth=scan_depth,
        last_scan_folder=folder,
    )
    db_session.add(lib)
    db_session.commit()
    return lib


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestLibraryBatchHelpers:
    def test_parse_uuids_singular_and_dedupe(self):
        uuids, err = parse_library_uuids({'library_uuid': 'a'})
        assert err is None
        assert uuids == ['a']
        uuids, err = parse_library_uuids({'library_uuids': ['a', 'a', 'b']})
        assert err is None
        assert uuids == ['a', 'b']

    def test_require_confirm_force_skips_name(self):
        assert require_confirm_or_force(
            library_uuid='u1',
            library_name='Alpha',
            force=True,
            confirm_names={},
            single_confirm_name=None,
        ) is None

    def test_require_confirm_mismatch(self):
        assert require_confirm_or_force(
            library_uuid='u1',
            library_name='Alpha',
            force=False,
            confirm_names={'u1': 'Wrong'},
            single_confirm_name=None,
        ) == 'confirm_name_mismatch'
        assert names_match('Alpha', 'Alpha')
        assert not names_match('Alpha', 'alpha ')


class TestBatchEditLibraries:
    def test_batch_edit_scan_depth_and_watch(
        self, client, admin_user, db_session
    ):
        a = _make_library(db_session, name='Edit A')
        b = _make_library(db_session, name='Edit B', scan_depth=1)
        _login(client, admin_user)

        resp = client.post(
            '/api/admin/libraries/batch/edit',
            json={
                'library_uuids': [a.uuid, b.uuid],
                'scan_depth': 2,
                'watch_enabled': False,
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['updated'] == 2
        db_session.refresh(a)
        db_session.refresh(b)
        assert a.scan_depth == 2
        assert b.scan_depth == 2
        assert a.watch_enabled is False
        assert b.watch_enabled is False

    def test_batch_edit_group_name(self, client, admin_user, db_session):
        a = _make_library(db_session, name='Group A')
        b = _make_library(db_session, name='Group B')
        _login(client, admin_user)

        resp = client.post(
            '/api/admin/libraries/batch/edit',
            json={
                'library_uuids': [a.uuid, b.uuid],
                'group_name': 'Arcade',
            },
        )
        assert resp.status_code == 200
        db_session.refresh(a)
        db_session.refresh(b)
        assert a.group_name == 'Arcade'
        assert b.group_name == 'Arcade'

        clear = client.post(
            '/api/admin/libraries/batch/edit',
            json={
                'library_uuids': [a.uuid],
                'group_name': '',
            },
        )
        assert clear.status_code == 200
        db_session.refresh(a)
        assert a.group_name is None
        db_session.refresh(b)
        assert b.group_name == 'Arcade'

    def test_batch_edit_requires_fields(self, client, admin_user, db_session):
        lib = _make_library(db_session)
        _login(client, admin_user)
        resp = client.post(
            '/api/admin/libraries/batch/edit',
            json={'library_uuids': [lib.uuid]},
        )
        assert resp.status_code == 400
        assert resp.get_json()['ok'] is False

    def test_non_admin_forbidden(self, client, regular_user, db_session):
        lib = _make_library(db_session)
        _login(client, regular_user)
        resp = client.post(
            '/api/admin/libraries/batch/edit',
            json={'library_uuids': [lib.uuid], 'scan_depth': 2},
        )
        assert resp.status_code in (401, 403, 302)


class TestBatchScanLibraries:
    def test_batch_scan_queues_and_skips_missing_folder(
        self, client, admin_user, db_session, app
    ):
        app.config.update({
            'DATA_FOLDER_GAMES': '/games',
            'BASE_FOLDER_POSIX': '/games',
            'BASE_FOLDER_WINDOWS': '/games',
            'LIBRARY_ROOTS': [],
        })
        with_folder = _make_library(
            db_session, name='HasFolder', folder='/games/pc'
        )
        no_folder = _make_library(db_session, name='NoFolder', folder=None)
        _login(client, admin_user)

        with patch(
            'oneirodex.utils.scan_queue.start_or_queue_scan',
            return_value={
                'status': 'queued',
                'job_id': 'job-1',
                'position': 1,
                'message': 'Queued',
            },
        ) as mock_start:
            resp = client.post(
                '/api/admin/libraries/batch/scan',
                json={'library_uuids': [with_folder.uuid, no_folder.uuid]},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['queued'] == 1
        assert body['skipped'] == 1
        assert mock_start.call_count == 1
        by_uuid = {r['uuid']: r for r in body['results']}
        assert by_uuid[with_folder.uuid]['status'] == 'queued'
        assert by_uuid[no_folder.uuid]['error'] == 'no_scan_folder'

    def test_batch_scan_rejects_out_of_root_path_without_queueing(
        self, client, admin_user, db_session, app
    ):
        app.config.update({
            'DATA_FOLDER_GAMES': '/games',
            'BASE_FOLDER_POSIX': '/games',
            'BASE_FOLDER_WINDOWS': '/games',
            'LIBRARY_ROOTS': [],
        })
        allowed = _make_library(db_session, name='Allowed', folder='/games/pc')
        denied = _make_library(db_session, name='Denied', folder='/outside/private')
        _login(client, admin_user)

        with patch(
            'oneirodex.utils.scan_queue.start_or_queue_scan',
            return_value={
                'status': 'queued', 'job_id': 'safe-job', 'position': 1,
                'message': 'Queued',
            },
        ) as mock_start:
            response = client.post('/api/admin/libraries/batch/scan', json={
                'library_uuids': [allowed.uuid, denied.uuid],
            })

        assert response.status_code == 200
        body = response.get_json()
        assert body['queued'] == 1
        assert body['failed'] == 1
        by_uuid = {row['uuid']: row for row in body['results']}
        assert by_uuid[denied.uuid]['status'] == 'rejected'
        assert by_uuid[denied.uuid]['error'] == 'forbidden'
        assert '/outside/private' not in response.get_data(as_text=True)
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs['folder_path'] == '/games/pc'


class TestBatchDeleteLibraries:
    def test_delete_requires_confirm_without_force(
        self, client, admin_user, db_session
    ):
        lib = _make_library(db_session, name='MustType')
        _login(client, admin_user)
        resp = client.post(
            '/api/admin/libraries/batch/delete',
            json={'library_uuids': [lib.uuid]},
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'confirm_name_required'

    def test_delete_confirm_name_mismatch(
        self, client, admin_user, db_session
    ):
        lib = _make_library(db_session, name='Exact Name')
        _login(client, admin_user)
        resp = client.post(
            '/api/admin/libraries/batch/delete',
            json={
                'library_uuids': [lib.uuid],
                'confirm_names': {lib.uuid: 'Wrong'},
            },
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['started'] == 0
        assert body['results'][0]['error'] == 'confirm_name_mismatch'

    def test_delete_with_matching_confirm_starts(
        self, client, admin_user, db_session
    ):
        lib = _make_library(db_session, name='Exact Name')
        _login(client, admin_user)
        with patch(
            'oneirodex.routes_apis.library.delete_library_background',
            create=True,
        ):
            # Patch where used: _start_library_delete_job imports the worker
            # from routes_admin_ext.library_delete.
            with patch(
                'oneirodex.routes_admin_ext.library_delete.delete_library_background'
            ) as mock_bg:
                mock_bg.return_value = None
                resp = client.post(
                    '/api/admin/libraries/batch/delete',
                    json={
                        'library_uuids': [lib.uuid],
                        'confirm_names': {lib.uuid: 'Exact Name'},
                    },
                )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['started'] == 1
        assert body['results'][0]['job_id']
        assert body['force'] is False
        mock_bg.assert_called_once()

    def test_force_delete_skips_confirm(
        self, client, admin_user, db_session
    ):
        a = _make_library(db_session, name='A')
        b = _make_library(db_session, name='B')
        _login(client, admin_user)
        with patch('oneirodex.routes_admin_ext.library_delete.delete_library_background') as mock_bg:
            mock_bg.return_value = None
            resp = client.post(
                '/api/admin/libraries/batch/delete',
                json={
                    'library_uuids': [a.uuid, b.uuid],
                    'force': True,
                },
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['started'] == 2
        assert body['force'] is True
        assert mock_bg.call_count == 2

    def test_single_delete_force_flag(
        self, client, admin_user, db_session
    ):
        lib = _make_library(db_session, name='Solo')
        _login(client, admin_user)
        with patch('oneirodex.routes_admin_ext.library_delete.delete_library_background') as mock_bg:
            mock_bg.return_value = None
            # Wrong confirm without force → 400
            bad = client.post(
                f'/delete_full_library/{lib.uuid}',
                json={'confirm_name': 'Nope'},
            )
            assert bad.status_code == 400
            assert bad.get_json()['error'] == 'confirm_name_mismatch'

            ok = client.post(
                f'/delete_full_library/{lib.uuid}',
                json={'force': True},
            )
            assert ok.status_code == 200
            assert ok.get_json()['status'] == 'started'
            mock_bg.assert_called_once()

    def test_delete_cap(self, client, admin_user, db_session):
        _login(client, admin_user)
        too_many = [str(uuid4()) for _ in range(LIBRARY_BATCH_DELETE_CAP + 1)]
        resp = client.post(
            '/api/admin/libraries/batch/delete',
            json={'library_uuids': too_many, 'force': True},
        )
        assert resp.status_code == 400
        assert resp.get_json()['cap'] == LIBRARY_BATCH_DELETE_CAP
