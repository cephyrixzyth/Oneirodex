from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native import styleguide


def test_styleguide_mobile_chrome_specimen_keeps_rail_inside_its_frame():
    source = (Path(__file__).resolve().parents[1] / 'oneirodex' / 'ui' / 'styleguide_body.html').read_text(encoding='utf-8')

    mobile_rule = source.split('@media (max-width: 900px)', 1)[1].split('</style>', 1)[0]
    assert '.sg__chrome .od-rail' in mobile_rule
    assert 'position: relative' in mobile_rule
    assert 'transform: none' in mobile_rule
    assert 'visibility: visible' in mobile_rule


def test_native_styleguide_keeps_admin_gate_theme_assets_flash_and_csrf(monkeypatch):
    from oneirodex.runtime_native import admin_pilot

    user = SimpleNamespace(
        id=9, role='admin',
        preferences=SimpleNamespace(theme='default', icon_pack='outline'),
    )
    session_data = {
        '_user_id': '9:fingerprint', '_fresh': True,
        '_flashes': [('info', 'Saved <settings>'), ('image-refresh', 'Done')],
        'image_refresh_game_uuid': 'game-9',
    }
    auth = SimpleNamespace(
        user=user, session_data=session_data, should_set_session_cookie=True,
        has_scope=lambda _scope: True,
    )
    runtime_app = SimpleNamespace(
        config={
            'SECRET_KEY': 'native-styleguide-secret',
            'SESSION_COOKIE_NAME': 'session',
            'PERMANENT_SESSION_LIFETIME': timedelta(days=1),
            'SESSION_REFRESH_EACH_REQUEST': True,
            'SESSION_PROTECTION': 'none',
            'WTF_CSRF_FIELD_NAME': 'csrf_token',
            'CSP_ENABLED': False,
        },
        login_manager=None,
        static_url_path='/static',
        root_path=str(Path(__file__).resolve().parents[1] / 'oneirodex'),
    )
    monkeypatch.setattr(styleguide, 'request_auth_context', lambda *_args, **_kwargs: auth)
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda _user_id: user, lambda _prefix: None, lambda _token: None,
    ))

    app = FastAPI()
    app.include_router(styleguide.create_styleguide_router(
        runtime_app,
        find_user=lambda _user_id: user,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        database_scope=lambda _app: nullcontext(),
    ))
    response = TestClient(app).get('/dev/styleguide')

    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.cookies.get('session')
    assert 'data-theme="default"' in response.text
    assert 'id="od-icon-pack-css"' in response.text
    assert 'name="csrf_token" value="' in response.text
    assert 'Saved &lt;settings&gt;' in response.text
    assert 'data-game-uuid="game-9"' in response.text
    assert 'container-flash-messages' in response.text
    assert '_flashes' not in session_data
