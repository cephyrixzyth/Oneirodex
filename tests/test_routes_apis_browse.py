"""
Unit tests for oneirodex.routes_apis.browse

Tests the browse_folders_ss API endpoint including authentication, authorization,
directory browsing, security, and error handling.
"""

import pytest
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
from uuid import uuid4

from oneirodex.models import User


@pytest.fixture
def regular_user(db_session):
    """Create a test regular user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'regularuser_{user_uuid[:8]}',
        email=f'regular_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5
    )
    user.set_password('regularpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create a test admin user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'adminuser_{user_uuid[:8]}',
        email=f'admin_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def mock_filesystem():
    """Create a mock filesystem structure for testing."""
    return {
        'base_dir': '/test/base',
        'directories': ['subdir1', 'subdir2'],
        'files': [
            {'name': 'file1.txt', 'size': 100},
            {'name': 'file2.pdf', 'size': 200},
            {'name': 'file3', 'size': 50}  # No extension
        ]
    }


class TestBrowseFoldersSS:
    """Test the browse_folders_ss API endpoint."""
    
    def test_browse_requires_login(self, client):
        """Test that browse_folders_ss requires user login."""
        response = client.get('/api/browse_folders_ss')
        assert response.status_code == 302  # Redirect to login
    
    def test_browse_requires_admin(self, client, regular_user):
        """Test that browse_folders_ss requires admin privileges."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/browse_folders_ss')
        assert response.status_code == 302  # Redirect due to admin_required decorator
    
    @patch('oneirodex.routes_apis.browse.os')
    @patch('oneirodex.routes_apis.browse.current_app', new_callable=MagicMock)
    def test_nonexistent_directory(self, mock_current_app, mock_os, client, admin_user):
        """Test handling of nonexistent directories."""
        # Setup mocks
        mock_os.name = 'posix'
        base_dir = '/test/base'
        
        mock_current_app.config.get.side_effect = lambda key: {
            'BASE_FOLDER_POSIX': base_dir,
            'BASE_FOLDER_WINDOWS': None
        }.get(key)
        
        mock_os.path.abspath.return_value = '/test/base/nonexistent'
        mock_os.path.join.side_effect = lambda *args: '/'.join(args)
        mock_os.path.isdir.return_value = False  # Directory doesn't exist
        
        # Login as admin
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/browse_folders_ss', query_string={'path': 'nonexistent'})
        assert response.status_code == 404
        
        data = json.loads(response.data)
        assert 'error' in data
        assert 'SS folder browser: Folder not found' in data['error']
    
