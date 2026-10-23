from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect, request
from flask_login import LoginManager
from werkzeug.exceptions import HTTPException

from oneirodex.runtime_native.reference_sets_read import create_reference_sets_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.utils.error_envelope import http_error_code, wants_json_error


def _client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-reference-sets-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='reference-sets-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_reference_sets_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=data or SimpleNamespace(read=lambda: {
            'sets': [{'id': 3, 'name': 'USA'}],
            'platforms': [{'id': 'NES', 'label': 'Nintendo Entertainment System'}],
            'catalog_platforms': [{'id': 'NES', 'label': 'Nintendo Entertainment System'}],
            'regions': ['USA', 'Europe'],
            'sources': ['no-intro'],
            'max_dat_bytes': 33554432,
        }),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session',
        dump_session_cookie(session_data, flask_app.config['SECRET_KEY']),
    )
    return client


def _install_legacy_error_envelope(app):
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if not wants_json_error(request):
            return error.get_response()
        from oneirodex.utils.api_response import api_error

        return api_error(
            error.description or error.name or 'Request failed',
            code=http_error_code(error.code), status=error.code or 500,
        )


def test_reference_sets_read_keeps_payload_cache_and_head_contract():
    client = _client()
    response = client.get('/api/admin/reference-sets')
    head = client.head('/api/admin/reference-sets')

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['sets'] == [{'id': 3, 'name': 'USA'}]
    assert response.json()['platforms'][0]['id'] == 'NES'
    assert response.json()['catalog_platforms'][0]['id'] == 'NES'
    assert response.json()['regions'] == ['USA', 'Europe']
    assert response.json()['sources'] == ['no-intro']
    assert response.json()['max_dat_bytes'] == 33554432
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_reference_sets_read_requires_admin():
    response = _client(role='user').get('/api/admin/reference-sets', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')


def test_reference_sets_upload_checks_csrf_then_preserves_upload_contract(monkeypatch):
    from oneirodex import db

    calls = []

    def upload(**kwargs):
        calls.append(kwargs)
        if kwargs['platform'] == 'UNKNOWN':
            raise ValueError('invalid platform')
        return 'created', {'id': 17, 'name': 'Sample DAT'}

    client = _client(data=SimpleNamespace(read=lambda: {}, upload=upload))
    monkeypatch.setattr(db.session, 'rollback', lambda: None)
    form = {'library_platform': 'NES', 'region': 'USA', 'source': 'no-intro'}
    files = {'file': ('game.dat', b'contents')}
    invalid = client.post('/api/admin/reference-sets', data=form, files=files)
    uploaded = client.post(
        '/api/admin/reference-sets',
        data=form, files=files,
        headers={'X-CSRFToken': client.csrf_token},
    )
    bad_platform = client.post(
        '/api/admin/reference-sets',
        data={**form, 'library_platform': 'UNKNOWN'}, files=files,
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert invalid.status_code == 400
    assert uploaded.status_code == 201
    assert uploaded.json()['reference_set']['id'] == 17
    assert bad_platform.status_code == 400
    assert calls[0]['raw'] == b'contents'


def test_reference_sets_upload_reports_legacy_xml_parse_detail(monkeypatch):
    from oneirodex import db
    from xml.etree.ElementTree import ParseError

    monkeypatch.setattr(db.session, 'rollback', lambda: None)
    client = _client(data=SimpleNamespace(
        read=lambda: {},
        upload=lambda **_kwargs: (_ for _ in ()).throw(ParseError('no element found: line 1, column 19')),
    ))
    response = client.post(
        '/api/reference-sets',
        data={'library_platform': 'NES', 'region': 'USA', 'source': 'mame'},
        files={'file': ('bad.xml', b'<datafile><machine>')},
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 400
    assert response.json()['message'] == 'Failed to parse DAT: no element found: line 1, column 19'


def test_legacy_reference_sets_invalid_form_redirect_keeps_html_content_type():
    client = _client()
    missing_csrf = client.post('/admin/reference_sets', data={'field': 'value'})
    invalid_form = client.post(
        '/admin/reference_sets', data={'csrf_token': client.csrf_token},
        headers={'X-CSRFToken': client.csrf_token}, follow_redirects=False,
    )

    assert missing_csrf.status_code == 400
    assert invalid_form.status_code == 302
    expected = flask_redirect('/admin/reference_sets', code=302)
    assert invalid_form.headers['content-type'] == expected.headers['Content-Type']
    assert invalid_form.content == expected.get_data()
    assert invalid_form.headers['location'] == '/admin/reference_sets'

    delete_client = _client(data=SimpleNamespace(read=lambda: {}, delete=lambda _set_id: False))
    missing_set = delete_client.post(
        '/admin/reference_sets',
        data={'csrf_token': delete_client.csrf_token, 'action': 'delete', 'set_id': '3'},
        headers={'X-CSRFToken': delete_client.csrf_token}, follow_redirects=False,
    )
    assert missing_set.status_code == 302
    assert missing_set.headers['content-type'] == expected.headers['Content-Type']
    assert missing_set.content == expected.get_data()
    assert missing_set.headers['location'] == '/admin/reference_sets'


def test_reference_set_delete_checks_csrf_and_keeps_not_found_contract():
    calls = []
    client = _client(data=SimpleNamespace(read=lambda: {}, delete=lambda set_id: calls.append(set_id) or set_id == 17))
    invalid = client.delete('/api/admin/reference-sets/17')
    deleted = client.delete(
        '/api/admin/reference-sets/17', headers={'X-CSRFToken': client.csrf_token}
    )
    missing = client.delete(
        '/api/admin/reference-sets/18', headers={'X-CSRFToken': client.csrf_token}
    )
    assert invalid.status_code == 400
    assert deleted.status_code == 200
    assert deleted.json()['id'] == 17
    assert missing.status_code == 404
    assert calls == [17, 18]


def test_reference_set_delete_rejects_paths_flask_integer_converter_does_not_match():
    from oneirodex.routes_apis.reference_sets import apis_bp

    legacy_app = Flask(__name__)
    legacy_app.config['SECRET_KEY'] = 'legacy-reference-sets-secret'
    login_manager = LoginManager()
    login_manager.init_app(legacy_app)
    login_manager.login_view = 'login'
    login_manager.user_loader(lambda _user_id: None)
    _install_legacy_error_envelope(legacy_app)
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_client = legacy_app.test_client()
    native_client = _client()

    for path in (
        '/api/reference-sets/not-an-integer',
        '/api/reference-sets/-1',
        '/api/admin/reference-sets/not-an-integer',
        '/api/admin/reference-sets/-1',
    ):
        legacy = legacy_client.delete(path)
        native = native_client.delete(path)
        assert native.status_code == legacy.status_code == 404
        assert native.headers['content-type'].startswith('application/json')
        assert native.headers['content-type'] == legacy.headers['Content-Type']
        assert native.json() == legacy.json
        assert native.headers.get('location') == legacy.headers.get('Location')


def test_reference_sets_member_api_keeps_legacy_bare_list_and_upload_shape():
    calls = []
    data = SimpleNamespace(
        read=lambda: {},
        read_sets=lambda: {'sets': [{'id': 21, 'library_platform': 'NES'}]},
        upload=lambda **kwargs: (calls.append(kwargs) or ('created', {'id': 22, 'name': 'Named DAT'})),
        delete=lambda _set_id: True,
    )
    client = _client(data=data)
    listed = client.get('/api/reference-sets')
    uploaded = client.post(
        '/api/reference-sets',
        data={'platform': 'NES', 'name': 'Named DAT'},
        files={'dat': ('game.dat', b'dat-bytes')},
        headers={'X-CSRFToken': client.csrf_token},
    )
    deleted = client.delete(
        '/api/reference-sets/22', headers={'X-CSRFToken': client.csrf_token}
    )

    assert listed.status_code == 200
    assert listed.json() == {'sets': [{'id': 21, 'library_platform': 'NES'}]}
    assert uploaded.status_code == 201
    assert uploaded.json() == {'id': 22, 'name': 'Named DAT'}
    assert calls[0]['name'] == 'Named DAT'
    assert calls[0]['raw'] == b'dat-bytes'
    assert deleted.status_code == 200
    assert deleted.json()['id'] == 22


def test_set_completion_keeps_query_parsing_report_and_error_contract():
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs['platform'] == 'MISSING':
            return None
        if kwargs['platform'] == 'INVALID':
            raise ValueError('Invalid platform')
        return {'platform': kwargs['platform'], 'matched': 4}

    client = _client(data=SimpleNamespace(read=lambda: {}, completion=completion))
    report = client.get('/api/set-completion?platform=NES&region=USA&include_matched=yes&missing_limit=12')
    missing_platform = client.get('/api/set-completion')
    missing_set = client.get('/api/set-completion?platform=MISSING')
    invalid = client.get('/api/set-completion?platform=INVALID')

    assert report.status_code == 200
    assert report.json() == {'platform': 'NES', 'matched': 4}
    assert calls[0]['include_matched'] is True
    assert calls[0]['missing_limit'] == 12
    assert missing_platform.status_code == 400
    assert missing_set.status_code == 404
    assert missing_set.json()['valid_regions']
    assert invalid.status_code == 400


def test_reference_set_rehash_and_repair_preview_keep_admin_action_contracts():
    calls = []
    data = SimpleNamespace(
        read=lambda: {},
        rehash=lambda platform: calls.append(('rehash', platform)) or {'platform': platform, 'hashed': 2, 'skipped': 1},
        repair_preview=lambda **kwargs: calls.append(('preview', kwargs)) or {'candidate_count': 3},
    )
    client = _client(data=data)
    missing_platform = client.post(
        '/api/reference-sets/rehash', json={}, headers={'X-CSRFToken': client.csrf_token}
    )
    rehashed = client.post(
        '/api/reference-sets/rehash', json={'platform': 'NES'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    vendor_json_rehash = client.post(
        '/api/reference-sets/rehash', data='{"platform":"NES"}',
        headers={
            'Content-Type': 'application/vnd.api+json',
            'X-CSRFToken': client.csrf_token,
        },
    )
    preview = client.post(
        '/api/reference-sets/repair-preview',
        json={'library_platform': 'NES', 'region': 'USA', 'limit': 5},
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid_preview = client.post(
        '/api/reference-sets/repair-preview', json={'unknown': 'field'},
        headers={'X-CSRFToken': client.csrf_token},
    )
    non_object_preview = client.post(
        '/api/reference-sets/repair-preview', json=[],
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert missing_platform.status_code == 400
    assert rehashed.json() == {'platform': 'NES', 'hashed': 2, 'skipped': 1}
    assert vendor_json_rehash.json() == {'platform': 'NES', 'hashed': 2, 'skipped': 1}
    assert preview.json()['candidate_count'] == 3
    assert calls[0] == ('rehash', 'NES')
    assert calls[1] == ('rehash', 'NES')
    assert calls[2][0] == 'preview'
    assert calls[2][1]['limit'] == 5
    assert invalid_preview.status_code == 422
    assert 'unknown' in invalid_preview.json()['detail']
    assert non_object_preview.status_code == 422
    assert non_object_preview.json()['detail'] == {
        '__root__': 'Input should be a valid dictionary or instance of RepairPreviewBody',
    }


def test_reference_sets_data_uses_current_catalog_helpers(monkeypatch):
    from oneirodex import platform as platform_module
    from oneirodex.runtime_native.reference_sets_read import ReferenceSetsData
    from oneirodex.utils import functions, set_completion

    class Platform:
        name = 'NES'
        value = 'Nintendo Entertainment System'

    class NativePlatform:
        name = 'DOS'
        value = 'PC DOS'

    monkeypatch.setattr(platform_module, 'LibraryPlatform', [Platform, NativePlatform])
    monkeypatch.setattr(platform_module, 'NATIVE_PC_PLATFORMS', {'DOS'})
    monkeypatch.setattr(functions, 'igdb_platform_id_for', lambda platform: 18 if platform == 'NES' else None)
    monkeypatch.setattr(set_completion, 'list_reference_sets', lambda: [{'id': 9}])
    monkeypatch.setattr(set_completion, 'REGION_PREF_ORDER', ('USA', 'Japan'))
    monkeypatch.setattr(set_completion, 'VALID_SOURCES', {'no-intro', 'redump'})

    payload = ReferenceSetsData().read()
    assert [item['id'] for item in payload['platforms']] == ['NES', 'DOS']
    assert [item['id'] for item in payload['catalog_platforms']] == ['NES']
    assert payload['sets'] == [{'id': 9}]
    assert payload['regions'] == ['USA', 'Japan']
    assert payload['sources'] == ['no-intro', 'redump']
    assert payload['max_dat_bytes'] == 33554432



def test_legacy_reference_sets_form_upload_uses_hidden_csrf_and_redirects():
    calls = []
    data = SimpleNamespace(
        read=lambda: {},
        upload=lambda **kwargs: (calls.append(kwargs) or ('created', {
            'id': 23, 'name': 'Sample DAT', 'entry_count': 4,
        })),
        delete=lambda _set_id: True,
    )
    client = _client(data=data)
    response = client.post(
        '/admin/reference_sets',
        data={
            'csrf_token': client.csrf_token,
            'library_platform': 'NES', 'region': 'USA', 'source': 'no-intro',
        },
        files={'file': ('sample.dat', b'dat-payload')},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/reference_sets'
    expected = flask_redirect('/admin/reference_sets', code=302)
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()
    assert calls[0]['raw'] == b'dat-payload'
    assert calls[0]['uploader_id'] == 71
    from oneirodex.runtime_native.session_compat import load_session_cookie
    session = load_session_cookie(
        response.cookies.get('session'), 'native-reference-sets-secret', max_age=3600,
    )
    assert session['_flashes'] == [('success', 'Uploaded Sample DAT')]


def test_legacy_reference_sets_form_rejects_missing_csrf_before_upload():
    calls = []
    data = SimpleNamespace(
        read=lambda: {}, upload=lambda **kwargs: calls.append(kwargs), delete=lambda _id: True,
    )
    response = _client(data=data).post(
        '/admin/reference_sets',
        data={'library_platform': 'NES', 'region': 'USA', 'source': 'no-intro'},
        files={'file': ('sample.dat', b'dat-payload')},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert calls == []
