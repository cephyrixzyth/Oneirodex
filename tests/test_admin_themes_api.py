from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

from oneirodex.models import User


def _admin(db_session):
    token = uuid4().hex[:10]
    user = User(name=f'theme_admin_{token}', email=f'theme_{token}@example.test', role='admin', user_id=str(uuid4()), state=True, is_email_verified=True)
    user.set_password('review-only-password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_theme_inventory_requires_admin(client, db_session):
    assert client.get('/api/admin/themes').status_code == 302
    user = User(name=f'member_{uuid4().hex[:8]}', email=f'member_{uuid4().hex[:8]}@example.test', role='user', user_id=str(uuid4()), state=True, is_email_verified=True)
    user.set_password('review-only-password')
    db_session.add(user)
    db_session.commit()
    _login(client, user)
    assert client.get('/api/admin/themes').status_code == 302


def test_theme_inventory_uses_envelope_and_only_exposes_theme_metadata(client, db_session):
    _login(client, _admin(db_session))
    themes = [{'folder': 'default', 'name': 'Default', 'author': 'Oneirodex', 'release_date': '2026-01-01', 'description': 'Built in'}]
    manager = MagicMock()
    manager.get_installed_themes.return_value = themes
    manager.get_default_theme.return_value = {'name': 'Default'}
    with patch('oneirodex.routes_apis.admin_themes.ThemeManager', return_value=manager):
        response = client.get('/api/admin/themes')
    body = response.get_json()
    assert response.status_code == 200
    assert body['ok'] is True
    assert body['themes'] == themes
    assert body['active_theme'] == 'default'
    assert 'theme_folder' not in body


def test_theme_upload_validates_zip_and_returns_uploaded_theme(client, db_session):
    _login(client, _admin(db_session))
    manager = MagicMock()
    manager.upload_theme.return_value = {'name': 'Night Green', 'author': 'Reviewer'}
    manager.get_installed_themes.return_value = [{'folder': 'night-green', 'name': 'Night Green'}]
    manager.get_default_theme.return_value = {'name': 'Default'}
    with patch('oneirodex.routes_apis.admin_themes.ThemeManager', return_value=manager):
        response = client.post('/api/admin/themes', data={'theme_zip': (BytesIO(b'PK\x03\x04archive'), 'night.zip')}, content_type='multipart/form-data')
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['theme']['name'] == 'Night Green'
    manager.upload_theme.assert_called_once()


def test_theme_upload_rejects_non_zip_before_manager(client, db_session):
    _login(client, _admin(db_session))
    manager = MagicMock()
    with patch('oneirodex.routes_apis.admin_themes.ThemeManager', return_value=manager):
        response = client.post('/api/admin/themes', data={'theme_zip': (BytesIO(b'not a zip'), 'theme.zip')}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    manager.upload_theme.assert_not_called()


def test_delete_theme_validates_and_returns_envelope(client, db_session):
    _login(client, _admin(db_session))
    manager = MagicMock()
    manager.get_installed_themes.return_value = []
    manager.get_default_theme.return_value = None
    with patch('oneirodex.routes_apis.admin_themes.ThemeManager', return_value=manager):
        response = client.delete('/api/admin/themes/night-green')
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    manager.delete_themefile.assert_called_once_with('night-green')


def test_loading_icon_inventory_requires_admin(client, db_session):
    _login(client, _admin(db_session))
    with patch('oneirodex.routes_apis.admin_themes.get_loading_icon_settings', return_value={'catalogue': [{'id': 'dpad'}], 'loading_icon_mode': 'rotate'}):
        response = client.get('/api/admin/themes/loading-icons')
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['catalogue'][0]['id'] == 'dpad'


def test_json_theme_reset_uses_shared_reset_and_returns_status(client, db_session):
    _login(client, _admin(db_session))
    with patch('oneirodex.routes_admin_ext.themes.perform_default_theme_reset', return_value=(True, 'Defaults reset.')):
        response = client.post('/admin/themes/reset', json={})
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['status'] == 'reset'


def test_json_theme_reset_does_not_return_filesystem_details(client, db_session):
    _login(client, _admin(db_session))
    with patch('oneirodex.routes_admin_ext.themes.perform_default_theme_reset', return_value=(False, 'copy failed at /srv/private/theme')):
        response = client.post('/admin/themes/reset', json={})
    assert response.status_code == 500
    body = response.get_json()
    assert body['ok'] is False
    assert 'Default theme reset failed' in body['error']
    assert '/srv/private/theme' not in response.get_data(as_text=True)
