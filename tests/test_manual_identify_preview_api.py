from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from flask import Blueprint, Flask
from flask_login import LoginManager, UserMixin

import oneirodex.routes_apis.library_tools as routes
from oneirodex.routes_apis import apis_bp


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role


def _client(monkeypatch, tmp_path, role='admin'):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='manual-identify-preview-test-only')
    manager = LoginManager(app)
    manager.login_view = 'login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    login_bp = Blueprint('login', __name__)
    login_bp.add_url_rule('/', 'login', lambda: 'login')
    app.register_blueprint(login_bp, url_prefix='/login')
    app.register_blueprint(apis_bp)

    folder = tmp_path / 'library' / 'Metroid'
    folder.mkdir(parents=True)
    library = SimpleNamespace(uuid='library-1', name='Nintendo', scan_depth=2)
    session = Mock()
    session.get.return_value = library
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, '_allowed_bases', lambda: [str(tmp_path)])
    monkeypatch.setattr(routes, 'resolve_scan_path', lambda path, root, app: (str(folder), None))
    monkeypatch.setattr(routes, 'load_scanning_filter_patterns', lambda: ([], []))
    monkeypatch.setattr(routes, 'load_skip_dir_patterns', lambda: ['_tools'])
    monkeypatch.setattr(routes, 'load_skip_dir_regex_patterns', lambda: ['^_'])
    listing = Mock(return_value=[{'name': 'Metroid', 'full_path': str(folder)}])
    monkeypatch.setattr(routes, 'get_game_names_from_folder', listing)

    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = role
        value['_fresh'] = True
    return client, folder, listing, session


def test_manual_identify_preview_is_read_only_and_uses_library_scan_settings(monkeypatch, tmp_path):
    client, folder, listing, session = _client(monkeypatch, tmp_path)

    response = client.get('/api/library_tools/manual_identify/preview', query_string={
        'library_uuid': 'library-1', 'root': 'games', 'folder': 'ignored', 'scan_mode': 'folders',
    })

    assert response.status_code == 200
    assert response.json['ok'] is True
    assert response.json['read_only'] is True
    assert response.json['games'] == [{'name': 'Metroid', 'full_path': str(folder)}]
    assert response.headers['Cache-Control'] == 'no-store'
    listing.assert_called_once_with(
        str(folder), [], [], scan_depth=2,
        skip_dir_patterns=['_tools'], skip_dir_regexes=['^_'],
    )
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_manual_identify_preview_requires_admin(monkeypatch, tmp_path):
    client, _, listing, _ = _client(monkeypatch, tmp_path, role='member')

    response = client.get('/api/library_tools/manual_identify/preview', query_string={
        'library_uuid': 'library-1', 'root': 'games', 'scan_mode': 'folders',
    })

    assert response.status_code == 302
    listing.assert_not_called()
