from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from flask import Blueprint, Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf

import oneirodex.routes_apis.library_tools as routes
from oneirodex.routes_apis import apis_bp


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role
        self.name = f'Reviewer {role}'


def _harness(monkeypatch, tmp_path, role='admin'):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='link-existing-api-test-only')
    manager = LoginManager(app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    login_bp = Blueprint('login', __name__)
    login_bp.add_url_rule('/', 'login', lambda: 'login')
    app.register_blueprint(login_bp, url_prefix='/login')
    app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app)
    app.register_blueprint(apis_bp)

    base = tmp_path / 'allowed'
    base.mkdir()
    folder = base / 'Example Game'
    folder.mkdir()
    game = SimpleNamespace(uuid='game-1', name='Example Game', full_disk_path='/old/path', path_status=None)
    unmatched = SimpleNamespace(folder_path=str(folder))
    session = Mock()
    session.get.return_value = game
    session.execute.return_value.scalars.return_value.first.return_value = unmatched
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, '_allowed_bases', lambda: [str(base)])
    monkeypatch.setattr('oneirodex.utils.rom_language.apply_rom_language_fields', lambda *args: None)
    monkeypatch.setattr(routes, 'log_system_event', Mock())

    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = role
        value['_fresh'] = True
    headers = {'X-CSRFToken': client.get('/csrf').text}
    return client, headers, game, unmatched, session, folder


def test_link_existing_game_updates_path_and_clears_matching_unmatched_row(monkeypatch, tmp_path):
    client, headers, game, unmatched, session, folder = _harness(monkeypatch, tmp_path)

    response = client.post('/api/library_tools/link_existing_game', json={
        'game_uuid': game.uuid,
        'full_disk_path': str(folder),
        'library_uuid': 'library-1',
        'from_unmatched': True,
    }, headers=headers)

    assert response.status_code == 200
    assert response.json['ok'] is True
    assert response.json['game_name'] == 'Example Game'
    assert response.json['removed_from_unmatched'] is True
    assert game.full_disk_path == str(folder)
    assert game.path_status == 'ok'
    session.delete.assert_called_once_with(unmatched)
    session.commit.assert_called_once()


def test_link_existing_game_rejects_outside_folder_and_requires_admin_csrf(monkeypatch, tmp_path):
    client, headers, game, _, session, _ = _harness(monkeypatch, tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()

    response = client.post('/api/library_tools/link_existing_game', json={
        'game_uuid': game.uuid, 'full_disk_path': str(outside),
    }, headers=headers)
    assert response.status_code == 403
    session.commit.assert_not_called()

    assert client.post('/api/library_tools/link_existing_game', json={
        'game_uuid': game.uuid, 'full_disk_path': str(outside),
    }).status_code == 400
    with client.session_transaction() as value:
        value['_user_id'] = 'member'
    assert client.post('/api/library_tools/link_existing_game', json={
        'game_uuid': game.uuid, 'full_disk_path': str(outside),
    }, headers=headers).status_code == 302
    session.commit.assert_not_called()
