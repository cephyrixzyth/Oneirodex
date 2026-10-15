"""DB/file-free admin contracts; upload/delete helpers are mocked."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.chat_emoji as routes


class ReviewUser(UserMixin):
    def __init__(self, role): self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='emoji-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login'); app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    emoji = {'id': 1, 'slug': 'review', 'label': 'Review', 'emoji': ':review:', 'url': '/static/library/chat-emoji/review.webp'}
    upload = Mock(return_value=SimpleNamespace(to_dict=lambda: emoji))
    delete = Mock(return_value=True); listing = Mock(return_value=[emoji]); session = Mock()
    monkeypatch.setattr(routes, 'upload_custom_emoji', upload); monkeypatch.setattr(routes, 'delete_custom_emoji', delete)
    monkeypatch.setattr(routes, 'list_custom_emoji', listing); monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    token = client.get('/csrf').text
    return client, upload, delete, listing, session, {'X-CSRFToken': token}


def test_document_route_uses_shared_shell_without_loading_emoji_rows(harness, monkeypatch):
    client, _, _, listing, *_ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>admin shell</main>')
    response = client.get('/admin/chat_emoji')
    assert response.status_code == 200 and b'admin shell' in response.data
    assert rendered == ['Chat emoji - Oneirodex Admin']
    listing.assert_not_called()


def test_state_exposes_public_preview_and_actual_limits(harness):
    client, *_ = harness
    response = client.get('/api/admin/chat-emoji')
    assert response.status_code == 200
    assert response.json['max_custom'] == 20
    assert response.json['limits']['max_upload_bytes'] == 256 * 1024
    assert response.json['limits']['max_edge_px'] == 128
    assert response.json['emojis'][0]['url'].startswith('/static/library/chat-emoji/')
    assert response.headers['Cache-Control'] == 'no-store'


def test_multipart_upload_delegates_to_existing_helper(harness):
    client, upload, *_rest, headers = harness
    response = client.post('/api/admin/chat-emoji', data={'slug': 'review', 'label': 'Review', 'file': (BytesIO(b'test-image'), 'review.png')}, headers=headers)
    assert response.status_code == 201
    assert response.json['emoji']['emoji'] == ':review:'
    args = upload.call_args.kwargs
    assert args['slug'] == 'review' and args['label'] == 'Review'
    assert args['file'].filename == 'review.png'
    assert 'uploader' in args


@pytest.mark.parametrize('message', ['Custom emoji limit reached (20)', 'Slug already exists', 'Image file required',
    'Only PNG, WebP, or JPEG allowed', 'File too large (max 256KB)', 'Empty file'])
def test_helper_validation_kept_as_envelope(harness, message):
    client, upload, *_rest, headers = harness
    upload.side_effect = ValueError(message)
    response = client.post('/api/admin/chat-emoji', data={}, headers=headers)
    assert response.status_code == 400 and response.json['error'] == message


def test_decoder_errors_scrubbed_and_unexpected_failure_rolls_back(harness):
    client, upload, _, _, session, headers = harness
    upload.side_effect = ValueError('Invalid image: private decoder details')
    response = client.post('/api/admin/chat-emoji', data={}, headers=headers)
    assert response.status_code == 400 and 'private decoder' not in response.text
    upload.side_effect = RuntimeError('private failure')
    response = client.post('/api/admin/chat-emoji', data={}, headers=headers)
    assert response.status_code == 500 and 'private failure' not in response.text
    session.rollback.assert_called_once()


def test_delete_and_not_found(harness):
    client, _, delete, _, _, headers = harness
    assert client.delete('/api/admin/chat-emoji/review', headers=headers).status_code == 200
    delete.assert_called_once_with('review')
    delete.return_value = False
    assert client.delete('/api/admin/chat-emoji/review', headers=headers).status_code == 404
    assert client.delete('/api/admin/chat-emoji/bad!', headers=headers).status_code == 400


def test_acl_and_csrf_block_helpers(harness):
    client, upload, delete, _, _, headers = harness
    assert client.post('/api/admin/chat-emoji', data={}).status_code == 400
    assert client.delete('/api/admin/chat-emoji/review').status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    assert client.get('/api/admin/chat-emoji').status_code == 302
    assert client.post('/api/admin/chat-emoji', data={}, headers=headers).status_code == 302
    assert client.delete('/api/admin/chat-emoji/review', headers=headers).status_code == 302
    upload.assert_not_called(); delete.assert_not_called()
