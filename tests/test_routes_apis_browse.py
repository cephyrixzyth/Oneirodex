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
    
    
