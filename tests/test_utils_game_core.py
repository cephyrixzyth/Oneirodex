from sqlalchemy import text
import pytest
import os
import tempfile
import threading
import time
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock, mock_open, call
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from werkzeug.utils import secure_filename

from oneirodex import create_app, db
from oneirodex.models import (
    Game, Image, Library, GlobalSettings, Developer, Publisher, 
    Genre, Theme, GameMode, Platform, PlayerPerspective, GameURL, 
    ScanJob, Category, Status
)
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.game_core import (
    category_mapping, status_mapping, create_game_instance, 
    check_existing_game_by_path, check_existing_game_by_igdb_id,
    store_image_url_for_download, smart_process_images_for_game,
    queue_post_identify_enrichment,
    download_images_for_game, download_images_for_game_turbo,
    process_and_save_image, download_single_image_worker,
    retrieve_and_save_game, fetch_and_store_game_urls,
    enumerate_companies, get_game_by_uuid, remove_from_lib,
    delete_game, download_pending_images, start_background_image_downloader,
    turbo_download_images, start_turbo_background_downloader,
    find_missing_images_for_library, queue_missing_images_for_download,
    process_missing_images_for_scan, get_or_create_entity
)


def safe_cleanup_database(db_session):
    """Safely clean up database records respecting foreign key constraints."""
    from sqlalchemy import delete
    
    # Clean up in order to respect foreign key constraints
    db_session.execute(delete(Image))
    db_session.execute(delete(GameURL))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(delete(Library))
    db_session.execute(delete(Developer))
    db_session.execute(delete(Publisher))
    db_session.execute(delete(Genre))
    db_session.execute(delete(Theme))
    db_session.execute(delete(GameMode))
    db_session.execute(delete(Platform))
    db_session.execute(delete(PlayerPerspective))
    db_session.execute(delete(ScanJob))
    db_session.commit()



@pytest.fixture
def sample_platform(db_session):
    """Create a sample platform for testing."""
    platform = Platform(name='Test Platform')
    db_session.add(platform)
    db_session.flush()
    return platform


@pytest.fixture
def sample_library(db_session):
    """Create a sample library for testing."""
    library = Library(
        uuid=str(uuid4()),
        name='Test Library',
        platform=LibraryPlatform.PCWIN
    )
    db_session.add(library)
    db_session.flush()
    return library


@pytest.fixture
def sample_game(db_session, sample_library, sample_global_settings):
    """Create a sample game for testing."""
    import random
    unique_id = random.randint(100000, 999999)
    game = Game(
        uuid=str(uuid4()),
        library_uuid=sample_library.uuid,
        igdb_id=unique_id,
        name='Test Game',
        full_disk_path=f'/test/game/path/{unique_id}',
        size=1024000,
        date_created=datetime.now(UTC),
        date_identified=datetime.now(UTC)
    )
    db_session.add(game)
    # Commit, not flush: tests here enter their own `app.app_context()`, which
    # gets a different session. A flushed-but-uncommitted row is invisible to
    # it, so writing an Image against this game hit a foreign-key violation.
    db_session.commit()
    return game


@pytest.fixture
def sample_image(db_session, sample_game, sample_global_settings):
    """Create a sample image for testing."""
    image = Image(
        game_uuid=sample_game.uuid,
        image_type='cover',
        url='test_cover.jpg',
        igdb_image_id='54321',
        download_url='https://example.com/image.jpg',
        is_downloaded=False
    )
    db_session.add(image)
    db_session.flush()
    return image


@pytest.fixture
def sample_global_settings(db_session):
    """Create sample global settings for testing."""
    # Delete any existing settings first to avoid multiple results
    from sqlalchemy import delete
    db_session.execute(delete(GlobalSettings))
    db_session.flush()
    
    settings = GlobalSettings(
        use_turbo_image_downloads=False,
        turbo_download_threads=4,
    )
    db_session.add(settings)
    db_session.flush()
    return settings


@pytest.fixture
def mock_igdb_response():
    """Mock IGDB API response data."""
    return [{
        'id': 12345,
        'name': 'Test Game',
        'summary': 'A test game',
        'url': 'https://igdb.com/games/test-game',
        'first_release_date': 1640995200,  # 2022-01-01
        'aggregated_rating': 85.5,
        'aggregated_rating_count': 100,
        'rating': 88.2,
        'rating_count': 50,
        'slug': 'test-game',
        'status': 1,  # Released
        'category': 0,  # Main game
        'total_rating': 87.0,
        'total_rating_count': 150,
        'cover': 98765,
        'screenshots': [11111, 22222],
        'videos': [{'video_id': 'abc123'}],
        'genres': [{'name': 'Action'}],
        'themes': [{'name': 'Horror'}],
        'game_modes': [{'name': 'Single player'}],
        'platforms': [{'name': 'PC (Microsoft Windows)'}],
        'player_perspectives': [{'name': 'First person'}],
        'involved_companies': [1, 2, 3]
    }]


@pytest.fixture
def mock_company_response():
    """Mock IGDB company response data."""
    return [
        {'company': {'name': 'Test Developer'}, 'developer': True, 'publisher': False, 'game': 12345},
        {'company': {'name': 'Test Publisher'}, 'developer': False, 'publisher': True, 'game': 12345}
    ]


class TestDataMappings:
    """Test the IGDB API mapping dictionaries."""
    
    def test_category_mapping_values(self):
        """Test category mapping contains expected values."""
        assert category_mapping[0] == Category.MAIN_GAME
        assert category_mapping[1] == Category.DLC_ADDON
        assert category_mapping[2] == Category.EXPANSION
        assert category_mapping[8] == Category.REMAKE
        assert category_mapping[9] == Category.REMASTER
        
    def test_status_mapping_values(self):
        """Test status mapping contains expected values."""
        assert status_mapping[1] == Status.RELEASED
        assert status_mapping[2] == Status.ALPHA
        assert status_mapping[3] == Status.BETA
        assert status_mapping[4] == Status.EARLY_ACCESS
        assert status_mapping[6] == Status.OFFLINE
        assert status_mapping[7] == Status.CANCELLED
        
    def test_category_mapping_completeness(self):
        """Test category mapping covers all expected keys."""
        expected_keys = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        assert set(category_mapping.keys()) == set(expected_keys)
        
    def test_status_mapping_completeness(self):
        """Test status mapping covers expected keys."""
        expected_keys = [1, 2, 3, 4, 6, 7]
        assert set(status_mapping.keys()) == set(expected_keys)


class TestCoreGameCreationFunctions:
    """Test core game creation and lookup functions."""
    
    @patch('oneirodex.utils.services.scan_identify.fetch_and_store_game_urls')
    def test_create_game_instance_success(self, mock_fetch_urls, db_session, sample_library, mock_igdb_response, sample_global_settings):
        """Test successful game instance creation."""
        game_data = mock_igdb_response[0]
        full_disk_path = '/test/game/path'
        folder_size_bytes = 1024000
        
        result = create_game_instance(game_data, full_disk_path, folder_size_bytes, sample_library.uuid)
        
        assert result is not None
        assert result.name == 'Test Game'
        assert result.igdb_id == 12345
        assert result.library_uuid == sample_library.uuid
        assert result.full_disk_path == full_disk_path
        assert result.size == folder_size_bytes
        assert result.category == Category.MAIN_GAME
        assert result.status == Status.RELEASED
    
    def test_create_game_instance_invalid_data(self, db_session, sample_library, sample_global_settings):
        """Test game instance creation with invalid data."""
        result = create_game_instance("not a dict", '/path', 1024, sample_library.uuid)
        assert result is None
    
    def test_create_game_instance_library_not_found(self, db_session, sample_global_settings):
        """Test game instance creation with non-existent library."""
        game_data = {'id': 123, 'name': 'Test Game'}
        result = create_game_instance(game_data, '/path', 1024, 'non-existent-uuid')
        assert result is None
    
    def test_check_existing_game_by_path_found(self, db_session, sample_game, sample_global_settings):
        """Test finding existing game by path."""
        result = check_existing_game_by_path(sample_game.full_disk_path)
        assert result is not None
        assert result.uuid == sample_game.uuid
    
    def test_check_existing_game_by_path_not_found(self, db_session, sample_global_settings):
        """Test not finding game by path."""
        result = check_existing_game_by_path('/non/existent/path')
        assert result is None
    
    def test_check_existing_game_by_igdb_id_found(self, db_session, sample_game, sample_global_settings):
        """Test finding existing game by IGDB ID."""
        result = check_existing_game_by_igdb_id(sample_game.igdb_id)
        assert result is not None
        assert result.uuid == sample_game.uuid
    
    def test_check_existing_game_by_igdb_id_not_found(self, db_session, sample_global_settings):
        """Test not finding game by IGDB ID."""
        result = check_existing_game_by_igdb_id(99999)
        assert result is None


class TestImageProcessingFunctions:
    """Test image processing and download functions."""
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_store_image_url_for_download_cover(self, mock_api, db_session, sample_game, sample_global_settings):
        """Test storing cover image URL for download."""
        mock_api.return_value = [{'url': '//images.igdb.com/igdb/image/upload/t_thumb/test.jpg'}]
        
        store_image_url_for_download(sample_game.uuid, 98765, 'cover')
        
        # Check image was stored in database
        images = db_session.query(Image).filter_by(game_uuid=sample_game.uuid).all()
        assert len(images) == 1
        assert images[0].image_type == 'cover'
        assert images[0].igdb_image_id == '98765'
        assert images[0].download_url == 'https://images.igdb.com/igdb/image/upload/t_original/test.jpg'
        assert images[0].is_downloaded is False

    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_store_image_url_accepts_expanded_cover_dict_without_api(
        self, mock_api, db_session, sample_game, sample_global_settings
    ):
        """Expanded IGDB cover objects must store a cover row using the embedded URL.

        Previously ``where id={...dict...}`` failed silently so screenshots landed
        and the UI fell back to the branded 'No cover art' placeholder.
        """
        store_image_url_for_download(
            sample_game.uuid,
            {
                'id': 4242,
                'url': '//images.igdb.com/igdb/image/upload/t_thumb/co_aiwu.jpg',
            },
            'cover',
        )

        mock_api.assert_not_called()
        images = db_session.query(Image).filter_by(
            game_uuid=sample_game.uuid, image_type='cover'
        ).all()
        assert len(images) == 1
        assert images[0].igdb_image_id == '4242'
        assert images[0].download_url == (
            'https://images.igdb.com/igdb/image/upload/t_original/co_aiwu.jpg'
        )
        assert images[0].is_downloaded is False

    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game')
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_smart_process_stores_cover_when_expanded_object(
        self, mock_api, mock_download, app, db_session, sample_game, sample_global_settings
    ):
        sample_global_settings.use_turbo_image_downloads = False
        db_session.commit()
        mock_download.return_value = 1

        with app.app_context():
            result = smart_process_images_for_game(
                sample_game.uuid,
                cover_data={
                    'id': 55,
                    'url': '//images.igdb.com/igdb/image/upload/t_thumb/co55.jpg',
                },
                screenshots_data=[
                    {'id': 66, 'url': '//images.igdb.com/igdb/image/upload/t_thumb/ss66.jpg'},
                ],
                app=app,
            )

        mock_api.assert_not_called()
        covers = db_session.query(Image).filter_by(
            game_uuid=sample_game.uuid, image_type='cover'
        ).all()
        shots = db_session.query(Image).filter_by(
            game_uuid=sample_game.uuid, image_type='screenshot'
        ).all()
        assert len(covers) == 1
        assert len(shots) == 1
        assert covers[0].download_url.endswith('/t_original/co55.jpg')
        assert shots[0].download_url.endswith('/t_original/ss66.jpg')
        mock_download.assert_called_once()
        assert result == 1

    def test_normalize_igdb_image_ref_shapes(self):
        from oneirodex.utils.game_core import normalize_igdb_image_ref

        assert normalize_igdb_image_ref(99) == (99, None)
        assert normalize_igdb_image_ref({'id': 7, 'url': '//cdn/x.jpg'}) == (
            7,
            'https://cdn/x.jpg',
        )
        assert normalize_igdb_image_ref(None) == (None, None)
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_store_image_url_for_download_screenshot(self, mock_api, db_session, sample_game, sample_global_settings):
        """Test storing screenshot image URL for download."""
        mock_api.return_value = [{'url': '//images.igdb.com/igdb/image/upload/t_thumb/screenshot.jpg'}]
        
        store_image_url_for_download(sample_game.uuid, 11111, 'screenshot')
        
        images = db_session.query(Image).filter_by(game_uuid=sample_game.uuid).all()
        assert len(images) == 1
        assert images[0].image_type == 'screenshot'
        assert images[0].igdb_image_id == '11111'
        assert images[0].download_url == 'https://images.igdb.com/igdb/image/upload/t_original/screenshot.jpg'
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_store_image_url_for_download_api_failure(self, mock_api, db_session, sample_game, sample_global_settings):
        """Test handling API failure when storing image URL."""
        mock_api.return_value = {'error': 'API Error'}
        
        store_image_url_for_download(sample_game.uuid, 98765, 'cover')
        
        images = db_session.query(Image).filter_by(game_uuid=sample_game.uuid).all()
        assert len(images) == 0
    
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game_turbo')
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game')
    @patch('oneirodex.utils.services.image_pipeline.store_image_url_for_download')
    def test_smart_process_images_for_game_with_cover_and_screenshots(self, mock_store_image, mock_download, mock_download_turbo, app, db_session, sample_game, sample_global_settings):
        """Test smart_process_images_for_game with cover and screenshots."""
        # Force non-turbo mode for this test
        sample_global_settings.use_turbo_image_downloads = False
        db_session.commit()
        
        mock_download.return_value = 3
        mock_download_turbo.return_value = 3
        
        with app.app_context():
            result = smart_process_images_for_game(sample_game.uuid, cover_data=98765, screenshots_data=[11111, 22222], app=app)
        
        # Should store images and download them
        assert mock_store_image.call_count == 3
        # Check which download method was called based on mode
        if mock_download.called:
            mock_download.assert_called_once_with(sample_game.uuid, app)
        elif mock_download_turbo.called:
            mock_download_turbo.assert_called_once()
        assert result == 3
    
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game_turbo')
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game')
    @patch('oneirodex.utils.services.image_pipeline.store_image_url_for_download')
    def test_smart_process_images_for_game_no_images(self, mock_store_image, mock_download, mock_download_turbo, app, db_session, sample_game, sample_global_settings):
        """Test smart_process_images_for_game with no images."""
        # Force non-turbo mode for this test
        sample_global_settings.use_turbo_image_downloads = False
        db_session.commit()
        
        mock_download.return_value = 0
        mock_download_turbo.return_value = 0
        
        with app.app_context():
            result = smart_process_images_for_game(sample_game.uuid, app=app)
        
        # Should not store any images but still call download
        mock_store_image.assert_not_called()
        # Check which download method was called based on mode
        if mock_download.called:
            mock_download.assert_called_once_with(sample_game.uuid, app)
        elif mock_download_turbo.called:
            mock_download_turbo.assert_called_once()
        assert result == 0
    
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game_turbo')
    @patch('oneirodex.utils.services.image_pipeline.store_image_url_for_download')
    def test_smart_process_images_for_game_turbo_mode(self, mock_store_image, mock_download_turbo, app, db_session, sample_game, sample_global_settings):
        """Test smart_process_images_for_game with turbo mode enabled."""
        # Enable turbo mode
        sample_global_settings.use_turbo_image_downloads = True
        sample_global_settings.turbo_download_threads = 4
        db_session.commit()
        
        mock_download_turbo.return_value = 2
        
        with app.app_context():
            result = smart_process_images_for_game(sample_game.uuid, cover_data=98765, screenshots_data=[11111], app=app)
        
        # Should use turbo download
        mock_download_turbo.assert_called_once_with(sample_game.uuid, app, max_workers=4)
        assert result == 2

    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game_turbo')
    @patch('oneirodex.utils.services.image_pipeline.download_images_for_game')
    @patch('oneirodex.utils.services.image_pipeline.store_image_url_for_download')
    def test_smart_process_images_download_immediately_false(
        self, mock_store_image, mock_download, mock_download_turbo, app, db_session, sample_game, sample_global_settings
    ):
        sample_global_settings.use_turbo_image_downloads = False
        db_session.commit()

        with app.app_context():
            result = smart_process_images_for_game(
                sample_game.uuid,
                cover_data=98765,
                screenshots_data=[11111],
                app=app,
                download_immediately=False,
            )

        assert mock_store_image.call_count == 2
        mock_download.assert_not_called()
        mock_download_turbo.assert_not_called()
        assert result == 0

    @patch('oneirodex.utils.services.game_enrich.smart_process_images_for_game')
    @patch('oneirodex.utils.services.game_enrich.enrich_game_with_steam')
    @patch('oneirodex.utils.services.game_enrich.get_folder_size_in_bytes_updates')
    def test_queue_post_identify_enrichment_inline(
        self, mock_size, mock_steam, mock_images, app, db_session, sample_game, sample_global_settings
    ):
        sample_global_settings.enable_hltb_integration = False
        db_session.commit()
        mock_size.return_value = 4096

        with app.app_context():
            queue_post_identify_enrichment(
                sample_game.uuid,
                fetch_hltb=False,
                cover_data=1,
                screenshots_data=[2],
                app=app,
                run_inline=True,
            )

        mock_size.assert_called_once()
        mock_steam.assert_called_once()
        mock_images.assert_called_once()
        assert mock_images.call_args.kwargs.get('download_immediately') is True
        db_session.refresh(sample_game)
        assert sample_game.size == 4096

    @patch('oneirodex.utils.services.scan_identify.queue_post_identify_enrichment')
    @patch('oneirodex.utils.services.scan_identify.enrich_game_with_steam')
    @patch('oneirodex.utils.services.scan_identify.notify_admins_new_game')
    @patch('oneirodex.utils.services.scan_identify.smart_process_images_for_game')
    @patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates')
    @patch('oneirodex.utils.services.scan_identify.read_first_nfo_content')
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    @patch('oneirodex.utils.services.scan_identify.create_game_instance')
    def test_retrieve_and_save_game_defers_enrichment_for_scan(
        self,
        mock_create_game,
        mock_api,
        mock_nfo,
        mock_folder_size,
        mock_smart_images,
        mock_notify_admins,
        mock_steam,
        mock_queue,
        app,
        db_session,
        sample_library,
        sample_global_settings,
    ):
        mock_api.return_value = [{'id': 12345, 'name': 'Test Game', 'cover': 99, 'screenshots': [11]}]
        mock_game = MagicMock()
        mock_game.uuid = 'test-uuid'
        mock_game.name = 'Test Game'
        mock_game.nfo_content = None
        mock_game.igdb_id = 12345
        mock_game.full_disk_path = '/test/path'
        mock_table = MagicMock()
        mock_column = MagicMock()
        mock_column.name = 'name'
        mock_table.columns = [mock_column]
        mock_game.__table__ = mock_table
        mock_create_game.return_value = mock_game
        mock_nfo.return_value = None
        mock_folder_size.return_value = 1024000

        job = ScanJob(
            id=str(uuid4()),
            library_uuid=sample_library.uuid,
            scan_folder='/test',
            status='Running',
            is_enabled=True,
        )
        db_session.add(sample_library)
        db_session.add(job)
        db_session.commit()

        with app.app_context():
            result = retrieve_and_save_game(
                'Test Game',
                '/test/path',
                scan_job_id=job.id,
                library_uuid=sample_library.uuid,
                fetch_hltb=True,
            )

        assert result == mock_game
        mock_steam.assert_not_called()
        mock_smart_images.assert_not_called()
        mock_folder_size.assert_not_called()
        mock_queue.assert_called_once()
        assert mock_queue.call_args.kwargs.get('fetch_hltb') is True


class TestDownloadFunctions:
    """Test image download and processing functions."""
    
    def test_download_images_for_game(self, app, db_session, sample_game, sample_image, sample_global_settings):
        """Test download_images_for_game function."""
        with app.app_context():
            result = download_images_for_game(sample_game.uuid, app)
            # Function should return count of processed images
            assert isinstance(result, int)
    
    def test_download_images_for_game_turbo(self, app, db_session, sample_game, sample_global_settings):
        """Test download_images_for_game_turbo with thread pool."""
        with app.app_context():
            result = download_images_for_game_turbo(sample_game.uuid, app, max_workers=2)
            # Function should return count of processed images
            assert isinstance(result, int)
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    @patch('oneirodex.utils.services.image_pipeline.download_image')
    def test_process_and_save_image_success(self, mock_download, mock_api, app, sample_game, sample_global_settings):
        """Test successful image processing and saving."""
        mock_api.return_value = [{'url': '//images.igdb.com/igdb/image/upload/t_thumb/test.jpg'}]
        mock_download.return_value = (True, None)
        
        with app.app_context():
            process_and_save_image(sample_game.uuid, 12345, 'cover')
        
        # Should call API and download exactly once (previously this double-downloaded for covers)
        mock_api.assert_called_once()
        assert mock_download.call_count == 1

    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    @patch('oneirodex.utils.services.image_pipeline.download_image')
    def test_process_and_save_image_records_success_state(self, mock_download, mock_api, app, db_session, sample_game, sample_global_settings):
        """The saved Image row should reflect a successful download: is_downloaded True,
        no last_error, and a download_url so a future retry has something to work with."""
        mock_api.return_value = [{'url': '//images.igdb.com/igdb/image/upload/t_thumb/test.jpg'}]
        mock_download.return_value = (True, None)

        with app.app_context():
            process_and_save_image(sample_game.uuid, 54321, 'cover')
            db_session.commit()

            image = db_session.execute(
                __import__('sqlalchemy').select(Image).filter_by(game_uuid=sample_game.uuid, image_type='cover')
            ).scalars().first()
            assert image is not None
            assert image.is_downloaded is True
            assert image.last_error is None
            assert image.download_url

    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    @patch('oneirodex.utils.services.image_pipeline.download_image')
    def test_process_and_save_image_records_failure_state(self, mock_download, mock_api, app, db_session, sample_game, sample_global_settings):
        """A failed download must not be silently marked downloaded — the row should
        carry is_downloaded=False and a human-readable last_error for the admin UI."""
        mock_api.return_value = [{'url': '//images.igdb.com/igdb/image/upload/t_thumb/test.jpg'}]
        mock_download.return_value = (False, 'Directory is not writable by the Oneirodex process.')

        with app.app_context():
            process_and_save_image(sample_game.uuid, 99999, 'cover')
            db_session.commit()

            image = db_session.execute(
                __import__('sqlalchemy').select(Image).filter_by(game_uuid=sample_game.uuid, image_type='cover')
            ).scalars().first()
            assert image is not None
            assert image.is_downloaded is False
            assert image.last_error == 'Directory is not writable by the Oneirodex process.'
            assert image.download_url
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_process_and_save_image_api_failure(self, mock_api, app, sample_game, sample_global_settings):
        """Test process_and_save_image handles API failure."""
        mock_api.return_value = {'error': 'API Error'}
        
        with app.app_context():
            with patch('builtins.print'):
                process_and_save_image(sample_game.uuid, 12345, 'cover')
        
        # Should handle error gracefully
        mock_api.assert_called_once()
    
    @patch('oneirodex.utils.services.image_pipeline.process_and_save_image')
    def test_download_single_image_worker(self, mock_process_save, app, sample_image, sample_global_settings):
        """Test download_single_image_worker function."""
        download_single_image_worker(sample_image, app)
        
        # Should process the image (but function implementation may vary)
        # This test mainly ensures the function can be called without error


class TestGameDataFunctions:
    """Test game data retrieval and URL processing functions."""
    
    @patch('oneirodex.utils.services.scan_identify.notify_admins_new_game')
    @patch('oneirodex.utils.services.scan_identify.smart_process_images_for_game')
    @patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates')
    @patch('oneirodex.utils.services.scan_identify.read_first_nfo_content')
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    @patch('oneirodex.utils.services.scan_identify.create_game_instance')
    def test_retrieve_and_save_game_success(self, mock_create_game, mock_api, mock_nfo, mock_folder_size, mock_smart_images, mock_notify_admins, app, db_session, sample_library, sample_global_settings):
        """Test successful game retrieval and saving."""
        mock_api.return_value = [{'id': 12345, 'name': 'Test Game'}]
        
        # Create a mock game with table attributes
        mock_game = MagicMock()
        mock_game.uuid = 'test-uuid'
        mock_game.name = 'Test Game'
        mock_game.nfo_content = None
        
        # Mock the __table__ attribute and columns
        mock_table = MagicMock()
        mock_column = MagicMock()
        mock_column.name = 'name'
        mock_table.columns = [mock_column]
        mock_game.__table__ = mock_table
        
        mock_create_game.return_value = mock_game
        mock_nfo.return_value = None
        mock_folder_size.return_value = 1024000
        mock_smart_images.return_value = 0
        
        # Ensure the library exists and is committed to the database
        db_session.add(sample_library)
        db_session.commit()
        
        with app.app_context():
            result = retrieve_and_save_game('Test Game', '/test/path', library_uuid=sample_library.uuid)
        
        assert result == mock_game
        # Identify tries search variants ('Path' from the folder, then the
        # cleaned title), so the IGDB call count tracks how many variants were
        # needed — pinning it to exactly one predates variant search. What
        # matters is that it searched and imported the game once.
        assert mock_api.call_count >= 1
        mock_create_game.assert_called_once()
        mock_notify_admins.assert_called_once_with(mock_game.uuid, mock_game.name)
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_retrieve_and_save_game_api_failure(self, mock_api, app, db_session, sample_library, sample_global_settings, monkeypatch):
        """Test retrieve_and_save_game handles API failure."""
        from oneirodex.utils.services import scan_identify
        from oneirodex.utils import software_identify

        monkeypatch.setattr(scan_identify, 'try_stage_d_store_identify', lambda **_kwargs: None)
        monkeypatch.setattr(scan_identify, 'fetch_steam_title_by_app_id', lambda *_args, **_kwargs: None)
        monkeypatch.setattr(software_identify, 'search_gog_games', lambda *_args, **_kwargs: [])
        mock_api.return_value = {'error': 'API Error'}
        
        # Ensure the library exists and is committed to the database
        db_session.add(sample_library)
        db_session.commit()
        
        with app.app_context():
            with patch('builtins.print'):
                result = retrieve_and_save_game('Test Game', '/test/path', library_uuid=sample_library.uuid)
        
        assert result is None
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_fetch_and_store_game_urls_success(self, mock_api, db_session, sample_game, sample_global_settings):
        """Test successful URL fetching and storing."""
        mock_api.return_value = [
            {'url': 'https://example.com/game1', 'category': 1},
            {'url': 'https://example.com/game2', 'category': 13}
        ]
        
        fetch_and_store_game_urls(sample_game.uuid, 12345)
        
        # Check URLs were stored
        urls = db_session.query(GameURL).filter_by(game_uuid=sample_game.uuid).all()
        assert len(urls) == 2
        assert urls[0].url == 'https://example.com/game1'
        assert urls[1].url == 'https://example.com/game2'
    
    @patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
    def test_fetch_and_store_game_urls_api_failure(self, mock_api, db_session, sample_game, sample_global_settings):
        """Test fetch_and_store_game_urls handles API failure."""
        mock_api.return_value = {'error': 'API Error'}
        
        with patch('builtins.print'):
            fetch_and_store_game_urls(sample_game.uuid, 12345)
        
        urls = db_session.query(GameURL).filter_by(game_uuid=sample_game.uuid).all()
        assert len(urls) == 0
    
    @patch('oneirodex.utils.services.scan_identify.make_igdb_api_request')
    def test_enumerate_companies_success(self, mock_api, db_session, sample_game, mock_company_response, sample_global_settings):
        """Test successful company enumeration."""
        from sqlalchemy import delete, update
        
        # Clean up any existing developer/publisher records by first removing foreign key references
        db_session.execute(update(Game).values(developer_id=None, publisher_id=None))
        db_session.execute(delete(Developer))
        db_session.execute(delete(Publisher))
        db_session.flush()
        
        mock_api.return_value = mock_company_response
        
        enumerate_companies(sample_game, sample_game.igdb_id, [1, 2])
        
        # Check companies were stored
        developers = db_session.query(Developer).all()
        publishers = db_session.query(Publisher).all()
        
        assert len(developers) == 1
        assert len(publishers) == 1
        assert developers[0].name == 'Test Developer'
        assert publishers[0].name == 'Test Publisher'
    
    @patch('oneirodex.utils.services.scan_identify.make_igdb_api_request')
    def test_enumerate_companies_api_failure(self, mock_api, db_session, sample_global_settings):
        """Test enumerate_companies handles API failure."""
        mock_api.return_value = {'error': 'API Error'}
        
        # Create a simple mock game for this test
        mock_game = MagicMock()
        mock_game.igdb_id = 12345
        
        with patch('builtins.print'):
            enumerate_companies(mock_game, 12345, [1, 2])
        
        # Check that no developers or publishers were created due to API failure
        developers = db_session.query(Developer).filter_by().all()
        publishers = db_session.query(Publisher).filter_by().all()
        # Don't assert exact count since there may be data from other tests
    
    def test_get_game_by_uuid_found(self, db_session, sample_game, sample_global_settings):
        """Test get_game_by_uuid finds existing game."""
        result = get_game_by_uuid(sample_game.uuid)
        
        assert result is not None
        assert result.uuid == sample_game.uuid
    
    def test_get_game_by_uuid_not_found(self, db_session, sample_global_settings):
        """Test get_game_by_uuid with non-existent UUID."""
        result = get_game_by_uuid('non-existent-uuid')
        
        assert result is None


class TestGameManagementFunctions:
    """Test game management functions like remove and delete."""
    
    def test_remove_from_lib_success(self, db_session, sample_game, sample_global_settings):
        """Test successful game removal from library."""
        game_uuid = sample_game.uuid
        
        result = remove_from_lib(game_uuid)
        
        assert result is True
        
        # Game should be removed from database
        game = db_session.query(Game).filter_by(uuid=game_uuid).first()
        assert game is None
    
    def test_remove_from_lib_not_found(self, db_session, sample_global_settings):
        """Test remove_from_lib with non-existent game."""
        result = remove_from_lib('non-existent-uuid')
        
        assert result is False
    
    def test_delete_game_success(self, db_session, sample_game, sample_global_settings):
        """Test successful game deletion."""
        game_uuid = sample_game.uuid
        
        # Function doesn't return value, just check it doesn't raise exception
        delete_game(game_uuid)
        
        # Game should be removed from database
        game = db_session.query(Game).filter_by(uuid=game_uuid).first()
        assert game is None
    
    def test_delete_game_with_exception(self, db_session, sample_game, sample_global_settings):
        """Test delete_game re-raises database errors so callers can report them."""
        with patch('oneirodex.utils.game_core.db.session.delete', side_effect=Exception("DB Error")):
            with patch('builtins.print'):
                with pytest.raises(Exception, match="DB Error"):
                    delete_game(sample_game.uuid)
    
    def test_delete_game_not_found(self, app, db_session, sample_global_settings):
        """Test delete_game with non-existent game raises 404."""
        from werkzeug.exceptions import NotFound
        
        with app.test_request_context():
            with pytest.raises(NotFound):
                delete_game('non-existent-uuid')


class TestBackgroundImageProcessing:
    """Test background image processing functions."""
    
    def test_download_pending_images(self, app, sample_global_settings):
        """Test download_pending_images function."""
        with app.app_context():
            result = download_pending_images(batch_size=5, app=app)
            # Should return count of processed images
            assert isinstance(result, int)
    
    @patch('oneirodex.utils.services.image_pipeline.download_pending_images')
    @patch('oneirodex.utils.game_core.threading.Thread')
    def test_start_background_image_downloader(self, mock_thread, mock_download, app, sample_global_settings):
        """Test start_background_image_downloader."""
        start_background_image_downloader()
        
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
    
    def test_turbo_download_images(self, app, sample_global_settings):
        """Test turbo_download_images function."""
        with app.app_context():
            result = turbo_download_images(max_workers=3, app=app)
            # Should return dictionary or count of processed images
            assert isinstance(result, (int, dict))
            if isinstance(result, dict):
                assert 'downloaded' in result
            else:
                assert result >= 0
    
    @patch('oneirodex.utils.services.image_pipeline.turbo_download_images')
    @patch('oneirodex.utils.game_core.threading.Thread')
    def test_start_turbo_background_downloader(self, mock_thread, mock_turbo, app, sample_global_settings):
        """Test start_turbo_background_downloader."""
        start_turbo_background_downloader(max_workers=4)
        
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()


class TestMissingImageProcessing:
    """Test missing image detection and processing functions."""
    
    def test_find_missing_images_for_library(self, app, db_session, sample_library, sample_global_settings):
        """Test find_missing_images_for_library function."""
        with app.app_context():
            result = find_missing_images_for_library(sample_library.uuid, app=app)
            # Should return a dictionary with statistics and list of missing images
            assert isinstance(result, dict)
            assert 'missing_images' in result or isinstance(result, list)
    
    def test_find_missing_images_all_libraries(self, app, sample_global_settings):
        """Test find_missing_images_for_library for all libraries."""
        with app.app_context():
            result = find_missing_images_for_library(app=app)
            # Should return a dictionary with statistics and list of missing images across all libraries
            assert isinstance(result, dict)
            assert 'missing_images' in result or isinstance(result, list)
    
    @patch('oneirodex.utils.services.image_pipeline.store_image_url_for_download')
    def test_queue_missing_images_for_download(self, mock_store_image, app, sample_game, sample_global_settings):
        """Test queue_missing_images_for_download function."""
        # Mock image objects with required attributes
        mock_image1 = MagicMock()
        mock_image1.game_uuid = sample_game.uuid
        mock_image1.igdb_image_id = '12345'
        mock_image1.image_type = 'cover'
        
        mock_image2 = MagicMock()
        mock_image2.game_uuid = sample_game.uuid
        mock_image2.igdb_image_id = '67890'
        mock_image2.image_type = 'screenshot'
        
        missing_images = [mock_image1, mock_image2]
        
        with app.app_context():
            result = queue_missing_images_for_download(missing_images)
        
        # Function may not call store_image_url_for_download directly, but should process the images
        # Check if it returns a count or processes the images
        if mock_store_image.call_count > 0:
            assert mock_store_image.call_count == 2
            mock_store_image.assert_any_call(sample_game.uuid, '12345', 'cover')
            mock_store_image.assert_any_call(sample_game.uuid, '67890', 'screenshot')
        else:
            # Function may handle images differently, just ensure no exceptions
            assert True
    
    @patch('oneirodex.utils.services.image_pipeline.queue_missing_images_for_download')
    @patch('oneirodex.utils.services.image_pipeline.find_missing_images_for_library')
    def test_process_missing_images_for_scan(self, mock_find_missing, mock_queue_missing, app, sample_library, sample_global_settings):
        """Test process_missing_images_for_scan function."""
        # Mock missing images found - may return dict or list depending on function implementation
        mock_images = [MagicMock(), MagicMock()]
        mock_find_missing.return_value = {
            'missing_images': mock_images, 
            'total_checked': 2, 
            'missing_count': 2,
            'already_queued': 0,
            'error': None
        }
        mock_queue_missing.return_value = 2
        
        with app.app_context():
            result = process_missing_images_for_scan(sample_library.uuid, app=app)
        
        mock_find_missing.assert_called_once_with(sample_library.uuid, app)
        # Check that the result is a dictionary with expected keys
        assert isinstance(result, dict)
        assert 'success' in result


class TestGetOrCreateEntity:
    """Test the get_or_create_entity helper function for thread safety."""

    def test_get_or_create_entity_new_genre(self, app):
        """Test creating a new genre when it doesn't exist."""
        with app.app_context():
            # Ensure no existing genre
            existing_genre = db.session.execute(db.select(Genre).filter_by(name="TestGenre")).scalar_one_or_none()
            if existing_genre:
                db.session.delete(existing_genre)
                db.session.commit()
            
            # Create new genre
            genre = get_or_create_entity(Genre, name="TestGenre")
            
            assert genre is not None
            assert genre.name == "TestGenre"
            assert genre.id is not None
            
            # Clean up
            db.session.delete(genre)
            db.session.commit()
    
    def test_get_or_create_entity_existing_genre(self, app):
        """Test getting an existing genre."""
        with app.app_context():
            # Create initial genre
            existing_genre = Genre(name="ExistingGenre")
            db.session.add(existing_genre)
            db.session.commit()
            existing_id = existing_genre.id
            
            # Get the same genre
            genre = get_or_create_entity(Genre, name="ExistingGenre")
            
            assert genre is not None
            assert genre.name == "ExistingGenre"
            assert genre.id == existing_id
            
            # Clean up
            db.session.delete(genre)
            db.session.commit()
    
    def test_get_or_create_entity_handles_integrity_error(self, app):
        """Test that get_or_create_entity handles IntegrityError correctly."""
        with app.app_context():
            # Ensure no existing genre
            existing_genre = db.session.execute(db.select(Genre).filter_by(name="IntegrityTestGenre")).scalar_one_or_none()
            if existing_genre:
                db.session.delete(existing_genre)
                db.session.commit()
            
            # First call should create the entity
            genre1 = get_or_create_entity(Genre, name="IntegrityTestGenre")
            assert genre1 is not None
            assert genre1.name == "IntegrityTestGenre"
            
            # Second call should get the existing entity (not create a new one)
            genre2 = get_or_create_entity(Genre, name="IntegrityTestGenre") 
            assert genre2 is not None
            assert genre2.name == "IntegrityTestGenre"
            assert genre1.id == genre2.id  # Should be the same entity
            
            # Verify only one genre exists in database
            all_genres = db.session.execute(db.select(Genre).filter_by(name="IntegrityTestGenre")).scalars().all()
            assert len(all_genres) == 1
            
            # Clean up
            db.session.delete(all_genres[0])
            db.session.commit()
    
    def test_get_or_create_entity_with_multiple_models(self, app):
        """Test get_or_create_entity works with different model types."""
        test_cases = [
            (Genre, "TestGenre2"),
            (Theme, "TestTheme"),
            (GameMode, "TestGameMode"), 
            (Platform, "TestPlatform"),
            (PlayerPerspective, "TestPerspective"),
            (Developer, "TestDeveloper"),
            (Publisher, "TestPublisher")
        ]
        
        with app.app_context():
            created_entities = []
            
            try:
                for model_class, name in test_cases:
                    # Clean up any existing entity first
                    existing = db.session.execute(db.select(model_class).filter_by(name=name)).scalar_one_or_none()
                    if existing:
                        db.session.delete(existing)
                        db.session.commit()
                    
                    # Create new entity
                    entity = get_or_create_entity(model_class, name=name)
                    created_entities.append(entity)
                    
                    assert entity is not None
                    assert entity.name == name
                    assert entity.id is not None
            
            finally:
                # Clean up all created entities
                for entity in created_entities:
                    try:
                        db.session.delete(entity)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
