from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import ai_status as native_ai_status
from oneirodex.runtime_native.ai_status import create_ai_status_router
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token, load_session_cookie,
)


class FakeAiStatusData:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'enabled': True,
            'auto_apply_enabled': False,
            'reachable': False,
            'base_url': 'http://ollama.test:11434',
            'model': 'small-model',
            'error': 'Ollama unreachable',
        }
        self.config_calls = []
        self.action_calls = []
        self.apply_enabled = False

    def status(self, *, config=None):
        self.calls += 1
        return self.payload

    def read_config(self, *, config=None):
        return {'enabled': False, 'ollama_model': 'small-model'}

    def save_config(self, payload, *, config=None):
        self.config_calls.append(payload)
        return {'enabled': payload.get('enabled', False), 'ollama_model': 'small-model'}

    def enabled(self, *, config=None):
        return True

    def unmatched_folder(self, _folder_id):
        return None

    def folder_platform(self, _library_uuid):
        return None

    def triage(self, name, platform, *, config=None):
        self.action_calls.append(('triage', name, platform))
        return {'query': name, 'platform': platform, 'suggestions': [{'title': 'Example'}]}

    def game_name_and_summary(self, game_uuid):
        return ('Example game', 'Fixture summary') if game_uuid == 'game-1' else None

    def notes(self, context, *, config=None):
        self.action_calls.append(('notes', context))
        return {'game_name': context['game_name'], 'notes': 'Fixture guidance'}

    def auto_apply_enabled(self, *, config=None):
        return self.apply_enabled

    def apply(self, game_uuid, title, *, config=None):
        self.action_calls.append(('apply', game_uuid, title))
        return {'applied': True, 'unchanged': False, 'game_uuid': game_uuid, 'name': title}


def make_client(*, role='admin', authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-ai-status-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=109, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_ai_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 109 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '109' else None,
        login_manager=manager,
        data_access=data or FakeAiStatusData(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '109:fp'}, 'native-ai-status-secret')
        )
    return client


def test_admin_get_preserves_bare_status_payload_and_unreachable_error_data():
    data = FakeAiStatusData()
    response = make_client(data=data).get('/api/ai/status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert response.json()['error'] == 'Ollama unreachable'
    assert 'ok' not in response.json()
    assert data.calls == 1


def test_anonymous_redirects_with_login_flash_and_next_without_status_call():
    data = FakeAiStatusData()
    response = make_client(authenticated=False, data=data).get(
        '/api/ai/status?from=settings', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Fai%2Fstatus%3Ffrom%3Dsettings'
    session = load_session_cookie(
        response.cookies['session'], 'native-ai-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_non_admin_redirects_with_danger_flash_without_next_or_status_call():
    data = FakeAiStatusData()
    response = make_client(role='user', data=data).get(
        '/api/ai/status?from=settings', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-ai-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_admin_token_without_admin_scope_is_forbidden(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_ai_status, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeAiStatusData()
    response = make_client(data=data).get('/api/ai/status')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'This token does not have the admin scope',
        'error_code': 'forbidden',
        'message': 'This token does not have the admin scope',
        'success': False,
    }
    assert data.calls == 0


def test_head_preserves_headers_and_length_without_returning_body():
    data = FakeAiStatusData()
    client = make_client(data=data)
    get_response = client.get('/api/ai/status')
    head_response = client.head('/api/ai/status')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.calls == 2


def test_ai_flag_projection_accepts_explicit_native_config():
    from oneirodex.utils.ai_assist import ai_auto_apply_enabled, ai_enabled

    config = {'ENABLE_AI_ASSIST': True, 'ENABLE_AI_AUTO_APPLY': True}
    assert ai_enabled(config=config) is True
    assert ai_auto_apply_enabled(config=config) is True


def test_ai_config_read_write_and_csrf_contract():
    data = FakeAiStatusData()
    client = make_client(data=data)
    read = client.get('/api/ai/config')
    head = client.head('/api/ai/config')
    assert read.status_code == 200
    assert read.json() == {'enabled': False, 'ollama_model': 'small-model'}
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(read.content))

    rejected = client.put('/api/ai/config', json={'enabled': True})
    assert rejected.status_code == 400
    assert data.config_calls == []

    session = {'_user_id': '109:fp'}
    csrf = generate_csrf_token(session, 'native-ai-status-secret')
    client.cookies.clear()
    client.cookies.set('session', dump_session_cookie(session, 'native-ai-status-secret'))
    saved = client.put(
        '/api/ai/config', json={'enabled': True}, headers={'X-CSRFToken': csrf},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        'enabled': True, 'ollama_model': 'small-model', 'status': 'saved',
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert data.config_calls == [{'enabled': True}]


def test_ai_triage_and_doctor_notes_actions_use_csrf_and_fake_adapter():
    data = FakeAiStatusData()
    client = make_client(data=data)
    session = {'_user_id': '109:fp'}
    csrf = generate_csrf_token(session, 'native-ai-status-secret')
    client.cookies.clear()
    client.cookies.set('session', dump_session_cookie(session, 'native-ai-status-secret'))
    headers = {'X-CSRFToken': csrf}

    rejected = client.post('/api/ai/triage', json={'name': 'Fixture'})
    triage = client.post(
        '/api/ai/triage', json={'name': '  Fixture  ', 'platform': 'NES'}, headers=headers,
    )
    notes = client.post(
        '/api/ai/doctor-notes',
        json={'game_uuid': 'game-1', 'issues': ['missing-cover']}, headers=headers,
    )
    assert rejected.status_code == 400
    assert triage.status_code == 200
    assert triage.json()['suggestions'] == [{'title': 'Example'}]
    assert notes.status_code == 200
    assert notes.json() == {'game_name': 'Example game', 'notes': 'Fixture guidance'}
    assert data.action_calls == [
        ('triage', 'Fixture', 'NES'),
        ('notes', {
            'issues': ['missing-cover'], 'summary': 'Fixture summary',
            'game_name': 'Example game',
        }),
    ]


def test_ai_apply_triage_keeps_explicit_feature_gate_and_created_status():
    data = FakeAiStatusData()
    client = make_client(data=data)
    session = {'_user_id': '109:fp'}
    csrf = generate_csrf_token(session, 'native-ai-status-secret')
    client.cookies.clear()
    client.cookies.set('session', dump_session_cookie(session, 'native-ai-status-secret'))
    headers = {'X-CSRFToken': csrf}

    disabled = client.post(
        '/api/ai/apply-triage', json={'game_uuid': 'game-1', 'title': 'Fixture'},
        headers=headers,
    )
    assert disabled.status_code == 403
    assert disabled.json()['auto_apply_enabled'] is False
    assert data.action_calls == []

    data.apply_enabled = True
    applied = client.post(
        '/api/ai/apply-triage', json={'game_uuid': 'game-1', 'title': 'Fixture'},
        headers=headers,
    )
    invalid = client.post('/api/ai/apply-triage', json={}, headers=headers)
    assert applied.status_code == 201
    assert applied.json()['name'] == 'Fixture'
    assert invalid.status_code == 422
    assert data.action_calls == [('apply', 'game-1', 'Fixture')]
