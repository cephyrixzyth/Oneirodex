import pytest
import socket
import ssl
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from oneirodex.models import GlobalSettings
from oneirodex.utils.smtp import (
    get_smtp_settings, is_smtp_config_valid, is_server_reachable,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- SMTP send path (smtplib / sockets).


def safe_cleanup_database(db_session):
    """Safely clean up database records respecting foreign key constraints."""
    from sqlalchemy import delete
    db_session.execute(delete(GlobalSettings))
    db_session.commit()


@pytest.fixture
def valid_smtp_settings():
    """Create or update GlobalSettings record with valid SMTP configuration."""
    def _create_settings(db_session, enabled=True):
        from sqlalchemy import select
        # Get existing settings or create new one
        settings = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        if not settings:
            settings = GlobalSettings()
            db_session.add(settings)
        
        # Update with test values
        settings.smtp_enabled = enabled
        settings.smtp_server = 'smtp.example.com'
        settings.smtp_port = 587
        settings.smtp_username = 'testuser@example.com'
        settings.smtp_password = 'testpass123'
        settings.smtp_use_tls = True
        settings.smtp_default_sender = 'noreply@example.com'
        settings.smtp_last_tested = datetime.now(timezone.utc)
        
        db_session.commit()
        return settings
    return _create_settings


@pytest.fixture
def invalid_smtp_settings():
    """Create or update GlobalSettings record with invalid SMTP configuration."""
    def _create_settings(db_session, **overrides):
        from sqlalchemy import select
        # Get existing settings or create new one
        settings = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        if not settings:
            settings = GlobalSettings()
            db_session.add(settings)
            
        default_settings = {
            'smtp_enabled': True,
            'smtp_server': None,
            'smtp_port': None,
            'smtp_username': None,
            'smtp_password': None,
            'smtp_use_tls': True,
            'smtp_default_sender': None,
        }
        default_settings.update(overrides)
        
        # Update settings with test values
        for key, value in default_settings.items():
            setattr(settings, key, value)
        
        db_session.commit()
        return settings
    return _create_settings


class TestGetSMTPSettings:
    """Test get_smtp_settings function."""
    
    def test_get_smtp_settings_enabled(self, app, db_session, valid_smtp_settings):
        """Test getting SMTP settings when enabled and configured."""
        with app.app_context():
            # Create valid settings
            settings = valid_smtp_settings(db_session, enabled=True)
            
            # Test
            result = get_smtp_settings()
            
            # Verify
            assert result is not None
            assert result['SMTP_ENABLED'] is True
            assert result['MAIL_SERVER'] == 'smtp.example.com'
            assert result['MAIL_PORT'] == 587
            assert result['MAIL_USERNAME'] == 'testuser@example.com'
            assert result['MAIL_PASSWORD'] == 'testpass123'
            assert result['MAIL_USE_TLS'] is True
            assert result['MAIL_DEFAULT_SENDER'] == 'noreply@example.com'
            assert result['SERVER_HOSTNAME'] == 'smtp.example.com'
    
    def test_get_smtp_settings_disabled(self, app, db_session, valid_smtp_settings):
        """Test getting SMTP settings when disabled."""
        with app.app_context():
            # Create disabled settings
            valid_smtp_settings(db_session, enabled=False)
            
            # Test
            result = get_smtp_settings()
            
            # Verify - should return None when disabled
            assert result is None
    
    def test_get_smtp_settings_no_settings(self, app, db_session):
        """Test getting SMTP settings when no GlobalSettings exist."""
        with app.app_context():
            # Ensure no settings exist
            safe_cleanup_database(db_session)
            
            # Test
            result = get_smtp_settings()
            
            # Verify
            assert result is None


class TestIsSMTPConfigValid:
    """Test is_smtp_config_valid function."""
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_valid_complete(self, mock_get_settings):
        """Test validation with complete valid configuration."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': 'smtp.example.com',
            'MAIL_PORT': 587,
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': 'testpass123',
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify
        assert is_valid is True
        assert message == "Configuration valid"
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_smtp_disabled(self, mock_get_settings):
        """Test validation when SMTP is disabled."""
        # When SMTP is disabled, get_smtp_settings returns None
        mock_get_settings.return_value = None
        
        is_valid, message = is_smtp_config_valid()
        assert is_valid is False
        assert 'not enabled' in message.lower()
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_missing_single_field(self, mock_get_settings):
        """Test validation with single missing required field."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': None,  # Missing
            'MAIL_PORT': 587,
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': 'testpass123',
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify
        assert is_valid is False
        assert message == "Missing required fields: SMTP Server"
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_missing_multiple_fields(self, mock_get_settings):
        """Test validation with multiple missing required fields."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': None,
            'MAIL_PORT': None,
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': None,
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify
        assert is_valid is False
        assert "Missing required fields:" in message
        assert "SMTP Server" in message
        assert "SMTP Port" in message
        assert "Password" in message
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_invalid_port_non_numeric(self, mock_get_settings):
        """Test validation with non-numeric port."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': 'smtp.example.com',
            'MAIL_PORT': 'invalid',
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': 'testpass123',
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify
        assert is_valid is False
        assert message == "Port must be a valid number"
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_invalid_port_out_of_range(self, mock_get_settings):
        """Test validation with port out of range."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': 'smtp.example.com',
            'MAIL_PORT': 70000,  # Out of range
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': 'testpass123',
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify
        assert is_valid is False
        assert message == "Invalid port number"
    
    @patch('oneirodex.utils.smtp.get_smtp_settings')
    def test_config_invalid_port_zero(self, mock_get_settings):
        """Test validation with zero port."""
        mock_get_settings.return_value = {
            'SMTP_ENABLED': True,
            'MAIL_SERVER': 'smtp.example.com',
            'MAIL_PORT': 0,  # This will be caught as a missing field since 0 is falsy
            'MAIL_USERNAME': 'testuser@example.com',
            'MAIL_PASSWORD': 'testpass123',
            'MAIL_DEFAULT_SENDER': 'noreply@example.com'
        }
        
        # Test
        is_valid, message = is_smtp_config_valid()
        
        # Verify - 0 is falsy so it's treated as missing
        assert is_valid is False
        assert "Missing required fields: SMTP Port" in message


class TestIsServerReachable:
    """Test is_server_reachable function."""
    
    @patch('oneirodex.utils.smtp.socket.create_connection')
    @patch('ssl.create_default_context')
    def test_server_reachable_port_465_success(self, mock_ssl_context, mock_socket):
        """Test successful connection to SMTPS port 465."""
        # Setup mocks
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_ssl_sock = MagicMock()
        mock_context.wrap_socket.return_value.__enter__.return_value = mock_ssl_sock
        
        # Test
        with patch('builtins.print') as mock_print:
            result = is_server_reachable('smtp.example.com', 465)
        
        # Verify
        assert result is True
        mock_socket.assert_called_once_with(('smtp.example.com', 465), timeout=5)
        mock_ssl_context.assert_called_once()
        mock_print.assert_any_call("Basic connection successful to smtp.example.com:465")
        mock_print.assert_any_call("Direct SSL/TLS connection successful to smtp.example.com:465")
    
    @patch('oneirodex.utils.smtp.socket.create_connection')
    @patch('oneirodex.utils.smtp.smtplib.SMTP')
    @patch('ssl.create_default_context')
    def test_server_reachable_port_587_success(self, mock_ssl_context, mock_smtp_class, mock_socket):
        """Test successful connection to SMTP port 587 with STARTTLS."""
        # Setup mocks
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        mock_smtp = MagicMock()
        mock_smtp.has_extn.return_value = True
        mock_smtp_class.return_value = mock_smtp
        
        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        
        # Test
        with patch('builtins.print') as mock_print:
            result = is_server_reachable('smtp.example.com', 587)
        
        # Verify
        assert result is True
        mock_socket.assert_called_once_with(('smtp.example.com', 587), timeout=5)
        mock_smtp_class.assert_called_once_with('smtp.example.com', 587)
        mock_smtp.ehlo.assert_called()
        mock_smtp.has_extn.assert_called_with('STARTTLS')
        mock_smtp.starttls.assert_called_once_with(context=mock_context)
        mock_smtp.quit.assert_called_once()
        mock_print.assert_any_call("Basic connection successful to smtp.example.com:587")
        mock_print.assert_any_call("STARTTLS connection successful to smtp.example.com:587")
    
    @patch('oneirodex.utils.smtp.socket.create_connection')
    def test_server_reachable_socket_timeout(self, mock_socket):
        """Test server unreachable due to socket timeout."""
        mock_socket.side_effect = socket.timeout()
        
        # Test
        with patch('builtins.print') as mock_print:
            result = is_server_reachable('smtp.example.com', 587)
        
        # Verify
        assert result is False
        mock_print.assert_called_with("Connection timeout to smtp.example.com:587")
    
    @patch('oneirodex.utils.smtp.socket.create_connection')
    def test_server_reachable_ssl_error(self, mock_socket):
        """Test server unreachable due to SSL error."""
        mock_socket.side_effect = ssl.SSLError("SSL handshake failed")
        
        # Test
        with patch('builtins.print') as mock_print:
            result = is_server_reachable('smtp.example.com', 465)
        
        # Verify
        assert result is False
        # SSL error message includes the exception args tuple
        mock_print.assert_called_with("SSL/TLS error connecting to smtp.example.com:465: ('SSL handshake failed',)")
    
    @patch('oneirodex.utils.smtp.socket.create_connection')
    def test_server_reachable_general_exception(self, mock_socket):
        """Test server unreachable due to general exception."""
        mock_socket.side_effect = ConnectionRefusedError("Connection refused")
        
        # Test
        with patch('builtins.print') as mock_print:
            result = is_server_reachable('smtp.example.com', 587)
        
        # Verify
        assert result is False
        mock_print.assert_called_with("Error connecting to smtp.example.com:587: Connection refused")


    
    
    
    
    
    
    
    
    
    


    


    
