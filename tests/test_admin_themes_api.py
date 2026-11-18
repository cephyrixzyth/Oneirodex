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


def test_theme_upload_rejects_non_zip_before_manager(client, db_session):
    _login(client, _admin(db_session))
    manager = MagicMock()
    with patch('oneirodex.utils.themes.ThemeManager', return_value=manager):
        response = client.post('/api/admin/themes', data={'theme_zip': (BytesIO(b'not a zip'), 'theme.zip')}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    manager.upload_theme.assert_not_called()


def test_loading_icon_inventory_requires_admin(client, db_session):
    _login(client, _admin(db_session))
    with patch('oneirodex.utils.loading_icons.get_loading_icon_settings', return_value={'catalogue': [{'id': 'dpad'}], 'loading_icon_mode': 'rotate'}):
        response = client.get('/api/admin/themes/loading-icons')
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['catalogue'][0]['id'] == 'dpad'


def test_json_theme_reset_uses_shared_reset_and_returns_status(client, db_session):
    _login(client, _admin(db_session))
    with patch('oneirodex.utils.theme_reset.reset_default_theme_assets', return_value=(True, 'Defaults reset.')):
        response = client.post('/admin/themes/reset', json={})
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert response.get_json()['status'] == 'reset'
