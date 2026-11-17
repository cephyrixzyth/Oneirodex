import pytest
from flask import url_for
from unittest.mock import patch
from oneirodex.models import User, Newsletter, GlobalSettings
from oneirodex import db
from uuid import uuid4


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    admin_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=admin_uuid,
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    """Create a regular user."""
    user_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=user_uuid,
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def global_settings_smtp_enabled(db_session):
    """Create GlobalSettings with SMTP enabled and configured."""
    # Clear existing settings
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    
    settings = GlobalSettings(
        settings={'enableNewsletterFeature': True},
        smtp_enabled=True,
        smtp_server='smtp.test.com',
        smtp_port=587,
        smtp_username='test@test.com',
        smtp_password='testpass',
        smtp_use_tls=True,
        smtp_default_sender='noreply@test.com'
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def global_settings_smtp_disabled(db_session):
    """Create GlobalSettings with SMTP disabled."""
    # Clear existing settings
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    
    settings = GlobalSettings(
        settings={'enableNewsletterFeature': True},
        smtp_enabled=False
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def global_settings_newsletter_disabled(db_session):
    """Create GlobalSettings with newsletter feature disabled."""
    # Clear existing settings
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    
    settings = GlobalSettings(
        settings={'enableNewsletterFeature': False},
        smtp_enabled=True,
        smtp_server='smtp.test.com',
        smtp_port=587,
        smtp_username='test@test.com',
        smtp_password='testpass',
        smtp_use_tls=True,
        smtp_default_sender='noreply@test.com'
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def global_settings_no_sender(db_session):
    """Create GlobalSettings with SMTP enabled but no default sender."""
    # Clear existing settings
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    
    settings = GlobalSettings(
        settings={'enableNewsletterFeature': True},
        smtp_enabled=True,
        smtp_server='smtp.test.com',
        smtp_port=587,
        smtp_username='test@test.com',
        smtp_password='testpass',
        smtp_use_tls=True,
        smtp_default_sender=None
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def sample_newsletter(db_session, admin_user):
    """Create a sample newsletter record."""
    # Clear existing newsletters
    db_session.query(Newsletter).delete()
    db_session.commit()
    
    newsletter = Newsletter(
        subject='Test Newsletter',
        content='<p>This is a test newsletter content</p>',
        sender_id=admin_user.id,
        recipient_count=2,
        recipients=['test1@test.com', 'test2@test.com'],
        status='sent'
    )
    db_session.add(newsletter)
    db_session.commit()
    return newsletter


class TestNewsletterRoute:
    
    def test_newsletter_requires_login(self, client, configured_install):
        """Test that newsletter page requires login."""
        response = client.get('/admin/newsletter')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_newsletter_requires_admin(self, client, regular_user):
        """Test that newsletter page requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter')
        assert response.status_code == 302

    def test_newsletter_smtp_not_enabled(self, client, admin_user, global_settings_smtp_disabled):
        """The React page shell loads; readiness is supplied by the JSON API."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter')
        assert response.status_code == 200
        assert b'<title>' in response.data and b'Oneirodex Admin</title>' in response.data
        assert b'id="admin-app-root"' in response.data
        assert b'/static/dist/admin-app/admin-app.js' in response.data

    def test_newsletter_feature_disabled(self, client, admin_user, global_settings_newsletter_disabled):
        """Test newsletter page when newsletter feature is disabled."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter')
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data
        assert b'/static/dist/admin-app/admin-app.js' in response.data

    def test_newsletter_no_sender_configured(self, client, admin_user, global_settings_no_sender):
        """Test newsletter page when no default sender is configured."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter')
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data
        assert b'/static/dist/admin-app/admin-app.js' in response.data

    def test_newsletter_get_request_success(self, client, admin_user, global_settings_smtp_enabled, sample_newsletter):
        """Test successful GET request to newsletter page."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter')
        assert response.status_code == 200
        assert b'<title>' in response.data and b'Oneirodex Admin</title>' in response.data
        assert b'id="admin-app-root"' in response.data
        assert b'/static/dist/admin-app/admin-app.js' in response.data

    def test_newsletter_post_invalid_form(self, client, admin_user, global_settings_smtp_enabled, db_session):
        """Test POST with invalid form data."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # Missing required fields
        data = {
            'subject': '',  # Empty subject
            'content': '',  # Empty content
            'recipients': 'test@test.com',
            'send': 'Send'
        }

        response = client.post('/admin/newsletter', data=data)
        assert response.status_code == 200
        assert b'Newsletter sent successfully!' not in response.data
        assert db_session.query(Newsletter).filter_by(subject='').first() is None


class TestViewNewsletterRoute:
    
    def test_view_newsletter_requires_login(self, client, configured_install):
        """Test that view newsletter page requires login."""
        response = client.get('/admin/newsletter/1')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_view_newsletter_requires_admin(self, client, regular_user):
        """Test that view newsletter page requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter/1')
        assert response.status_code == 302

    def test_view_newsletter_success(self, client, admin_user, sample_newsletter):
        """Newsletter detail shell loads the row through its React API."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get(f'/admin/newsletter/{sample_newsletter.id}')
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

    def test_view_newsletter_not_found(self, client, admin_user, global_settings_smtp_enabled):
        """The page shell loads even if the data API will return a missing row."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/newsletter/99999')
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data
