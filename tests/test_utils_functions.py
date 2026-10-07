from sqlalchemy import text
import pytest
import os
import time
import tempfile
import shutil
from unittest.mock import patch, MagicMock, mock_open, call
from PIL import Image as PILImage
import requests
import requests.exceptions
from wtforms.validators import ValidationError

from oneirodex import create_app, db
from oneirodex.models import ReleaseGroup, Library, Game, GlobalSettings, User
from oneirodex.utils.functions import (
    format_size, square_image, get_folder_size_in_bytes, get_folder_size_in_bytes_updates,
    read_first_nfo_content, download_image, comma_separated_urls, website_category_to_string,
    PLATFORM_IDS, load_scanning_filter_patterns, get_library_count, get_games_count,
    delete_associations_for_game, sanitize_string_input,
    is_case_sensitive_flag, normalize_case_sensitive,
)


def safe_cleanup_database(db_session):
    """Safely clean up database records respecting foreign key constraints.""" 
    from sqlalchemy import delete
    
    # Clean up in order to respect foreign key constraints
    db_session.execute(delete(User))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(delete(Library))
    db_session.execute(delete(ReleaseGroup))
    db_session.execute(delete(GlobalSettings))
    db_session.commit()




@pytest.fixture
def sample_libraries(db_session):
    """Create sample libraries for testing."""
    libraries = []
    for i in range(3):
        library = Library(
            uuid=f'test-lib-{i}',
            name=f'Test Library {i}',
            image_url=f'https://example.com/lib{i}.jpg' if i % 2 else None
        )
        db_session.add(library)
        libraries.append(library)
    db_session.commit()
    return libraries


@pytest.fixture
def sample_games(db_session):
    """Create sample games for testing."""
    games = []
    for i in range(5):
        game = Game(
            uuid=f'test-game-{i}',
            name=f'Test Game {i}'
        )
        db_session.add(game)
        games.append(game)
    db_session.commit()
    return games


@pytest.fixture
def sample_release_groups(db_session):
    """Create sample scanning filters for testing."""
    release_groups = []
    
    # Case insensitive scanning filters
    rg1 = ReleaseGroup(filter_pattern='TEST_GROUP_1')
    rg2 = ReleaseGroup(filter_pattern='TEST_GROUP_2')

    # Case sensitive scanning filters
    rg3 = ReleaseGroup(filter_pattern='TEST_GROUP_3', case_sensitive='yes')
    rg4 = ReleaseGroup(filter_pattern='TEST_GROUP_4', case_sensitive='no')
    
    for rg in [rg1, rg2, rg3, rg4]:
        db_session.add(rg)
        release_groups.append(rg)
    
    db_session.commit()
    return release_groups


@pytest.fixture
def sample_global_settings(db_session, global_settings):
    """Sample settings for testing.

    Updates the singleton rather than inserting a second row — see the identical
    fixture in test_utils_download.py.
    """
    global_settings.update_folder_name = 'Updates'
    global_settings.extras_folder_name = 'Extras'
    db_session.commit()
    return global_settings


class TestFormatSize:
    """Test cases for format_size function."""
    
    def test_format_size_none_input(self):
        """Test format_size with None input."""
        result = format_size(None)
        assert result == '0 MB'
    
    def test_format_size_zero_bytes(self):
        """Test format_size with 0 bytes."""
        result = format_size(0)
        assert result == '0.00 KB'
    
    def test_format_size_kilobytes(self):
        """Test format_size for kilobyte range."""
        result = format_size(1024)  # 1 KB
        assert result == '1.00 KB'
        
        result = format_size(512)  # 0.5 KB
        assert result == '0.50 KB'
    
    def test_format_size_megabytes(self):
        """Test format_size for megabyte range."""
        result = format_size(1024 * 1024)  # 1 MB
        assert result == '1.00 MB'
        
        result = format_size(1536 * 1024)  # 1.5 MB
        assert result == '1.50 MB'
    
    def test_format_size_gigabytes(self):
        """Test format_size for gigabyte range."""
        result = format_size(1024 * 1024 * 1024)  # 1 GB
        assert result == '1.00 GB'
    
    def test_format_size_terabytes(self):
        """Test format_size for terabyte range."""
        result = format_size(1024 * 1024 * 1024 * 1024)  # 1 TB
        assert result == '1.00 TB'
    
    def test_format_size_very_large(self):
        """Test format_size for very large sizes."""
        result = format_size(1024**6)  # 1 EB (exabyte)
        assert result == '1.00 EB'
    
    def test_format_size_exception_handling(self):
        """Test format_size with invalid input that causes exception."""
        # Test with string input that can't be divided
        with patch('builtins.print') as mock_print:
            result = format_size('invalid')
            assert result == '0 MB'
            mock_print.assert_called_once()


class TestSquareImage:
    """Test cases for square_image function."""
    
    @patch('oneirodex.utils.helpers.images.PILImage')
    def test_square_image_already_square(self, mock_pil):
        """Test square_image when image is already square."""
        # Mock image that's already the target size
        mock_image = MagicMock()
        mock_image.size = [100, 100]
        
        result = square_image(mock_image, 100)
        
        mock_image.thumbnail.assert_called_once_with((100, 100))
        assert result == mock_image
    
    @patch('oneirodex.utils.helpers.images.PILImage')
    def test_square_image_needs_padding(self, mock_pil):
        """Test square_image when image needs padding."""
        # Mock image that needs padding
        mock_image = MagicMock()
        mock_image.size = [50, 80]  # Not square, smaller than target
        
        mock_new_image = MagicMock()
        mock_pil.new.return_value = mock_new_image
        
        result = square_image(mock_image, 100)
        
        mock_image.thumbnail.assert_called_once_with((100, 100))
        mock_pil.new.assert_called_once_with('RGB', (100, 100), color='black')
        mock_new_image.paste.assert_called_once()
        assert result == mock_new_image
    
    @patch('oneirodex.utils.helpers.images.PILImage')
    def test_square_image_different_aspect_ratio(self, mock_pil):
        """Test square_image with different aspect ratios."""
        mock_image = MagicMock()
        mock_image.size = [200, 100]  # Wide image
        
        mock_new_image = MagicMock()
        mock_pil.new.return_value = mock_new_image
        
        result = square_image(mock_image, 150)
        
        mock_image.thumbnail.assert_called_once_with((150, 150))
        mock_pil.new.assert_called_once_with('RGB', (150, 150), color='black')


class TestGetFolderSizeInBytes:
    """Test cases for get_folder_size_in_bytes function."""
    
    def test_get_folder_size_nonexistent_path(self):
        """Test get_folder_size_in_bytes with non-existent path."""
        with patch('builtins.print') as mock_print:
            result = get_folder_size_in_bytes('/nonexistent/path')
            assert result == 0
            mock_print.assert_called()
    
    @patch('os.path.isfile')
    @patch('os.path.getsize')
    @patch('os.path.exists')
    def test_get_folder_size_single_file(self, mock_exists, mock_getsize, mock_isfile):
        """Test get_folder_size_in_bytes with single file."""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_getsize.return_value = 1024
        
        result = get_folder_size_in_bytes('/path/to/file.txt')
        assert result == 1024
    
    @patch('os.access')
    @patch('os.path.exists')
    def test_get_folder_size_no_read_permission(self, mock_exists, mock_access):
        """Test get_folder_size_in_bytes with no read permission."""
        mock_exists.return_value = True
        mock_access.return_value = False
        
        with patch('builtins.print') as mock_print:
            result = get_folder_size_in_bytes('/path/no/permission')
            assert result == 0
            mock_print.assert_called()
    
    @patch('os.walk')
    @patch('os.path.getsize')
    @patch('os.path.exists')
    @patch('os.path.isfile')
    @patch('os.access')
    @patch('os.path.islink')
    def test_get_folder_size_normal_folder(self, mock_islink, mock_access, mock_isfile, 
                                           mock_exists, mock_getsize, mock_walk):
        """Test get_folder_size_in_bytes with normal folder structure."""
        mock_exists.return_value = True
        mock_isfile.return_value = False
        mock_access.return_value = True
        mock_islink.return_value = False
        mock_getsize.return_value = 512
        
        # Mock os.walk to return test directory structure
        mock_walk.return_value = [
            ('/test', ['subdir'], ['file1.txt', 'file2.txt']),
            ('/test/subdir', [], ['file3.txt'])
        ]
        
        result = get_folder_size_in_bytes('/test')
        assert result == 512 * 3  # 3 files, 512 bytes each
    
    @patch('os.walk')
    @patch('os.path.exists')
    @patch('os.path.isfile')
    @patch('os.access')
    def test_get_folder_size_with_symlinks(self, mock_access, mock_isfile, mock_exists, mock_walk):
        """Test get_folder_size_in_bytes skips symlinks."""
        mock_exists.return_value = True
        mock_isfile.return_value = False
        mock_access.return_value = True
        
        mock_walk.return_value = [
            ('/test', [], ['file1.txt', 'symlink'])
        ]
        
        def mock_islink_side_effect(path):
            return 'symlink' in path
        
        with patch('os.path.islink', side_effect=mock_islink_side_effect):
            with patch('os.path.getsize', return_value=512) as mock_getsize:
                result = get_folder_size_in_bytes('/test')
                # Should only count file1.txt, not the symlink
                assert mock_getsize.call_count == 1


class TestGetFolderSizeInBytesUpdates:
    """Test cases for get_folder_size_in_bytes_updates function."""
    
    def test_get_folder_size_updates_single_file(self, db_session):
        """Test get_folder_size_in_bytes_updates with single file."""
        with patch('oneirodex.utils.helpers.fs.get_allowed_base_directories', return_value=['/']):
            with patch('oneirodex.utils.helpers.fs.is_safe_path', return_value=(True, None)):
                with patch('os.path.isfile', return_value=True):
                    with patch('os.path.getsize', return_value=2048):
                        result = get_folder_size_in_bytes_updates('/path/to/file.txt')
                        assert result == 2048
    
    def test_get_folder_size_updates_nonexistent_path(self, db_session):
        """Test get_folder_size_in_bytes_updates with non-existent path."""
        with patch('oneirodex.utils.helpers.fs.get_allowed_base_directories', return_value=['/']):
            with patch('oneirodex.utils.helpers.fs.is_safe_path', return_value=(True, None)):
                with patch('os.path.exists', return_value=False):
                    with patch('builtins.print') as mock_print:
                        result = get_folder_size_in_bytes_updates('/nonexistent/path')
                        assert result == 0
                        mock_print.assert_called()
    
    def test_get_folder_size_updates_with_exclusions(self, db_session, sample_global_settings):
        """Test get_folder_size_in_bytes_updates excludes update/extra folders."""
        mock_walk_data = [
            ('/test', ['Updates', 'Extras', 'normal'], []),
            ('/test/Updates', [], ['update.exe']),
            ('/test/Extras', [], ['bonus.txt']),
            ('/test/normal', [], ['game.exe'])
        ]
        
        with patch('oneirodex.utils.helpers.fs.get_allowed_base_directories', return_value=['/']):
            with patch('oneirodex.utils.helpers.fs.is_safe_path', return_value=(True, None)):
                with patch('os.path.isfile', return_value=False):
                    with patch('os.path.exists', return_value=True):
                        with patch('os.access', return_value=True):
                            with patch('os.walk', return_value=mock_walk_data):
                                with patch('os.path.islink', return_value=False):
                                    with patch('os.path.getsize', return_value=1024):
                                        result = get_folder_size_in_bytes_updates('/test')
                                        # Should only count game.exe, not files in Updates/Extras
                                        assert result == 1024

    def test_get_folder_size_honors_timeout(self):
        """Timeout must stop the walk instead of ignoring the parameter."""
        slow_walk = [
            ('/test', ['a'], ['f1.bin']),
            ('/test/a', ['b'], ['f2.bin']),
            ('/test/a/b', [], ['f3.bin']),
        ]

        def slow_getsize(_path):
            time.sleep(0.05)
            return 100

        with patch('os.path.isfile', return_value=False):
            with patch('os.path.exists', return_value=True):
                with patch('os.access', return_value=True):
                    with patch('os.walk', return_value=slow_walk):
                        with patch('os.path.islink', return_value=False):
                            with patch('os.path.getsize', side_effect=slow_getsize):
                                with patch('builtins.print'):
                                    result = get_folder_size_in_bytes('/test', timeout=1)
        # Partial result is fine; must return quickly and not hang forever.
        assert result >= 1


class TestReadFirstNfoContent:
    """Test cases for read_first_nfo_content function."""
    
    def test_read_first_nfo_content_file_path(self):
        """Test read_first_nfo_content with file path instead of directory."""
        with patch('os.path.isfile', return_value=True):
            with patch('builtins.print') as mock_print:
                result = read_first_nfo_content('/path/to/file.txt')
                assert result is None
                mock_print.assert_called_with("Path is a file, not a directory. Skipping NFO scan.")
    
    def test_read_first_nfo_content_no_nfo_file(self):
        """Test read_first_nfo_content when no NFO file exists."""
        with patch('os.path.isfile', return_value=False):
            with patch('os.listdir', return_value=['game.exe', 'readme.txt']):
                with patch('builtins.print') as mock_print:
                    result = read_first_nfo_content('/path/to/game')
                    assert result is None
                    assert any('No NFO file found' in str(call) for call in mock_print.call_args_list)
    
    # The NFO is opened through open_plain_file_within (descriptor-level link
    # check), so these use real files rather than a mocked ``open``.
    def test_read_first_nfo_content_success(self, tmp_path):
        """Test read_first_nfo_content successfully reading NFO file."""
        nfo_content = "Game Name: Test Game\nRelease Date: 2023\nDescription: A test game"
        (tmp_path / 'game.nfo').write_bytes(nfo_content.encode('utf-8'))
        (tmp_path / 'game.exe').write_bytes(b'MZ')

        with patch('builtins.print'):
            result = read_first_nfo_content(str(tmp_path))
        assert result == nfo_content

    def test_read_first_nfo_content_with_null_bytes(self, tmp_path):
        """Test read_first_nfo_content removes null bytes from content."""
        (tmp_path / 'info.nfo').write_bytes(b"Game\x00Name: Test\x00Game")

        with patch('builtins.print'):
            result = read_first_nfo_content(str(tmp_path))
        assert result == "GameName: TestGame"

    def test_read_first_nfo_content_is_capped(self, tmp_path):
        """A huge NFO is read only up to the cap, not into memory whole."""
        from oneirodex.utils.helpers.fs import _NFO_MAX_BYTES

        (tmp_path / 'big.nfo').write_bytes(b'A' * (_NFO_MAX_BYTES + 5000))
        with patch('builtins.print'):
            result = read_first_nfo_content(str(tmp_path))
        assert result == 'A' * _NFO_MAX_BYTES


    def test_read_first_nfo_content_read_error(self):
        """Test read_first_nfo_content handles file read errors."""
        with patch('os.path.isfile', return_value=False):
            with patch('os.listdir', return_value=['game.nfo']):
                with patch('builtins.open', side_effect=IOError("Permission denied")):
                    with patch('builtins.print') as mock_print:
                        result = read_first_nfo_content('/path/to/game')
                        assert result is None
                        # Should print error and continue


class TestDownloadImage:
    """Test cases for download_image function."""

    def _allow_url(self, monkeypatch):
        monkeypatch.setattr(
            'oneirodex.utils.clients.images.validate_user_outbound_http_url',
            lambda url: (True, url),
        )

    def test_download_image_success(self, monkeypatch):
        """Test successful image download."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake_image_data'
        mock_response.headers = {}
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get = MagicMock(return_value=mock_response)
        self._allow_url(monkeypatch)
        monkeypatch.setattr('oneirodex.utils.clients.images.safe_get', mock_get)

        with patch('os.path.exists', return_value=True):
            with patch('os.access', return_value=True):
                with patch('builtins.open', mock_open()) as mock_file:
                    download_image('//example.com/image.jpg', '/path/to/save/image.jpg')

                    args, kwargs = mock_get.call_args
                    assert args[0] == 'https://example.com/image.jpg'
                    assert kwargs.get('timeout')

                    mock_file.assert_called_once_with('/path/to/save/image.jpg', 'wb')
                    mock_file().write.assert_called_once_with(b'fake_image_data')

    def test_download_image_url_transformation(self, monkeypatch):
        """Test URL transformation from thumb to original."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake_image_data'
        mock_response.headers = {}
        mock_response.iter_content.return_value = [mock_response.content]
        mock_get = MagicMock(return_value=mock_response)
        self._allow_url(monkeypatch)
        monkeypatch.setattr('oneirodex.utils.clients.images.safe_get', mock_get)

        with patch('os.path.exists', return_value=True):
            with patch('os.access', return_value=True):
                with patch('builtins.open', mock_open()):
                    download_image('https://example.com/t_thumb/image.jpg', '/path/image.jpg')
                    args, kwargs = mock_get.call_args
                    assert args[0] == 'https://example.com/t_original/image.jpg'
                    assert kwargs.get('timeout')

    def test_download_image_http_error(self, monkeypatch):
        """Test download_image with HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        self._allow_url(monkeypatch)
        monkeypatch.setattr(
            'oneirodex.utils.clients.images.safe_get',
            MagicMock(return_value=mock_response),
        )

        with patch('builtins.print') as mock_print:
            download_image('https://example.com/image.jpg', '/path/image.jpg')
            mock_print.assert_called_with("Failed to download the image. Status Code: 404")

    def test_download_image_create_directory(self, monkeypatch):
        """Test download_image creates directory when it doesn't exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake_image_data'
        mock_response.headers = {}
        mock_response.iter_content.return_value = [mock_response.content]
        self._allow_url(monkeypatch)
        monkeypatch.setattr(
            'oneirodex.utils.clients.images.safe_get',
            MagicMock(return_value=mock_response),
        )

        with patch('os.path.exists', return_value=False):
            with patch('os.makedirs') as mock_makedirs:
                with patch('os.access', return_value=True):
                    with patch('builtins.open', mock_open()):
                        with patch('builtins.print'):
                            download_image(
                                'https://example.com/image.jpg',
                                '/new/path/image.jpg',
                            )
                            mock_makedirs.assert_called_once_with(
                                '/new/path', exist_ok=True,
                            )

    def test_download_image_request_exception(self, monkeypatch):
        """Test download_image handles request exceptions."""
        self._allow_url(monkeypatch)
        monkeypatch.setattr(
            'oneirodex.utils.clients.images.safe_get',
            MagicMock(side_effect=requests.exceptions.ConnectionError("Network error")),
        )

        with patch('builtins.print') as mock_print:
            download_image('https://example.com/image.jpg', '/path/image.jpg')
            mock_print.assert_called()


class TestCommaSeparatedUrls:
    """Test cases for comma_separated_urls validator."""
    
    def test_comma_separated_urls_valid_single(self):
        """Test comma_separated_urls with single valid URL."""
        mock_form = MagicMock()
        mock_field = MagicMock()
        mock_field.data = 'https://www.youtube.com/embed/dQw4w9WgXcQ'
        
        # Should not raise an exception
        comma_separated_urls(mock_form, mock_field)
    
    def test_comma_separated_urls_valid_multiple(self):
        """Test comma_separated_urls with multiple valid URLs."""
        mock_form = MagicMock()
        mock_field = MagicMock()
        mock_field.data = 'https://www.youtube.com/embed/dQw4w9WgXcQ,https://youtube.com/embed/abc123,http://www.youtube.com/embed/xyz789'
        
        # Should not raise an exception
        comma_separated_urls(mock_form, mock_field)
    
    def test_comma_separated_urls_invalid_single(self):
        """Test comma_separated_urls with invalid URL."""
        mock_form = MagicMock()
        mock_field = MagicMock()
        mock_field.data = 'https://example.com/video'
        
        with pytest.raises(ValidationError) as exc_info:
            comma_separated_urls(mock_form, mock_field)
        
        assert 'invalid' in str(exc_info.value)
    
    def test_comma_separated_urls_mixed_valid_invalid(self):
        """Test comma_separated_urls with mix of valid and invalid URLs."""
        mock_form = MagicMock()
        mock_field = MagicMock()
        mock_field.data = 'https://www.youtube.com/embed/valid,https://example.com/invalid'
        
        with pytest.raises(ValidationError):
            comma_separated_urls(mock_form, mock_field)
    
    def test_comma_separated_urls_empty_string(self):
        """Test comma_separated_urls with empty string."""
        mock_form = MagicMock()
        mock_field = MagicMock()
        mock_field.data = ''
        
        with pytest.raises(ValidationError):
            comma_separated_urls(mock_form, mock_field)


class TestWebsiteCategoryToString:
    """Test cases for website_category_to_string function."""
    
    def test_website_category_to_string_known_ids(self):
        """Test website_category_to_string with known category IDs."""
        assert website_category_to_string(1) == "official"
        assert website_category_to_string(4) == "facebook"
        assert website_category_to_string(7) == "website"  # Test the newly added category ID 7
        assert website_category_to_string(9) == "youtube"
        assert website_category_to_string(13) == "steam"
    
    def test_website_category_to_string_unknown_id(self):
        """Test website_category_to_string with unknown category ID."""
        assert website_category_to_string(999) == "website"
        assert website_category_to_string(0) == "website"
        assert website_category_to_string(-1) == "website"
    
    def test_website_category_to_string_none_input(self):
        """Test website_category_to_string with None input."""
        assert website_category_to_string(None) == "website"
        
    def test_website_category_to_string_with_url_fallback(self):
        """Test website_category_to_string with URL pattern matching fallback."""
        # Test unknown category ID but recognizable URL patterns
        assert website_category_to_string(999, "https://store.steampowered.com/app/123") == "steam"
        assert website_category_to_string(0, "https://www.gog.com/game/example") == "gog"
        assert website_category_to_string(-1, "https://youtube.com/watch?v=abc") == "youtube"
        assert website_category_to_string(999, "https://twitter.com/example") == "twitter"
        assert website_category_to_string(999, "https://some-unknown-site.com") == "website"
        
    def test_website_category_to_string_known_id_with_url(self):
        """Test that known category IDs take precedence over URL patterns."""
        # Should return mapped value, not URL-based detection
        assert website_category_to_string(13, "https://youtube.com/example") == "steam"  # 13 = steam
        assert website_category_to_string(4, "https://twitter.com/example") == "facebook"  # 4 = facebook


class TestPlatformIds:
    """Test cases for PLATFORM_IDS constant."""
    
    def test_platform_ids_contains_expected_platforms(self):
        """Test PLATFORM_IDS contains expected platforms."""
        assert "PCWIN" in PLATFORM_IDS
        assert "PS5" in PLATFORM_IDS
        assert "XBOX" in PLATFORM_IDS
        assert "SNES" in PLATFORM_IDS
        assert "GBC" in PLATFORM_IDS

    def test_platform_ids_values(self):
        """Test specific PLATFORM_IDS values."""
        assert PLATFORM_IDS["PCWIN"] == 6
        assert PLATFORM_IDS["PS5"] == 167
        assert PLATFORM_IDS["XSX"] == 169
        assert PLATFORM_IDS["GBC"] == 22
        assert PLATFORM_IDS["OTHER"] is None


class TestLoadScanningFilterPatterns:
    """Test cases for load_scanning_filter_patterns function."""
    
    def test_load_scanning_filter_patterns_success(self, db_session, sample_release_groups):
        """Test load_scanning_filter_patterns with sample data."""
        insensitive, sensitive = load_scanning_filter_patterns()
        
        # Check insensitive patterns (all groups get both - and . prefixes)
        assert "-TEST_GROUP_1" in insensitive
        assert ".TEST_GROUP_1" in insensitive
        assert "-TEST_GROUP_2" in insensitive
        assert ".TEST_GROUP_2" in insensitive

        # Check sensitive patterns
        sensitive_dict = {pattern: case_sensitive for pattern, case_sensitive in sensitive}

        # TEST_GROUP_3 has case_sensitive='yes' so should be case sensitive
        assert ("-TEST_GROUP_3", True) in sensitive
        assert (".TEST_GROUP_3", True) in sensitive

        # TEST_GROUP_4 has case_sensitive='no' so should not be case sensitive
        assert ("-TEST_GROUP_4", False) in sensitive
        assert (".TEST_GROUP_4", False) in sensitive
    
    def test_load_scanning_filter_patterns_empty_db(self, db_session):
        """Test load_scanning_filter_patterns with empty database."""
        # Mock empty database response
        with patch('oneirodex.utils.helpers.scan_filters.db.session.execute') as mock_execute:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_execute.return_value.scalars.return_value = mock_scalars
            
            insensitive, sensitive = load_scanning_filter_patterns()
            assert insensitive == []
            assert sensitive == []
    
    def test_load_scanning_filter_patterns_db_error(self, db_session):
        """Test load_scanning_filter_patterns handles database errors."""
        from sqlalchemy.exc import SQLAlchemyError
        with patch('oneirodex.utils.helpers.scan_filters.db.session.execute', side_effect=SQLAlchemyError("DB Error")):
            with patch('builtins.print') as mock_print:
                insensitive, sensitive = load_scanning_filter_patterns()
                assert insensitive == []
                assert sensitive == []
                mock_print.assert_called()

    def test_is_case_sensitive_flag_shapes(self):
        """Accept bool, yes/no, 1/0, and true/false string forms."""
        for truthy in (True, 'yes', 'Yes', 'YES', 'true', 'True', '1', 1, 'y', 'on'):
            assert is_case_sensitive_flag(truthy) is True
        for falsy in (False, 'no', 'No', 'false', 'False', '0', 0, '', None, 'maybe'):
            assert is_case_sensitive_flag(falsy) is False

    def test_normalize_case_sensitive_canonical(self):
        """Write path always stores 'yes'|'no' for the String column."""
        assert normalize_case_sensitive(True) == 'yes'
        assert normalize_case_sensitive('yes') == 'yes'
        assert normalize_case_sensitive(1) == 'yes'
        assert normalize_case_sensitive('true') == 'yes'
        assert normalize_case_sensitive(False) == 'no'
        assert normalize_case_sensitive('no') == 'no'
        assert normalize_case_sensitive(0) == 'no'
        assert normalize_case_sensitive(None) == 'no'

    def test_load_scanning_filter_patterns_bool_and_string_shapes(self, db_session):
        """Load path treats bool and 'yes'|'no' rows the same."""
        unique = 'CS_SHAPE'
        yes_str = ReleaseGroup(filter_pattern=f'{unique}_YES_STR', case_sensitive='yes')
        no_str = ReleaseGroup(filter_pattern=f'{unique}_NO_STR', case_sensitive='no')
        yes_bool = ReleaseGroup(filter_pattern=f'{unique}_YES_BOOL', case_sensitive=True)
        no_bool = ReleaseGroup(filter_pattern=f'{unique}_NO_BOOL', case_sensitive=False)
        yes_one = ReleaseGroup(filter_pattern=f'{unique}_YES_1', case_sensitive='1')
        no_zero = ReleaseGroup(filter_pattern=f'{unique}_NO_0', case_sensitive='0')
        yes_true = ReleaseGroup(filter_pattern=f'{unique}_YES_TRUE', case_sensitive='true')
        for rg in (yes_str, no_str, yes_bool, no_bool, yes_one, no_zero, yes_true):
            db_session.add(rg)
        db_session.commit()

        _insensitive, sensitive = load_scanning_filter_patterns()
        sensitive_dict = {pattern: flag for pattern, flag in sensitive}

        assert sensitive_dict[f'-{unique}_YES_STR'] is True
        assert sensitive_dict[f'.{unique}_YES_STR'] is True
        assert sensitive_dict[f'-{unique}_NO_STR'] is False
        assert sensitive_dict[f'-{unique}_YES_BOOL'] is True
        assert sensitive_dict[f'-{unique}_NO_BOOL'] is False
        assert sensitive_dict[f'-{unique}_YES_1'] is True
        assert sensitive_dict[f'-{unique}_NO_0'] is False
        assert sensitive_dict[f'-{unique}_YES_TRUE'] is True


class TestGetLibraryCount:
    """get_library_count / get_games_count against the real query.

    These six tests used to mock `db.session.execute(...).scalars().all()` and
    assert a `print("Returning N libraries.")`. Both implementations changed to
    `select(func.count())` with no print, so the mocks no longer intercepted
    anything real and the assertions pinned behaviour that had been removed —
    they failed for the right reason and were only ever testing themselves.

    Counting by delta rather than absolute value on purpose: the test database
    is not reset between tests, so `assert count == 0` was never a statement
    about the function, only about whatever had run before.
    """

    def test_counts_the_libraries_that_exist(self, db_session):
        from oneirodex.models import Library, LibraryPlatform

        before = get_library_count()
        db_session.add_all([
            Library(name=f'CountLib {i}', platform=LibraryPlatform.PCWIN)
            for i in range(3)
        ])
        db_session.commit()

        assert get_library_count() == before + 3

    def test_a_removed_library_stops_being_counted(self, db_session):
        from oneirodex.models import Library, LibraryPlatform

        library = Library(name='CountLib solo', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.commit()

        after_add = get_library_count()
        db_session.delete(library)
        db_session.commit()

        assert get_library_count() == after_add - 1

    def test_returns_a_plain_int(self, db_session):
        """Callers put this straight into templates and JSON."""
        count = get_library_count()
        assert isinstance(count, int)
        assert not isinstance(count, bool)


class TestGetGamesCount:
    """See TestGetLibraryCount for why these no longer mock the session."""

    def test_counts_the_games_that_exist(self, db_session):
        from uuid import uuid4

        from oneirodex.models import Game, Library, LibraryPlatform

        library = Library(name=f'CountGames {uuid4().hex[:8]}',
                          platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.flush()

        before = get_games_count()
        db_session.add_all([
            Game(name=f'Counted {i}', library_uuid=library.uuid,
                 full_disk_path=f'/tmp/counted-{uuid4().hex[:8]}')
            for i in range(5)
        ])
        db_session.commit()

        assert get_games_count() == before + 5

    def test_returns_a_plain_int(self, db_session):
        count = get_games_count()
        assert isinstance(count, int)
        assert not isinstance(count, bool)


class TestDeleteAssociationsForGame:
    """Test cases for delete_associations_for_game function."""
    
    def test_delete_associations_for_game(self, db_session):
        """Test delete_associations_for_game clears associations."""
        # Create a mock game with associations
        mock_game = MagicMock()
        mock_game.genres = MagicMock()
        mock_game.platforms = MagicMock()
        mock_game.game_modes = MagicMock()
        mock_game.themes = MagicMock()
        mock_game.player_perspectives = MagicMock()
        mock_game.multiplayer_modes = MagicMock()
        
        delete_associations_for_game(mock_game)
        
        # Verify all associations were cleared
        mock_game.genres.clear.assert_called_once()
        mock_game.platforms.clear.assert_called_once()
        mock_game.game_modes.clear.assert_called_once()
        mock_game.themes.clear.assert_called_once()
        mock_game.player_perspectives.clear.assert_called_once()
        mock_game.multiplayer_modes.clear.assert_called_once()


class TestSanitizeStringInput:
    """Test cases for sanitize_string_input function."""
    
    def test_sanitize_string_input_none_input(self):
        """Test sanitize_string_input with None input."""
        result = sanitize_string_input(None, 100)
        assert result == ''
    
    def test_sanitize_string_input_empty_string(self):
        """Test sanitize_string_input with empty string."""
        result = sanitize_string_input('', 100)
        assert result == ''
    
    def test_sanitize_string_input_normal_string(self):
        """Test sanitize_string_input with normal string."""
        result = sanitize_string_input('  Hello World  ', 100)
        assert result == 'Hello World'
    
    def test_sanitize_string_input_html_escaping(self):
        """Test sanitize_string_input escapes HTML by default."""
        result = sanitize_string_input('<script>alert("xss")</script>', 100)
        assert '&lt;script&gt;' in result
        assert '&lt;/script&gt;' in result
    
    def test_sanitize_string_input_allow_html(self):
        """Test sanitize_string_input allows HTML when specified."""
        html_input = '<b>Bold text</b>'
        result = sanitize_string_input(html_input, 100, allow_html=True)
        assert result == html_input
    
    def test_sanitize_string_input_length_limit(self):
        """Test sanitize_string_input enforces length limit."""
        long_string = 'a' * 200
        result = sanitize_string_input(long_string, 50)
        assert len(result) == 50
        assert result == 'a' * 50
    
    def test_sanitize_string_input_non_string_input(self):
        """Test sanitize_string_input converts non-string input."""
        result = sanitize_string_input(12345, 100)
        assert result == '12345'
