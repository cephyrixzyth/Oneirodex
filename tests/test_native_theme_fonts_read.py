from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.runtime_native.theme_fonts_read import (
    ThemeFontsData,
    create_theme_fonts_read_router,
)


class FakeFonts:
    def __init__(self):
        self.calls = 0

    def catalogue(self):
        self.calls += 1
        return {
            'fonts': [{'id': 'system-ui', 'label': 'System UI', 'installed': True}],
            'platform_hints': {'NES': 'press-start'},
            'fonts_dir': '/fonts',
            'note': 'Operator fonts are supported.',
        }


def _client(*, role='user'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-font-catalog-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=95, user_id='font-user', role=role, is_active=True,
        state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeFonts()
    router = create_theme_fonts_read_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 95 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '95' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '95:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
    ))
    return client, data


def test_theme_font_catalogue_preserves_member_payload_and_head_contract():
    client, data = _client(role='user')
    get = client.get('/api/theme/fonts')
    head = client.head('/api/theme/fonts')

    assert get.status_code == 200
    payload = get.json()
    assert payload['ok'] is True
    assert payload['fonts'] == [
        {'id': 'system-ui', 'label': 'System UI', 'installed': True},
    ]
    assert payload['platform_hints'] == {'NES': 'press-start'}
    assert payload['fonts_dir'] == '/fonts'
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
    assert data.calls == 2


def test_theme_font_catalogue_data_uses_explicit_path_without_flask_context(monkeypatch, tmp_path):
    from oneirodex.utils import theme_fonts

    monkeypatch.setattr(theme_fonts, 'available_fonts', lambda root: {
        'system-ui': {'label': 'System UI', 'stack': 'sans-serif', 'file': None},
    })
    app = Flask(__name__)
    app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('theme fonts catalogue pushed Flask app context')
    )

    payload = ThemeFontsData(str(tmp_path)).catalogue()

    assert payload['fonts'] == [
        {'id': 'system-ui', 'label': 'System UI', 'stack': 'sans-serif'},
    ]
    assert payload['fonts_dir'] == str(tmp_path)
