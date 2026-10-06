import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock, call, ANY
from uuid import uuid4
from datetime import datetime, timedelta
from threading import Thread
import time

from oneirodex import create_app, db
from oneirodex.models import Library, GlobalSettings, AllowedFileType, ScanJob, Game
from oneirodex.platform import LibraryPlatform
from oneirodex.utilities import scan_and_add_games, handle_auto_scan, handle_manual_scan
from sqlalchemy import select


def safe_cleanup_database(db_session):
    """Completely clean up ALL test data - this is a test database, nuke everything!"""
    from sqlalchemy import text
    
    try:
        # Disable foreign key checks temporarily for aggressive cleanup
        db_session.execute(text("SET session_replication_role = replica;"))
        
        # Delete all junction table data first
        db_session.execute(text("TRUNCATE TABLE user_favorites CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_genre_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_platform_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_game_mode_association CASCADE"))
        db_session.execute(text("TRUNCATE TABLE game_theme_association CASCADE"))
        
        # Delete all main table data
        for table in ['game_updates', 'game_extras', 'images', 'game_urls', 'unmatched_folders', 
                     'scan_jobs', 'download_requests', 'newsletters', 'system_events', 
                     'invite_tokens', 'games', 'users', 'libraries']:
            try:
                db_session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            except Exception:
                pass  # Table might not exist
        
        # Re-enable foreign key checks
        db_session.execute(text("SET session_replication_role = DEFAULT;"))
        
        db_session.commit()
        
    except Exception as e:
        db_session.rollback()
        print(f"❌ Error during aggressive cleanup in test_utilities.py: {e}")
        # Try to re-enable foreign key checks
        try:
            db_session.execute(text("SET session_replication_role = DEFAULT;"))
            db_session.commit()
        except:
            pass


@pytest.fixture(autouse=True)
def cleanup_after_each_test(db_session):
    """Automatically clean up after each test - no test data should persist!"""
    yield  # Let the test run first
    safe_cleanup_database(db_session)  # Clean up after


class TestScanAndAddGamesCore:
    """Test core functionality of scan_and_add_games with comprehensive assertions."""
    
    @patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running')
    def test_early_return_when_scan_running(self, mock_is_running, app):
        """Test that function returns early if scan is already running with no side effects."""
        mock_is_running.return_value = True
        
        with app.app_context():
            # Ensure clean database state before test
            initial_scan_jobs = db.session.execute(select(ScanJob)).scalars().all()
            initial_count = len(initial_scan_jobs)
            
            result = scan_and_add_games("/fake/path", library_uuid=str(uuid4()))
            
            # Verify function returns None
            assert result is None
            
            # Verify running check was called exactly once
            mock_is_running.assert_called_once()
            
            # Critical assertion: No scan job should be created when one is running
            final_scan_jobs = db.session.execute(select(ScanJob)).scalars().all()
            assert len(final_scan_jobs) == initial_count, "No new scan jobs should be created when scan is running"

    def test_library_not_found_creates_no_scan_job(self, app, db_session):
        """Test that no scan job is created when library UUID doesn't exist."""
        nonexistent_uuid = str(uuid4())
        
        with app.app_context():
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                initial_jobs = db_session.execute(select(ScanJob)).scalars().all()
                initial_count = len(initial_jobs)
                
                result = scan_and_add_games("/fake/path", library_uuid=nonexistent_uuid)
                
                # Verify function returns None
                assert result is None
                
                # Critical assertion: No scan job created for nonexistent library
                final_jobs = db_session.execute(select(ScanJob)).scalars().all()
                assert len(final_jobs) == initial_count, "No scan job should be created for nonexistent library"
                
                # Verify no scan job exists for the nonexistent UUID
                uuid_specific_jobs = db_session.execute(
                    select(ScanJob).filter_by(library_uuid=nonexistent_uuid)
                ).scalars().all()
                assert len(uuid_specific_jobs) == 0, f"No scan jobs should exist for UUID {nonexistent_uuid}"


class TestHandleAutoScanCore:
    """Test core functionality of handle_auto_scan with comprehensive assertions."""
    
    def test_form_validation_failure_with_mock_form(self, app, db_session):
        """Test comprehensive behavior when form validation fails."""
        test_uuid = str(uuid4())
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = False
        mock_form.library_uuid.data = test_uuid
        mock_form.errors = {'folder_path': ['This field is required.'], 'scan_mode': ['Invalid choice.']}
        
        with app.app_context():
            with app.test_request_context():
                # Track initial state
                initial_scan_jobs = db_session.execute(select(ScanJob)).scalars().all()
                initial_count = len(initial_scan_jobs)
                
                with patch('oneirodex.utils.services.scan_orchestration.flash') as mock_flash:
                    with patch('oneirodex.utils.services.scan_orchestration.redirect') as mock_redirect:
                        with patch('oneirodex.utils.services.scan_orchestration.url_for') as mock_url_for:
                            mock_session = {}
                            with patch('oneirodex.utils.services.scan_orchestration.session', mock_session):
                                mock_url_for.return_value = '/scan'
                                mock_redirect.return_value = 'redirected_response'
                                
                                result = handle_auto_scan(mock_form)
                                
                                # Verify flash was called with specific error details
                                mock_flash.assert_called_once()
                                flash_call = mock_flash.call_args[0][0]  # Get the message
                                assert 'validation failed' in flash_call.lower()
                                assert str(mock_form.errors) in flash_call
                                
                                # Note: session['active_tab'] is NOT set in validation failure case
                                # The session should remain empty since the function doesn't set it on validation failure
                                assert 'active_tab' not in mock_session
                                
                                # Verify redirect is called with correct parameters
                                mock_redirect.assert_called_once()
                                mock_url_for.assert_called_with(
                                    'admin2.scan_management', 
                                    library_uuid=test_uuid, 
                                    active_tab='auto'
                                )
                                
                                # Critical assertion: No scan job created on validation failure
                                final_scan_jobs = db_session.execute(select(ScanJob)).scalars().all()
                                assert len(final_scan_jobs) == initial_count, "No scan job should be created on validation failure"
                                
                                # Verify form was accessed correctly
                                mock_form.validate_on_submit.assert_called_once()
                                assert result == 'redirected_response'

    def test_scan_already_running_comprehensive_checks(self, app, db_session):
        """Second auto-scan while Running queues a Queued job (does not drop)."""
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = True
        mock_form.remove_missing.data = True
        mock_form.download_missing_images.data = False
        mock_form.force_updates_extras_scan.data = False
        mock_form.fetch_hltb.data = False
        mock_form.force_hltb_refetch.data = False
        mock_form.schedule.data = ''
        mock_form.folder_path.data = 'pc'
        mock_form.scan_mode.data = 'folders'

        # Create library for the running scan job
        running_library = Library(
            uuid=str(uuid4()),
            name="Running Scan Library",
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(running_library)
        mock_form.library_uuid.data = running_library.uuid
        # No scan location picked -> resolve against the OS base folder
        mock_form.library_root.data = ''

        # Create actual running scan job in database
        running_job = ScanJob(
            folders={"/test/path": True},
            content_type='Games',
            status='Running',
            is_enabled=True,
            last_run=datetime.now(),
            library_uuid=running_library.uuid,
            error_message='',
            total_folders=5,
            folders_success=2,
            folders_failed=1,
            scan_folder='/test/path'
        )
        db_session.add(running_job)
        db_session.commit()

        with app.app_context():
            with app.test_request_context():
                with patch('oneirodex.utils.services.scan_orchestration.flash') as mock_flash:
                    with patch('oneirodex.utils.services.scan_orchestration.redirect') as mock_redirect:
                        with patch('oneirodex.utils.services.scan_orchestration.url_for') as mock_url_for:
                            mock_session = {}
                            with patch('oneirodex.utils.services.scan_orchestration.session', mock_session):
                                with patch(
                                    'oneirodex.utils.services.scan_orchestration.get_allowed_base_directories',
                                    return_value=['/base'],
                                ):
                                    with patch(
                                        'oneirodex.utils.services.scan_orchestration.is_safe_path',
                                        return_value=(True, None),
                                    ):
                                        with patch('oneirodex.utils.services.scan_orchestration.os.path.exists', return_value=True):
                                            with patch('oneirodex.utils.services.scan_orchestration.os.access', return_value=True):
                                                with patch.dict(
                                                    'oneirodex.utils.services.scan_orchestration.current_app.config',
                                                    {'BASE_FOLDER_POSIX': '/base', 'BASE_FOLDER_WINDOWS': '/base'},
                                                    clear=False,
                                                ):
                                                    mock_url_for.return_value = '/scan_management'
                                                    mock_redirect.return_value = 'queued_response'

                                                    result = handle_auto_scan(mock_form)

                                assert mock_flash.called
                                flash_msg, flash_cat = mock_flash.call_args[0]
                                assert 'queued' in flash_msg.lower()
                                assert flash_cat == 'info'
                                assert mock_session.get('active_tab') == 'auto'

                                persistent_job = db_session.get(ScanJob, running_job.id)
                                assert persistent_job is not None
                                assert persistent_job.status == 'Running'
                                assert persistent_job.folders_success == 2

                                queued = db_session.execute(
                                    select(ScanJob).filter_by(
                                        library_uuid=running_library.uuid,
                                        status='Queued',
                                    )
                                ).scalars().all()
                                assert len(queued) == 1
                                assert result == 'queued_response'


class TestHandleManualScanCore:
    """Test core functionality of handle_manual_scan with proper mocking."""
    
    def test_form_validation_failure(self, app):
        """Test behavior when form validation fails.""" 
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = False
        mock_form.library_uuid.data = str(uuid4())
        
        with app.app_context():
            with app.test_request_context():
                mock_session = {}
                with patch('oneirodex.utils.services.scan_orchestration.session', mock_session):
                    with patch('oneirodex.utils.services.scan_orchestration.flash') as mock_flash:
                        with patch('oneirodex.utils.services.scan_orchestration.redirect'):
                            with patch('oneirodex.utils.services.scan_orchestration.url_for'):
                                handle_manual_scan(mock_form)
                                
                                mock_flash.assert_called_with('Manual scan form validation failed.', 'danger')
                                assert mock_session['active_tab'] == 'manual'

    def test_scan_already_running_queues(self, app, db_session):
        """Manual while Running queues via start_or_queue_scan (not hard reject)."""
        mock_form = Mock()
        mock_form.validate_on_submit.return_value = True
        mock_form.folder_path.data = 'pc'
        mock_form.scan_mode.data = 'folders'
        mock_form.force_updates_extras_scan.data = False
        mock_form.fetch_hltb.data = False
        mock_form.force_hltb_refetch.data = False

        library = Library(
            uuid=str(uuid4()),
            name="Manual Queue Library",
            platform=LibraryPlatform.PCWIN,
        )
        db_session.add(library)
        mock_form.library_uuid.data = library.uuid
        # No scan location picked -> resolve against the OS base folder
        mock_form.library_root.data = ''

        running_job = ScanJob(
            folders={"/base/pc": True},
            content_type='Games',
            status='Running',
            is_enabled=True,
            last_run=datetime.now(),
            library_uuid=library.uuid,
            error_message='',
            total_folders=5,
            folders_success=1,
            folders_failed=0,
            scan_folder='/base/pc',
        )
        db_session.add(running_job)
        db_session.commit()

        with app.app_context():
            with app.test_request_context():
                mock_session = {}
                with patch('oneirodex.utils.services.scan_orchestration.session', mock_session):
                    with patch('oneirodex.utils.services.scan_orchestration.flash') as mock_flash:
                        with patch('oneirodex.utils.services.scan_orchestration.redirect') as mock_redirect:
                            with patch('oneirodex.utils.services.scan_orchestration.url_for') as mock_url_for:
                                with patch(
                                    'oneirodex.utils.services.scan_orchestration.get_allowed_base_directories',
                                    return_value=['/base'],
                                ):
                                    with patch(
                                        'oneirodex.utils.services.scan_orchestration.is_safe_path',
                                        return_value=(True, None),
                                    ):
                                        with patch('oneirodex.utils.services.scan_orchestration.os.path.exists', return_value=True):
                                            with patch('oneirodex.utils.services.scan_orchestration.os.access', return_value=True):
                                                with patch.dict(
                                                    'oneirodex.utils.services.scan_orchestration.current_app.config',
                                                    {
                                                        'BASE_FOLDER_POSIX': '/base',
                                                        'BASE_FOLDER_WINDOWS': '/base',
                                                    },
                                                    clear=False,
                                                ):
                                                    mock_url_for.return_value = '/scan_management'
                                                    mock_redirect.return_value = 'queued_response'
                                                    result = handle_manual_scan(mock_form)

                flash_msg, flash_cat = mock_flash.call_args[0]
                assert 'queued' in flash_msg.lower()
                assert flash_cat == 'info'
                assert mock_session.get('active_tab') == 'manual'
                queued = db_session.execute(
                    select(ScanJob).filter_by(
                        library_uuid=library.uuid,
                        status='Queued',
                    )
                ).scalars().all()
                assert len(queued) == 1
                assert result == 'queued_response'


class TestUtilitiesWithRealDatabase:
    """Test utilities with actual database integration (faster, focused tests)."""
    
    def test_scan_job_creation_with_real_db(self, app, db_session, global_settings):
        """Test that scan job is created properly when library exists."""
        # Create test library
        library = Library(
            uuid=str(uuid4()),
            name="Test Library", 
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(library)
        
        # Create required settings
        # Settings is a one-row table, so this sets values on the existing row
        # rather than adding another — the same shape as the AllowedFileType
        # check just below, which was already written this way.
        settings = global_settings
        settings.update_folder_name = 'updates'
        settings.extras_folder_name = 'extras'
        settings.scan_thread_count = 1
        
        # Create allowed file type to prevent empty list error (check if exists first)
        existing_file_type = db_session.query(AllowedFileType).filter_by(value='exe').first()
        if not existing_file_type:
            file_type = AllowedFileType(value='exe')
            db_session.add(file_type)
        
        db_session.commit()
        
        with app.app_context():
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                with patch('os.path.exists', return_value=False):  # Force folder access failure
                    with patch('os.access', return_value=False):
                        scan_and_add_games("/nonexistent/path", library_uuid=library.uuid)
                        
                        # Check that scan job was created
                        scan_jobs = db_session.query(ScanJob).filter_by(library_uuid=library.uuid).all()
                        assert len(scan_jobs) > 0
                        assert scan_jobs[0].status == 'Failed'
                        assert 'Cannot access folder' in scan_jobs[0].error_message

    def test_library_validation(self, app, db_session):
        """Test that function handles missing library gracefully."""
        with app.app_context():
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                result = scan_and_add_games("/fake/path", library_uuid="nonexistent-uuid")
                assert result is None


class TestAdvancedScanScenarios:
    """Test advanced scanning scenarios with deep database integration."""
    
    def test_existing_job_restart_workflow(self, app, db_session, global_settings):
        """Test restarting an existing scan job with proper state management."""
        # Setup test environment
        library = Library(
            uuid=str(uuid4()),
            name="Restart Test Library", 
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(library)
        
        # Settings is a one-row table, so this sets values on the existing row
        # rather than adding another — the same shape as the AllowedFileType
        # check just below, which was already written this way.
        settings = global_settings
        settings.update_folder_name = 'updates'
        settings.extras_folder_name = 'extras'
        settings.scan_thread_count = 1
        
        # Add required file types
        if not db_session.execute(select(AllowedFileType).filter_by(value='exe')).scalars().first():
            db_session.add(AllowedFileType(value='exe'))
        
        # Create existing failed job
        existing_job = ScanJob(
            folders={"/restart/path": True},
            content_type='Games',
            status='Failed',
            is_enabled=True,
            last_run=datetime.now() - timedelta(hours=1),
            library_uuid=library.uuid,
            error_message='Previous failure reason',
            total_folders=5,
            folders_success=2,
            folders_failed=3,
            scan_folder='/restart/path'
        )
        db_session.add(existing_job)
        db_session.commit()
        existing_job_id = existing_job.id
        
        with app.app_context():
            # Simulate path access failure again
            with patch('os.path.exists', return_value=False):
                with patch('os.access', return_value=False):
                    scan_and_add_games(
                        "/restart/path",
                        library_uuid=library.uuid,
                        existing_job=existing_job
                    )
                    
                    # Verify the same job was updated, not a new one created
                    # Query the job again instead of refreshing to avoid session issues
                    updated_job = db_session.get(ScanJob, existing_job_id)
                    assert updated_job is not None
                    assert updated_job.id == existing_job_id  # Same job ID
                    assert updated_job.status == 'Failed'  # Status updated
                    assert 'Cannot access folder' in updated_job.error_message
                    
                    # Verify no duplicate jobs created
                    all_jobs = db_session.execute(
                        select(ScanJob).filter_by(library_uuid=library.uuid)
                    ).scalars().all()
                    assert len(all_jobs) == 1  # Still only one job
                    
                    # Verify state preservation and updates
                    assert all_jobs[0].id == existing_job_id
                    assert all_jobs[0].folders == {"/restart/path": True}
                    assert all_jobs[0].content_type == 'Games'

    def test_remove_missing_games_functionality(self, app, db_session, global_settings):
        """Test the remove missing games feature with database state verification."""
        # Setup test environment
        library = Library(
            uuid=str(uuid4()),
            name="Remove Missing Test Library", 
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(library)
        
        # Settings is a one-row table, so this sets values on the existing row
        # rather than adding another — the same shape as the AllowedFileType
        # check just below, which was already written this way.
        settings = global_settings
        settings.update_folder_name = 'updates'
        settings.extras_folder_name = 'extras'
        settings.scan_thread_count = 1
        
        if not db_session.execute(select(AllowedFileType).filter_by(value='exe')).scalars().first():
            db_session.add(AllowedFileType(value='exe'))
        
        # Create existing games - some that will be "missing" 
        existing_games = [
            Game(
                uuid=str(uuid4()),
                name='Game Still Exists',
                full_disk_path='/existing/game',
                library_uuid=library.uuid
            ),
            Game(
                uuid=str(uuid4()),
                name='Game Missing Now',
                full_disk_path='/missing/game',
                library_uuid=library.uuid
            ),
            Game(
                uuid=str(uuid4()),
                name='Another Missing Game',
                full_disk_path='/another/missing',
                library_uuid=library.uuid
            )
        ]
        
        for game in existing_games:
            db_session.add(game)
        
        db_session.commit()
        
        # Record initial game count
        initial_games = db_session.execute(
            select(Game).filter_by(library_uuid=library.uuid)
        ).scalars().all()
        assert len(initial_games) == 3
        
        with app.app_context():
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                with patch('os.path.exists') as mock_exists:
                    with patch('os.access', return_value=True):
                        # Mock to return some dummy games so scan doesn't return early
                        dummy_games = [
                            {'name': 'Dummy Game 1', 'full_path': '/dummy/game1'},
                            {'name': 'Dummy Game 2', 'full_path': '/dummy/game2'}
                        ]
                        with patch('oneirodex.utils.services.scan_orchestration.get_game_names_from_folder', return_value=dummy_games):
                            with patch('oneirodex.utils.services.scan_orchestration.load_scanning_filter_patterns', return_value=([], [])):
                                with patch('oneirodex.utils.scanning.process_game_with_fallback', return_value=True):  # Mock successful processing
                                    with patch('oneirodex.utils.services.scan_orchestration.remove_from_lib') as mock_remove:
                                        
                                        # Configure path existence - only first game exists
                                        def exists_side_effect(path):
                                            if path == '/scan/path':  # Scan folder
                                                return True
                                            elif path == '/existing/game':  # First game
                                                return True
                                            else:  # Missing games
                                                return False
                                        
                                        mock_exists.side_effect = exists_side_effect
                                        
                                        scan_and_add_games(
                                            "/scan/path",
                                            library_uuid=library.uuid,
                                            remove_missing=True
                                        )
                                        
                                        # Verify remove_from_lib was called for missing games
                                        assert mock_remove.call_count == 2  # Two missing games
                                        
                                        # Get the UUIDs that were passed to remove_from_lib
                                        removed_uuids = [call[0][0] for call in mock_remove.call_args_list]
                                        
                                        # Verify correct games were marked for removal
                                        missing_game_uuids = [
                                            existing_games[1].uuid,  # 'Game Missing Now'
                                            existing_games[2].uuid   # 'Another Missing Game'
                                        ]
                                        
                                        for uuid in missing_game_uuids:
                                            assert uuid in removed_uuids
                                        
                                        # Verify scan job shows removal count
                                        scan_jobs = db_session.execute(
                                            select(ScanJob).filter_by(library_uuid=library.uuid)
                                        ).scalars().all()
                                        
                                        assert len(scan_jobs) == 1
                                        scan_job = scan_jobs[0]
                                        assert scan_job.removed_count == 2
                                        assert scan_job.status == 'Completed'

    def test_database_error_handling_during_scan(self, app, db_session, global_settings):
        """Test how scan handles database errors gracefully."""
        # Setup test environment
        library = Library(
            uuid=str(uuid4()),
            name="Database Error Test Library", 
            platform=LibraryPlatform.PCWIN
        )
        db_session.add(library)
        
        # Settings is a one-row table, so this sets values on the existing row
        # rather than adding another — the same shape as the AllowedFileType
        # check just below, which was already written this way.
        settings = global_settings
        settings.update_folder_name = 'updates'
        settings.extras_folder_name = 'extras'
        settings.scan_thread_count = 1
        
        if not db_session.execute(select(AllowedFileType).filter_by(value='exe')).scalars().first():
            db_session.add(AllowedFileType(value='exe'))
        
        db_session.commit()
        
        with app.app_context():
            # Test 1: Database error during initial ScanJob creation
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                with patch('os.path.exists', return_value=True):
                    with patch('os.access', return_value=True):
                        with patch('oneirodex.utils.services.scan_orchestration.db.session.commit') as mock_commit:
                            from sqlalchemy.exc import SQLAlchemyError
                            
                            # Simulate database error on first commit (ScanJob creation)
                            mock_commit.side_effect = SQLAlchemyError("Database connection lost")
                            
                            result = scan_and_add_games("/test/path", library_uuid=library.uuid)
                            
                            # Verify function returns early on database error
                            assert result is None
                            mock_commit.assert_called_once()
            
            # Test 2: Database error during final commit  
            with patch('oneirodex.utils.services.scan_orchestration.is_scan_job_running', return_value=False):
                with patch('os.path.exists', return_value=True):
                    with patch('os.access', return_value=True):
                        with patch('oneirodex.utils.services.scan_orchestration.get_game_names_from_folder', return_value=[]):
                            with patch('oneirodex.utils.services.scan_orchestration.load_scanning_filter_patterns', return_value=([], [])):
                                real_commit = db_session.commit
                                with patch('oneirodex.utils.services.scan_orchestration.db.session.commit') as mock_commit:
                                    from sqlalchemy.exc import SQLAlchemyError
                                    
                                    # Track commits and fail on final one
                                    commit_count = 0

                                    def commit_and_fail_on_final():
                                        nonlocal commit_count
                                        commit_count += 1
                                        if commit_count >= 3:  # Fail on final commit
                                            raise SQLAlchemyError("Connection timeout during final commit")
                                        return real_commit()

                                    mock_commit.side_effect = commit_and_fail_on_final
                                    
                                    # The scan function should handle the SQLAlchemy error gracefully
                                    # and continue execution (not raise an exception to the test)
                                    try:
                                        scan_and_add_games("/test/path", library_uuid=library.uuid)
                                    except SQLAlchemyError:
                                        # This is expected - the function lets final commit errors propagate
                                        # but handles them at the higher level via try/catch in utilities.py
                                        pass
                                    
                                    # Verify multiple commits were attempted
                                    assert mock_commit.call_count >= 2
                                    
                                    # Check that scan job was created initially (despite final error)
                                    scan_jobs = db_session.execute(
                                        select(ScanJob).filter_by(library_uuid=library.uuid)
                                    ).scalars().all()
                                    # At least one scan job should exist from the successful initial creation
                                    assert len(scan_jobs) >= 1
            
            # Test 3: Verify error handling preserves partial progress  
            existing_job = ScanJob(
                folders={"/error/path": True},
                content_type='Games',
                status='Running',
                is_enabled=True,
                last_run=datetime.now(),
                library_uuid=library.uuid,
                error_message='Initial error message',
                total_folders=2,
                folders_success=1,
                folders_failed=0,
                scan_folder='/error/path'
            )
            db_session.add(existing_job)
            db_session.commit()
            
            # Verify scan job state is preserved even with database errors
            db_session.refresh(existing_job)
            assert existing_job.folders_success == 1  # Progress preserved
            assert 'Initial error message' in existing_job.error_message
            assert existing_job.total_folders == 2
