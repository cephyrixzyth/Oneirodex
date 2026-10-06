import pytest
from flask import url_for
from oneirodex.models import User
from uuid import uuid4


@pytest.fixture
def admin_user(db_session):
    admin = User(
        user_id=str(uuid4()),
        name=f'TestAdmin_{str(uuid4())[:8]}',
        email=f'admin_{str(uuid4())[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    user = User(
        user_id=str(uuid4()),
        name=f'TestUser_{str(uuid4())[:8]}',
        email=f'user_{str(uuid4())[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def login_as(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestAdminHelpRoute:
    def test_requires_login(self, client, configured_install):
        response = client.get('/admin/help')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_requires_admin(self, client, regular_user):
        login_as(client, regular_user)
        response = client.get('/admin/help')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_admin_help_redirects_to_member_help(self, client, admin_user):
        login_as(client, admin_user)
        response = client.get('/admin/help')
        assert response.status_code == 302
        assert response.location == '/help'
        assert 'text/html' in response.content_type

    def test_admin_help_route_is_get_only(self, client, admin_user):
        login_as(client, admin_user)
        assert client.get('/admin/help').status_code == 302
        assert client.post('/admin/help').status_code == 405
        assert client.put('/admin/help').status_code == 405
        assert client.delete('/admin/help').status_code == 405

    def test_admin_help_route_registration(self, app):
        with app.test_request_context():
            assert url_for('admin2.admin_help') == '/admin/help'
