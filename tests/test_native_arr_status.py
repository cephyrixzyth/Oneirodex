from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import arr_status as native_arr
from oneirodex.runtime_native.arr_status import ArrStatusData, create_arr_status_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeArrStatusData:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'enabled': True,
            'module': 'arr',
            'status': 'ready',
            'message': 'Arr module ready — configure native indexers, presets, and optional Prowlarr/Jackett hubs in Admin → Arr.',
            'connectors': [
                {'id': 'native_indexers', 'configured': True, 'warnings': ['Indexer B offline']},
                {'id': 'prowlarr', 'configured': False, 'warnings': []},
            ],
            'hardlink_pipeline_enabled': True,
            'hardlink_helpers_enabled': True,
            'hardlink_apply_allowed': False,
            'indexer_warnings': ['Indexer B offline'],
        }

    def status(self, *, config=None):
        self.calls += 1
        return self.payload


def make_client(*, role='admin', authenticated=True, data=None, arr_login=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-arr-status-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule('/arr-signin', endpoint='arr_signin', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=139, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={'arr': arr_login} if arr_login else {},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_arr_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 139 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '139' else None,
        login_manager=manager,
        data_access=data or FakeArrStatusData(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '139:fp'}, 'native-arr-status-secret')
        )
    return client


def test_admin_get_returns_full_api_ok_status_payload():
    data = FakeArrStatusData()
    response = make_client(data=data).get('/api/arr/status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        **data.payload,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == 1


def test_anonymous_redirect_prefers_arr_blueprint_login_view():
    data = FakeArrStatusData()
    response = make_client(
        authenticated=False, data=data, arr_login='/arr-signin'
    ).get('/api/arr/status?from=admin', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == '/arr-signin?next=%2Fapi%2Farr%2Fstatus%3Ffrom%3Dadmin'
    session = load_session_cookie(
        response.cookies['session'], 'native-arr-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_non_admin_gets_admin_redirect_and_danger_flash_without_adapter_call():
    data = FakeArrStatusData()
    response = make_client(role='user', data=data).get(
        '/api/arr/status?from=admin', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-arr-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_admin_bearer_without_admin_scope_gets_forbidden_envelope(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_arr, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeArrStatusData()
    response = make_client(data=data).get('/api/arr/status')
    assert response.status_code == 403
    assert response.json()['error'] == 'This token does not have the admin scope'
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == 0


def test_head_preserves_status_headers_and_length_without_body():
    data = FakeArrStatusData()
    client = make_client(data=data)
    get_response = client.get('/api/arr/status')
    head_response = client.head('/api/arr/status')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.calls == 2


def test_status_adapter_passes_explicit_config_to_readiness_helpers(monkeypatch):
    from oneirodex.utils import arr_connectors, arr_hardlink_pipeline, module_status

    config = {'ENABLE_ARR_MODULE': True, 'ENABLE_ARR_HARDLINK_PIPELINE': True}
    observed = []
    monkeypatch.setattr(module_status, 'arr_module_on', lambda *, config: config['ENABLE_ARR_MODULE'])
    monkeypatch.setattr(arr_connectors, 'connector_status', lambda *, config: (
        observed.append(config) or [{'id': 'native_indexers', 'configured': True}]
    ))
    monkeypatch.setattr(arr_hardlink_pipeline, 'pipeline_enabled', lambda *, config: config['ENABLE_ARR_HARDLINK_PIPELINE'])
    monkeypatch.setattr(arr_hardlink_pipeline, 'hardlink_helpers_enabled', lambda *, config: False)
    monkeypatch.setattr(arr_hardlink_pipeline, 'hardlink_apply_allowed', lambda *, config: False)

    result = ArrStatusData().status(config=config)

    assert result['enabled'] is True
    assert result['hardlink_pipeline_enabled'] is True
    assert observed == [config]
