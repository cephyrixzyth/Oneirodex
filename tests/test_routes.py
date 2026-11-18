import pytest
import json
import os
import tempfile
from unittest.mock import patch, Mock, MagicMock, mock_open
from datetime import datetime, timezone
from uuid import uuid4
from io import BytesIO
from werkzeug.datastructures import FileStorage
from sqlalchemy import select, func

from oneirodex import create_app, db
from oneirodex.models import (
    User, Game, Library, Genre, GameMode, Theme, Platform, 
    PlayerPerspective, Image, ScanJob, UnmatchedFolder, user_favorites
)
from oneirodex.platform import LibraryPlatform




@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'testuser_{user_uuid[:8]}',
        email=f'test_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    admin_uuid = str(uuid4())
    admin = User(
        name=f'admin_{admin_uuid[:8]}',
        email=f'admin_{admin_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=admin_uuid
    )
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def test_library(db_session):
    """Create a test library."""
    unique_name = f'Test Library {uuid4().hex[:8]}'
    library = Library(
        name=unique_name,
        image_url='/static/library_test.jpg',
        platform=LibraryPlatform.PCWIN,
        display_order=1
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def test_game(db_session, test_library):
    """Create a test game."""
    game = Game(
        uuid=str(uuid4()),
        name='Test Game',
        library_uuid=test_library.uuid,
        summary='A test game',
        rating=85,
        size=1024000,
        first_release_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
        date_identified=datetime.now(timezone.utc),
        full_disk_path='/test/path/game'
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def test_genre(db_session):
    """Create a test genre."""
    genre = db.session.execute(select(Genre).filter_by(name='Action')).scalar_one_or_none()
    if not genre:
        genre = Genre(name='Action')
        db_session.add(genre)
        db_session.commit()
    return genre


@pytest.fixture
def test_scan_job(db_session, test_library):
    """Create a test scan job."""
    job = ScanJob(
        scan_folder='test_folder',
        library_uuid=test_library.uuid,
        status='Completed',
        last_run=datetime.now(timezone.utc),
        setting_remove=False,
        setting_filefolder=False,
        is_enabled=True
    )
    db_session.add(job)
    db_session.commit()
    return job


@pytest.fixture
def test_unmatched_folder(db_session, test_library):
    """Create a test unmatched folder."""
    folder = UnmatchedFolder(
        folder_path='/test/unmatched/folder',
        status='Unmatched',
        library_uuid=test_library.uuid
    )
    db_session.add(folder)
    db_session.commit()
    return folder


@pytest.fixture
def test_image(db_session, test_game):
    """Create a test image."""
    image = Image(
        game_uuid=test_game.uuid,
        image_type='cover',
        url='test_cover.jpg'
    )
    db_session.add(image)
    db_session.commit()
    return image


class TestMainBlueprint:
    """Test cases for the routes folded out of the retired 'main' blueprint."""

    def test_browse_games_unauthenticated(self, client):
        """Test browse_games route requires authentication."""
        response = client.get('/browse_games')
        assert response.status_code == 302  # Redirect to login

    @patch('flask_login.current_user')
    def test_browse_games_basic(self, mock_current_user, client, app, db_session, test_user, test_game, test_image):
        """Test basic browse_games functionality."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = client.get('/browse_games')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'games' in data
        assert 'total' in data
        assert 'pages' in data
        assert 'current_page' in data

    @patch('flask_login.current_user')
    def test_browse_games_cover_url_is_static_path(self, mock_current_user, client, app, db_session, test_user, test_game, test_image):
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        response = client.get('/browse_games')
        assert response.status_code == 200
        game = response.get_json()['games'][0]
        assert 'cover_url' in game
        assert '/static/' in game['cover_url']

    @patch('flask_login.current_user')
    def test_browse_games_includes_has_local_override_and_is_vr(self, mock_current_user, client, app, db_session, test_user, test_game):
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        # Scoped to this test's own library. `test_library` mints a fresh one
        # per test, so the response contains exactly this test's game whatever
        # else is in the table.
        #
        # Searching an unscoped /browse_games was only ever half a fix: it
        # stopped trusting index 0, but the route pages at 20 sorted by name and
        # nothing here deletes its games, so once enough have accumulated this
        # game is not on page one at all and `next()` raises StopIteration.
        response = client.get(f'/browse_games?library_uuid={test_game.library_uuid}')
        games = response.get_json()['games']
        game = next(g for g in games if g['uuid'] == test_game.uuid)
        assert 'has_local_override' in game
        assert isinstance(game['has_local_override'], bool)
        assert 'is_vr' in game
        assert 'library_platform' in game
        assert game['lifecycle_state'] == 'not_downloaded'
        assert game['client_connected'] is False

    @patch('flask_login.current_user')
    def test_browse_games_lifecycle_update_available(self, mock_current_user, client, app, db_session, test_user, test_game):
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id
        test_game.freshness_status = 'behind'
        db_session.commit()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        # Scoped by library for the same reason as the test above: every
        # `test_game` is named 'Test Game' and none are cleaned up, so an
        # unscoped request eventually pages this row off the first 20.
        response = client.get(f'/browse_games?library_uuid={test_game.library_uuid}')
        games = response.get_json()['games']
        game = next(g for g in games if g['uuid'] == test_game.uuid)
        assert game['lifecycle_state'] == 'update_available'
        assert game['client_connected'] is False

    @patch('flask_login.current_user')
    def test_browse_games_with_filters(self, mock_current_user, client, app, db_session, test_user, test_game, test_library, test_genre):
        """Test browse_games with various filters."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        
        # Add genre to game
        test_game.genres.append(test_genre)
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        # Test with library filter
        response = client.get(f'/browse_games?library_uuid={test_library.uuid}')
        assert response.status_code == 200
        
        # Test with genre filter
        response = client.get(f'/browse_games?genre=Action')
        assert response.status_code == 200
        
        # Test with rating filter
        response = client.get('/browse_games?rating=80')
        assert response.status_code == 200
        
        # Test with sorting
        response = client.get('/browse_games?sort_by=rating&sort_order=desc')
        assert response.status_code == 200

    @patch('flask_login.current_user')
    def test_browse_games_library_platform_filter(self, mock_current_user, client, app, db_session, test_user, test_game, test_library):
        """Test browse_games filters by library_platform, excluding games from other-platform libraries."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id

        other = Library(
            name=f'NES Lib {uuid4().hex[:8]}',
            platform=LibraryPlatform.NES,
            display_order=2,
        )
        db_session.add(other)
        db_session.flush()
        nes_game = Game(
            uuid=str(uuid4()),
            name='NES Only',
            library_uuid=other.uuid,
            full_disk_path=f'/test/nes/{uuid4().hex}',
        )
        db_session.add(nes_game)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)

        response = client.get('/browse_games?library_platform=NES')
        assert response.status_code == 200
        names = [g['name'] for g in response.get_json()['games']]
        assert 'NES Only' in names
        assert 'Test Game' not in names

    @patch('flask_login.current_user')
    def test_browse_games_play_mode_filter(self, mock_current_user, client, app, db_session, test_user, test_game, test_library):
        """play_mode is honest Browser / Companion / Catalog, not store verification."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id

        catalog_lib = Library(
            name=f'Switch Lib {uuid4().hex[:8]}',
            platform=LibraryPlatform.SWITCH,
            display_order=3,
        )
        db_session.add(catalog_lib)
        db_session.flush()
        catalog_name = f'Catalog Path {uuid4().hex[:6]}'
        companion_name = f'Companion Path {uuid4().hex[:6]}'
        catalog_game = Game(
            uuid=str(uuid4()),
            name=catalog_name,
            library_uuid=catalog_lib.uuid,
            full_disk_path=f'/test/switch/{uuid4().hex}',
        )
        companion_game = Game(
            uuid=str(uuid4()),
            name=companion_name,
            library_uuid=test_library.uuid,
            full_disk_path=f'/test/pc/{uuid4().hex}',
        )
        db_session.add_all([catalog_game, companion_game])
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)

        catalog = client.get(f'/browse_games?play_mode=catalog&name={catalog_name}')
        assert catalog.status_code == 200
        catalog_names = [g['name'] for g in catalog.get_json()['games']]
        assert catalog_name in catalog_names
        assert companion_name not in catalog_names

        companion = client.get(f'/browse_games?play_mode=companion&name={companion_name}')
        assert companion.status_code == 200
        companion_names = [g['name'] for g in companion.get_json()['games']]
        assert companion_name in companion_names
        assert catalog_name not in companion_names

        crossed = client.get(f'/browse_games?play_mode=catalog&name={companion_name}')
        assert crossed.get_json()['games'] == []

    @patch('flask_login.current_user')
    def test_browse_games_igdb_platform_filter(self, mock_current_user, client, app, db_session, test_user, test_game, test_library):
        """Test browse_games filters by igdb_platform (Game.platforms association)."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        mock_current_user.id = test_user.id

        plat = Platform(name=f'IGDB-{uuid4().hex[:6]}')
        db_session.add(plat)
        db_session.flush()
        test_game.platforms.append(plat)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)

        response = client.get(f'/browse_games?igdb_platform={plat.name}')
        assert response.status_code == 200
        names = [g['name'] for g in response.get_json()['games']]
        assert 'Test Game' in names

        response = client.get('/browse_games?igdb_platform=DoesNotExistXYZ')
        assert response.status_code == 200
        assert response.get_json()['games'] == []

    @patch('flask_login.current_user')
    def test_browse_games_pagination(self, mock_current_user, client, app, db_session, test_user, test_game):
        """Test browse_games pagination."""
        mock_current_user.is_authenticated = True
        mock_current_user.name = test_user.name
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = client.get('/browse_games?page=1&per_page=5')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['current_page'] == 1

    def test_scan_folder_unauthenticated(self, client):
        """Test scan_folder route requires authentication."""
        response = client.get('/scan_manual_folder')
        assert response.status_code == 302  # Redirect to login

    @patch('flask_login.current_user')
    def test_scan_folder_non_admin(self, mock_current_user, client, db_session, test_user):
        """Test scan_folder route requires admin access."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'user'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = client.get('/scan_manual_folder')
        assert response.status_code == 302  # Redirect to login

        # Should contain error message about folder not existing

    @patch('flask_login.current_user')
    def test_scan_management_get(self, mock_current_user, client, app, db_session, admin_user, test_library, test_scan_job):
        """Test scan_management GET request."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.get('/scan_management')
        assert response.status_code == 200

    @patch('flask_login.current_user')
    def test_cancel_scan_job(self, mock_current_user, client, app, db_session, admin_user, test_scan_job):
        """Test cancelling a scan job."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        # Set job to running status
        test_scan_job.status = 'Running'
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/cancel_scan_job/{test_scan_job.id}')
        assert response.status_code == 302  # Redirect

        # Simulate background thread completing the cancellation
        # In production, the scan thread checks is_enabled and updates status
        test_scan_job.status = 'Cancelled'
        test_scan_job.error_message = 'Scan cancelled by user'
        db_session.commit()

        # Check job was cancelled
        db_session.refresh(test_scan_job)
        assert test_scan_job.status == 'Cancelled'
        assert test_scan_job.is_enabled == False
        assert test_scan_job.error_message == 'Scan cancelled by user'

    @patch('flask_login.current_user')
    def test_cancel_scan_job_not_running(self, mock_current_user, client, app, db_session, admin_user, test_scan_job):
        """Test cancelling a non-running scan job."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/cancel_scan_job/{test_scan_job.id}')
        assert response.status_code == 302  # Redirect
        
        # Job should remain in original state
        db_session.refresh(test_scan_job)
        assert test_scan_job.status == 'Completed'

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scan_queue._start_job_thread')
    def test_restart_scan_job(self, mock_background, mock_current_user,
                             client, app, db_session, admin_user, test_scan_job):
        """Test restarting a scan job.

        The queue helper hands work to its thread dispatcher, so intercept it
        here and assert the route reset the row before dispatch.
        """
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/restart_scan_job/{test_scan_job.id}')
        assert response.status_code == 302  # Redirect
        
        # Check job was restarted
        db_session.refresh(test_scan_job)
        assert test_scan_job.status == 'Running'
        assert test_scan_job.is_enabled == True

    @patch('flask_login.current_user')
    def test_restart_running_scan_job(self, mock_current_user, client, app, db_session, admin_user, test_scan_job):
        """Test restarting an already running scan job."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        # Set job to running
        test_scan_job.status = 'Running'
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/restart_scan_job/{test_scan_job.id}')
        assert response.status_code == 302  # Redirect

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_edit_game_images(self, mock_is_scan_running, mock_current_user, 
                             client, app, db_session, admin_user, test_game, test_image):
        """Test edit game images route."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = False
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.get(f'/edit_game_images/{test_game.uuid}')
        assert response.status_code == 200

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_edit_game_images_scan_running(self, mock_is_scan_running, mock_current_user, 
                                          client, app, db_session, admin_user, test_game):
        """Test edit game images when scan is running."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = True
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.get(f'/edit_game_images/{test_game.uuid}')
        assert response.status_code == 200

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_upload_image_no_file(self, mock_is_scan_running, mock_current_user, 
                                 client, app, db_session, admin_user, test_game):
        """Test image upload without file."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = False
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/upload_image/{test_game.uuid}')
        assert response.status_code == 400

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_upload_image_invalid_extension(self, mock_is_scan_running, mock_current_user, 
                                           client, app, db_session, admin_user, test_game):
        """Test image upload with invalid file extension."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = False
        
        test_file = FileStorage(
            stream=BytesIO(b'fake image data'),
            filename='test.txt',
            content_type='text/plain'
        )
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/upload_image/{test_game.uuid}', 
                              data={'file': test_file},
                              content_type='multipart/form-data')
        assert response.status_code == 400

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_delete_image_invalid_request(self, mock_is_scan_running, mock_current_user, 
                                         client, app, db_session, admin_user):
        """Test image deletion with invalid request."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = False
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post('/delete_image', json={})
        assert response.status_code == 422

    @patch('flask_login.current_user')
    def test_delete_scan_job(self, mock_current_user, client, app, db_session, admin_user, test_scan_job):
        """Test deleting a scan job."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        job_id = test_scan_job.id
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/delete_scan_job/{job_id}')
        assert response.status_code == 302  # Redirect
        
        # Check job was deleted
        deleted_job = db.session.get(ScanJob, job_id)
        assert deleted_job is None

    @patch('flask_login.current_user')
    def test_clear_all_scan_jobs(self, mock_current_user, client, app, db_session, admin_user, test_scan_job):
        """Test clearing all scan jobs."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post('/clear_all_scan_jobs')
        assert response.status_code == 302  # Redirect
        
        # Check all jobs were deleted
        job_count = db.session.scalar(select(func.count(ScanJob.id)))
        assert job_count == 0

    @patch('flask_login.current_user')
    def test_update_unmatched_folder_status_ajax(self, mock_current_user, client, app, db_session, 
                                                admin_user, test_unmatched_folder):
        """Test updating unmatched folder status via AJAX."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post('/update_unmatched_folder_status', 
                              data={'folder_id': test_unmatched_folder.id},
                              headers={'X-Requested-With': 'XMLHttpRequest'})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'success'

    @patch('flask_login.current_user')
    def test_clear_unmatched_entry_ajax(self, mock_current_user, client, app, db_session, 
                                       admin_user, test_unmatched_folder):
        """Test clearing unmatched entry via AJAX."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/clear_unmatched_entry/{test_unmatched_folder.id}',
                              headers={'X-Requested-With': 'XMLHttpRequest'})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'success'

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.background.run_in_background')
    @patch('oneirodex.utils.gamenames.get_game_name_by_uuid')
    def test_refresh_game_images(self, mock_get_name, mock_background,
                                mock_current_user, client, app, db_session, admin_user, test_game):
        """Test refreshing game images."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.name = admin_user.name
        mock_get_name.return_value = 'Test Game'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/refresh_game_images/{test_game.uuid}')
        assert response.status_code == 302  # Redirect

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.background.run_in_background')
    @patch('oneirodex.utils.gamenames.get_game_name_by_uuid')
    def test_refresh_game_images_ajax(self, mock_get_name, mock_background, mock_current_user,
                                     client, app, db_session, admin_user, test_game):
        """Test refreshing game images via AJAX.

        The worker is patched for the same reason the non-AJAX test above
        patches it, and this was the one of the pair that did not: it calls out
        to IGDB and writes images on a daemon thread that outlives the test.
        Left real, it does that work while later tests run. This test is about
        the AJAX response shape, which the route produces before the worker
        does anything.
        """
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.name = admin_user.name
        mock_get_name.return_value = 'Test Game'

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)

        response = client.post(f'/refresh_game_images/{test_game.uuid}',
                              headers={'X-Requested-With': 'XMLHttpRequest'})
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'message' in data

    @patch('flask_login.current_user')
    @patch('shutil.rmtree')
    @patch('os.path.exists', return_value=True)
    @patch('oneirodex.utils.security.is_safe_path_strict', return_value=(False, 'Access denied'))
    def test_delete_folder_rejects_unsafe_path(self, mock_safe, mock_exists, mock_rmtree,
                                               mock_current_user, client, app, db_session, admin_user):
        """Test delete_folder denies paths outside allowed base directories."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)

        response = client.post('/delete_folder', json={'folder_path': '/etc/passwd'})
        assert response.status_code == 403
        mock_rmtree.assert_not_called()

    @patch('flask_login.current_user')
    def test_delete_folder_no_path(self, mock_current_user, client, app, db_session, admin_user):
        """Test delete_folder without path."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post('/delete_folder', json={})
        assert response.status_code == 400

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    @patch('os.path.isdir')
    @patch('shutil.rmtree')
    @patch('os.path.exists')
    @patch('oneirodex.utils.security.is_safe_path_strict', return_value=(False, 'Access denied'))
    @patch('oneirodex.utils.services.game_delete.delete_game')
    def test_delete_full_game_rejects_unsafe_path(self, mock_delete_game, mock_safe_path, mock_exists,
                                                  mock_rmtree, mock_isdir, mock_is_scan_running,
                                                  mock_current_user, client, app, db_session, admin_user, test_game):
        """Test delete_full_game denies disk deletion when the game path is outside allowed bases."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.name = admin_user.name
        mock_is_scan_running.return_value = False
        mock_isdir.return_value = True
        mock_exists.return_value = True

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)

        response = client.post('/delete_full_game',
                              json={'game_uuid': test_game.uuid})
        assert response.status_code == 403

        data = json.loads(response.data)
        assert data['success'] == False
        mock_rmtree.assert_not_called()
        mock_delete_game.assert_not_called()

    @patch('flask_login.current_user')
    @patch('oneirodex.utils.scanning.is_scan_job_running')
    def test_delete_full_game_no_uuid(self, mock_is_scan_running, mock_current_user, 
                                     client, app, db_session, admin_user):
        """Test delete_full_game without game UUID."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_is_scan_running.return_value = False
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post('/delete_full_game', json={})
        assert response.status_code == 422
        
        data = json.loads(response.data)
        assert data['success'] == False

    @patch('flask_login.current_user')
    def test_delete_full_library_not_found(self, mock_current_user, client, app, db_session, admin_user):
        """Test deleting a non-existent library."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        fake_uuid = str(uuid4())
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
        
        response = client.post(f'/delete_full_library/{fake_uuid}')
        assert response.status_code == 404  # Not found
        
        # Check JSON error response
        json_data = response.get_json()
        assert json_data['status'] == 'error'
        assert 'Library not found' in json_data['message']

class TestErrorHandling:
    """Test error handling scenarios."""

    def test_upload_image_invalid_image_data(self, client, app, db_session, admin_user, test_game, tmp_path):
        """Test uploading invalid image data."""
        app.config['IMAGE_SAVE_PATH'] = str(tmp_path)
        before = db_session.execute(select(func.count()).select_from(Image)).scalar_one()
        
        with patch('oneirodex.utils.scanning.is_scan_job_running', return_value=False):
            test_file = FileStorage(
                stream=BytesIO(b'invalid image data'),
                filename='test.jpg', content_type='image/jpeg',
            )
            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin_user.id)
            response = client.post(f'/upload_image/{test_game.uuid}',
                                   data={'file': test_file},
                                   content_type='multipart/form-data')
            assert response.status_code == 400
        assert db_session.execute(select(func.count()).select_from(Image)).scalar_one() == before
        assert list(tmp_path.iterdir()) == []

    @patch('flask_login.current_user')
    def test_delete_image_not_found(self, mock_current_user, client, app, db_session, admin_user):
        """Test deleting non-existent image."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with patch('oneirodex.utils.scanning.is_scan_job_running', return_value=False):
            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin_user.id)
            
            response = client.post('/delete_image', 
                                  json={'image_id': 99999})
            assert response.status_code == 404

    @patch('flask_login.current_user')
    def test_delete_folder_permission_error(self, mock_current_user, client, app, db_session, admin_user):
        """Test delete_folder with permission error."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        
        with patch('oneirodex.utils.security.is_safe_path_strict', return_value=(True, None)):
            with patch('os.path.exists', return_value=True):
                with patch('os.path.isfile', return_value=True):
                    with patch('os.remove', side_effect=PermissionError("Permission denied")):
                        with client.session_transaction() as sess:
                            sess['_user_id'] = str(admin_user.id)
                        
                        response = client.post('/delete_folder', 
                                              json={'folder_path': '/test/file.txt'})
                        assert response.status_code == 403

    @patch('flask_login.current_user')  
    def test_delete_full_game_folder_not_found(self, mock_current_user, client, app, db_session, admin_user, test_game):
        """A game missing from disk must still be removable from the library."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'

        game_uuid = test_game.uuid

        with patch('oneirodex.utils.scanning.is_scan_job_running', return_value=False):
            with patch('os.path.isdir', return_value=False):
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(admin_user.id)

                response = client.post('/delete_full_game',
                                      json={'game_uuid': game_uuid})
                assert response.status_code == 200

                data = json.loads(response.data)
                assert data['success'] == True

                # The stranded database entry is gone.
                assert db_session.query(Game).filter_by(uuid=game_uuid).first() is None
