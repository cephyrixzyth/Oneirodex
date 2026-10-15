from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.arr_indexers_read import create_arr_indexers_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


def _client(*, role='admin', enabled=True, pipeline=True):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-arr-indexers-secret', CSP_ENABLED=False,
        ENABLE_ARR_HARDLINK_PIPELINE=pipeline,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='arr-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_arr_indexers_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=SimpleNamespace(
            read=lambda: {
                'indexers': [{'id': 'idx-1', 'name': 'Local', 'api_key_set': True}],
                'presets': [{'id': 'preset-1', 'name': 'Preset'}],
            },
            read_one=lambda indexer_id: (
                {'indexer': {'id': indexer_id, 'name': 'Local', 'api_key_set': True}}
                if indexer_id == 'idx-1' else None
            ),
            create=lambda payload: {'id': 'idx-new', 'name': payload.get('name', '')},
            update=lambda indexer_id, payload: {
                'id': indexer_id, 'name': payload.get('name', 'Updated'),
            },
            delete=lambda indexer_id: indexer_id == 'idx-1',
            bulk_import=lambda _payload: [{'id': 'idx-bulk', 'name': 'Bulk'}],
            enable_presets=lambda ids: [{'id': ids[0], 'name': 'Preset'}] if ids else [],
            module_status=lambda **_kwargs: {
                'enabled': False, 'db_enabled': False, 'env_enabled': False,
            },
            save_module_status=lambda enabled, **_kwargs: {
                'status': 'saved', 'enabled': enabled, 'db_enabled': enabled,
                'env_enabled': False,
            },
            search=lambda query, **kwargs: {
                'query': query, 'results': [{'title': 'Example', 'quality': {'score': 10}}],
                'excluded_by_quality': 1, 'warnings': ['Local warning'], 'options': kwargs,
            },
            download=lambda url: {'queued': True, 'url': url},
            hardlink_preview=lambda dest, *, limit, app: {
                'library_dest_dir': dest, 'count': 1, 'limit': limit,
                'proposals': [{'source': 'source.rom', 'dest': 'target.rom'}],
            },
            hardlink_apply=lambda proposals, *, only_ok, app: {
                'applied_count': len(proposals), 'skipped_count': 0,
                'error_count': 0, 'only_ok': only_ok,
            },
        ),
        module_enabled=lambda **_kwargs: enabled,
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


def test_arr_indexers_read_keeps_bare_payload_and_head():
    client = _client()
    response = client.get('/api/arr/indexers')
    head = client.head('/api/arr/indexers')
    detail = client.get('/api/arr/indexers/idx-1')
    missing = client.get('/api/arr/indexers/missing')
    assert response.status_code == 200
    assert response.json()['indexers'][0]['id'] == 'idx-1'
    assert response.json()['presets'][0]['id'] == 'preset-1'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))
    assert detail.status_code == 200
    assert detail.json()['indexer']['id'] == 'idx-1'
    assert missing.status_code == 404


def test_arr_indexers_read_keeps_module_and_admin_gates():
    disabled = _client(enabled=False).get('/api/arr/indexers')
    forbidden = _client(role='user').get('/api/arr/indexers', follow_redirects=False)
    assert disabled.status_code == 403
    assert forbidden.status_code == 302


def test_arr_module_status_is_available_while_the_module_is_disabled():
    response = _client(enabled=False).get('/api/arr/module')
    assert response.status_code == 200
    assert response.json() == {
        'enabled': False, 'db_enabled': False, 'env_enabled': False,
    }


def test_arr_module_put_checks_csrf_and_preserves_compatibility_payload():
    client = _client(enabled=False)
    missing = client.put('/api/arr/module', json={'enabled': True})
    saved = client.put(
        '/api/arr/module', json={'enabled': True},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid = client.put(
        '/api/arr/module', json={}, headers={'X-CSRFToken': client.csrf_token}
    )
    assert missing.status_code == 400
    assert saved.status_code == 200
    assert saved.json()['ok'] is True
    assert saved.json()['status'] == 'saved'
    assert saved.json()['enabled'] is True
    assert saved.json()['db_enabled'] is True
    assert saved.json()['env_enabled'] is False
    assert invalid.status_code == 400


def test_arr_indexer_mutations_check_csrf_and_keep_status_contracts():
    client = _client()
    payload = {'name': 'Added', 'protocol': 'torznab', 'url': 'https://indexer.example'}
    invalid_csrf = client.post('/api/arr/indexers', json=payload)
    created = client.post(
        '/api/arr/indexers', json=payload,
        headers={'X-CSRFToken': client.csrf_token},
    )
    updated = client.patch(
        '/api/arr/indexers/idx-1', json={'name': 'Changed'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    deleted = client.delete(
        '/api/arr/indexers/idx-1', headers={'X-CSRFToken': client.csrf_token}
    )
    missing = client.delete(
        '/api/arr/indexers/missing', headers={'X-CSRFToken': client.csrf_token}
    )
    assert invalid_csrf.status_code == 400
    assert created.status_code == 201
    assert created.json()['indexer']['id'] == 'idx-new'
    assert updated.status_code == 200
    assert updated.json()['indexer']['name'] == 'Changed'
    assert deleted.status_code == 200
    assert missing.status_code == 404


def test_arr_bulk_and_preset_actions_keep_created_contracts():
    client = _client()
    bulk = client.post(
        '/api/arr/indexers/bulk', json={'indexers': [{'name': 'Bulk'}]},
        headers={'X-CSRFToken': client.csrf_token},
    )
    presets = client.post(
        '/api/arr/indexers/enable-presets', json={'preset_ids': ['preset-1']},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid = client.post(
        '/api/arr/indexers/enable-presets', json={'preset_ids': 'preset-1'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert bulk.status_code == 201
    assert bulk.json()['status'] == 'imported'
    assert bulk.json()['count'] == 1
    assert presets.status_code == 201
    assert presets.json()['status'] == 'enabled'
    assert invalid.status_code == 400


def test_arr_search_keeps_quality_fields_query_alias_and_limit():
    client = _client()
    missing = client.get('/api/arr/search')
    response = client.get('/api/arr/search?query=zelda&limit=99&include_disallowed=on')

    assert missing.status_code == 400
    assert response.status_code == 200
    assert response.json()['query'] == 'zelda'
    assert response.json()['results'][0]['quality']['score'] == 10
    assert response.json()['excluded_by_quality'] == 1
    assert response.json()['warnings'] == ['Local warning']
    assert response.json()['options'] == {'limit': 50, 'include_disallowed': True}


def test_arr_download_checks_csrf_validates_outbound_url_and_keeps_accepted_status(monkeypatch):
    from oneirodex.utils import security

    client = _client()
    monkeypatch.setattr(security, 'validate_user_outbound_http_url', lambda _url: (True, 'https://safe.example/download'))
    invalid_csrf = client.post('/api/arr/download', json={'url': 'https://safe.example/download'})
    accepted = client.post(
        '/api/arr/download', json={'url': 'https://safe.example/download'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    monkeypatch.setattr(security, 'validate_user_outbound_http_url', lambda _url: (False, 'URL is not allowed'))
    rejected = client.post(
        '/api/arr/download', json={'url': 'https://127.0.0.1/private'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid_body = client.post('/api/arr/download', json={}, headers={'X-CSRFToken': client.csrf_token})

    assert invalid_csrf.status_code == 400
    assert accepted.status_code == 202
    assert accepted.json()['queued'] is True
    assert accepted.json()['url'] == 'https://safe.example/download'
    assert rejected.status_code == 400
    assert rejected.json()['error'] == 'URL is not allowed'
    assert invalid_body.status_code == 422


def test_arr_hardlink_preview_and_apply_preserve_gates_and_response_shapes():
    client = _client()
    invalid_csrf = client.post('/api/arr/hardlink/preview', json={'library_dest_dir': 'library'})
    preview = client.post(
        '/api/arr/hardlink/preview',
        json={'library_dest_dir': 'library', 'limit': 500},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid_preview = client.post(
        '/api/arr/hardlink/preview', json={}, headers={'X-CSRFToken': client.csrf_token}
    )
    apply = client.post(
        '/api/arr/hardlink/apply',
        json={'proposals': [{'source': 'source.rom', 'dest': 'target.rom'}]},
        headers={'X-CSRFToken': client.csrf_token},
    )
    disabled_client = _client(pipeline=False)
    disabled = disabled_client.post(
        '/api/arr/hardlink/preview',
        json={'library_dest_dir': 'library'},
        headers={'X-CSRFToken': disabled_client.csrf_token},
    )

    assert invalid_csrf.status_code == 400
    assert preview.status_code == 200
    assert preview.json()['count'] == 1
    assert preview.json()['limit'] == 200
    assert invalid_preview.status_code == 422
    assert apply.status_code == 201
    assert apply.json()['applied_count'] == 1
    assert disabled.status_code == 403


def test_hardlink_preview_uses_explicit_app_config_without_flask_context(tmp_path):
    from oneirodex.utils.arr_hardlink_pipeline import propose_hardlinks

    source_root = tmp_path / 'completed'
    dest_root = tmp_path / 'library'
    source_root.mkdir()
    dest_root.mkdir()
    source = source_root / 'game.rom'
    source.write_bytes(b'rom-data')
    app = Flask(__name__)
    app.config.update(
        ENABLE_ARR_HARDLINK_PIPELINE=True,
        ENABLE_HARDLINK_HELPERS=True,
        ALLOW_HARDLINK_APPLY=True,
        DATA_FOLDER_GAMES=str(tmp_path),
        ARR_REMOTE_PATH_MAP='',
    )

    result = propose_hardlinks(
        str(dest_root),
        torrents=[{'name': 'Game', 'content_path': str(source)}],
        app=app,
    )

    assert result['count'] == 1
    assert result['library_dest_dir'] == str(dest_root)
    assert result['proposals'][0]['source'] == str(source)
    assert result['proposals'][0]['dest'] == str(dest_root / 'game.rom')
    assert result['apply_allowed'] is True
