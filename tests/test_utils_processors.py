import pytest
from sqlalchemy import delete
from oneirodex.models import GlobalSettings
from oneirodex.utils.processors import get_global_settings
from oneirodex import app_version


class TestGetGlobalSettings:
    """Tests for get_global_settings function."""
    
    def test_get_global_settings_no_record(self, app, db_session):
        """Test get_global_settings when no GlobalSettings record exists."""
        with app.app_context():
            # Clear any existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()

            result = get_global_settings()

        # Should return default values
        expected_defaults = {
            'show_logo': True,
            'show_help_button': True,
            'enable_web_links': True,
            'enable_server_status': True,
            'enable_newsletter': True,
            'show_version': True,
            'show_discovery': True,
            'show_favorites': True,
            'show_trailers': True,
            'show_play_status': True,
            'enable_delete_game_on_disk': True,
            'enable_game_updates': True,
            'enable_game_extras': True,
            'app_version': app_version
        }

        assert result == expected_defaults
        assert result['app_version'] == app_version
    
    def test_get_global_settings_empty_settings(self, app, db_session):
        """Test get_global_settings with GlobalSettings record but null settings."""
        with app.app_context():
            # Clear any existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()

            # Create GlobalSettings record with no settings
            settings_record = GlobalSettings(settings=None)
            db_session.add(settings_record)
            db_session.flush()

            result = get_global_settings()

        # Should return default values
        expected_defaults = {
            'show_logo': True,
            'show_help_button': True,
            'enable_web_links': True,
            'enable_server_status': True,
            'enable_newsletter': True,
            'show_version': True,
            'show_discovery': True,
            'show_favorites': True,
            'show_trailers': True,
            'show_play_status': True,
            'enable_delete_game_on_disk': True,
            'enable_game_updates': True,
            'enable_game_extras': True,
            'app_version': app_version
        }

        assert result == expected_defaults
    
    def test_get_global_settings_partial_settings(self, app, db_session):
        """Test get_global_settings with partial settings that merge with defaults."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()
            
            # Create GlobalSettings record with partial settings
            partial_settings = {
                'showSystemLogo': False,
                'enableWebLinksOnDetailsPage': False,
                'enableServerStatusFeature': False
            }
            settings_record = GlobalSettings(settings=partial_settings)
            db_session.add(settings_record)
            db_session.flush()
            
            result = get_global_settings()
        
        # Should merge partial settings with defaults based on function behavior
        assert result['show_logo'] is False  # From partial settings via settings.get()
        assert result['enable_web_links'] is False  # From partial settings via settings.get()
        assert result['enable_server_status'] is False  # From partial settings via settings_record.settings.get()
        assert result['show_help_button'] is True  # From defaults (not overridden) via settings.get()
        assert result['enable_newsletter'] is False  # Default from settings_record.settings.get() since not in partial_settings
        assert result['app_version'] == app_version
    
    def test_get_global_settings_complete_settings(self, app, db_session):
        """Test get_global_settings with complete custom settings."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()
            
            # Create GlobalSettings record with complete custom settings
            custom_settings = {
                'showSystemLogo': False,
                'showHelpButton': False,
                'enableWebLinksOnDetailsPage': False,
                'enableServerStatusFeature': False,
                'enableNewsletterFeature': False,
                'showVersion': False,
                'enableDeleteGameOnDisk': False,
                'enableGameUpdates': False,
                'enableGameExtras': False
            }
            settings_record = GlobalSettings(settings=custom_settings)
            db_session.add(settings_record)
            db_session.flush()
            
            result = get_global_settings()
        
        # Should use custom settings based on function behavior
        assert result['show_logo'] is False  # settings.get('showSystemLogo')
        assert result['show_help_button'] is False  # settings.get('showHelpButton')
        assert result['enable_web_links'] is False  # settings.get('enableWebLinksOnDetailsPage')
        assert result['enable_server_status'] is False  # settings_record.settings.get('enableServerStatusFeature', False)
        assert result['enable_newsletter'] is False  # settings_record.settings.get('enableNewsletterFeature', False)
        assert result['show_version'] is False  # settings_record.settings.get('showVersion', False)
        assert result['enable_delete_game_on_disk'] is False  # settings_record.settings.get('enableDeleteGameOnDisk', True)
        assert result['enable_game_updates'] is False  # settings_record.settings.get('enableGameUpdates', True)
        assert result['enable_game_extras'] is False  # settings_record.settings.get('enableGameExtras', True)
        assert result['app_version'] == app_version
    
    def test_get_global_settings_includes_app_version(self, app, db_session):
        """Test that app_version is always included in result."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()
            
            # Test with no settings record
            result = get_global_settings()
            assert 'app_version' in result
            assert result['app_version'] == app_version
            
            # Test with settings record
            settings_record = GlobalSettings(settings={'showSystemLogo': True})
            db_session.add(settings_record)
            db_session.flush()
            
            result = get_global_settings()
            assert 'app_version' in result
            assert result['app_version'] == app_version
    
    def test_get_global_settings_return_keys(self, app, db_session):
        """Test that all expected keys are present in return value."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()

            result = get_global_settings()

        expected_keys = {
            'show_logo',
            'show_help_button',
            'enable_web_links',
            'enable_server_status',
            'enable_newsletter',
            'show_version',
            'show_discovery',
            'show_favorites',
            'show_trailers',
            'show_play_status',
            'enable_delete_game_on_disk',
            'enable_game_updates',
            'enable_game_extras',
            'app_version'
        }

        assert set(result.keys()) == expected_keys
    
    def test_get_global_settings_duplicate_defaults_handling(self, app, db_session):
        """Test that duplicate keys in default_settings are handled correctly."""
        # The function has duplicate keys in default_settings dict
        # This test ensures the function handles this gracefully
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()

            result = get_global_settings()

        # Should not cause errors and return valid result
        assert isinstance(result, dict)
        assert len(result) == 14  # Should have exactly 14 keys
        assert all(key in result for key in [
            'show_logo', 'show_help_button', 'enable_web_links',
            'enable_server_status', 'enable_newsletter', 'show_version',
            'show_discovery', 'show_favorites', 'show_trailers', 'show_play_status',
            'enable_delete_game_on_disk', 'enable_game_updates',
            'enable_game_extras', 'app_version'
        ])
    
    def test_get_global_settings_boolean_types(self, app, db_session):
        """Test that all settings (except app_version) return boolean values."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()
            
            result = get_global_settings()
        
        for key, value in result.items():
            if key != 'app_version':
                assert isinstance(value, bool), f"Key '{key}' should be boolean, got {type(value)}"
        
        assert isinstance(result['app_version'], str)
    
    @pytest.fixture
    def sample_global_settings(self, db_session):
        """Create sample GlobalSettings for testing."""
        settings = GlobalSettings(
            settings={
                'showSystemLogo': True,
                'enableWebLinksOnDetailsPage': True,
                'enableServerStatusFeature': True
            }
        )
        db_session.add(settings)
        db_session.flush()
        return settings
    
    def test_get_global_settings_with_fixture(self, app, db_session):
        """Test get_global_settings using fixture data pattern."""
        with app.app_context():
            # Clear existing settings first
            db_session.execute(delete(GlobalSettings))
            db_session.flush()
            
            # Create fresh fixture-like settings
            fixture_settings = GlobalSettings(
                settings={
                    'showSystemLogo': True,
                    'enableWebLinksOnDetailsPage': True,
                    'enableServerStatusFeature': True
                }
            )
            db_session.add(fixture_settings)
            db_session.flush()
            
            result = get_global_settings()
        
        assert result['show_logo'] is True
        assert result['enable_web_links'] is True  
        assert result['enable_server_status'] is True
        assert result['app_version'] == app_version