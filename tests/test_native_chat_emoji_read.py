from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.chat_emoji_read import create_chat_emoji_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


def _client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-chat-emoji-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='emoji-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_chat_emoji_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=data or SimpleNamespace(read=lambda: {
            'emojis': [{'slug': 'cheer', 'emoji': ':cheer:'}],
            'max_custom': 24,
            'limits': {'max_upload_bytes': 1048576, 'max_edge_px': 256, 'extensions': ['.png']},
        }),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    )
    return client


def test_chat_emoji_read_keeps_envelope_no_store_and_head():
    client = _client()
    response = client.get('/api/admin/chat-emoji')
    head = client.head('/api/admin/chat-emoji')

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['emojis'][0]['emoji'] == ':cheer:'
    assert response.json()['limits']['extensions'] == ['.png']
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_chat_emoji_read_requires_admin():
    response = _client(role='user').get('/api/admin/chat-emoji', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')


def test_chat_emoji_read_uses_generic_error_on_storage_failure():
    client = _client(data=SimpleNamespace(read=lambda: (_ for _ in ()).throw(OSError('private path'))))
    response = client.get('/api/admin/chat-emoji')
    assert response.status_code == 500
    assert response.json()['error'] == 'Could not load custom chat emoji'
    assert 'private path' not in response.text


def test_chat_emoji_delete_checks_csrf_then_preserves_delete_contract():
    calls = []

    def delete(slug, upload_folder=None):
        calls.append(slug)
        if slug == 'bad!':
            raise ValueError('invalid slug')
        return slug == 'cheer'

    data = SimpleNamespace(
        read=lambda: {},
        delete=delete,
    )
    client = _client(data=data)
    invalid = client.delete('/api/admin/chat-emoji/cheer')
    deleted = client.delete(
        '/api/admin/chat-emoji/cheer',
        headers={'X-CSRFToken': client.csrf_token},
    )
    missing = client.delete(
        '/api/admin/chat-emoji/missing',
        headers={'X-CSRFToken': client.csrf_token},
    )
    bad_slug = client.delete(
        '/api/admin/chat-emoji/bad!',
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert invalid.status_code == 400
    assert deleted.status_code == 200
    assert deleted.json()['message'] == 'Custom emoji deleted.'
    assert missing.status_code == 404
    assert bad_slug.status_code == 400
    assert calls == ['cheer', 'missing', 'bad!']


def test_legacy_admin_chat_emoji_delete_keeps_csrf_flash_and_redirect():
    calls = []
    client = _client(data=SimpleNamespace(
        read=lambda: {},
        delete=lambda slug, upload_folder=None: calls.append((slug, upload_folder)) or True,
    ))
    rejected = client.post('/admin/chat_emoji', data={'action': 'delete', 'slug': 'cheer'})
    accepted = client.post(
        '/admin/chat_emoji',
        data={
            'action': 'delete', 'slug': 'cheer',
            'csrf_token': client.csrf_token,
        },
        follow_redirects=False,
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/admin/chat_emoji'
    assert calls == [('cheer', None)]
