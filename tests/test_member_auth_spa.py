from pathlib import Path
from flask import Flask, flash
from flask_wtf.csrf import CSRFProtect

from oneirodex.routes_login import login_bp
from oneirodex.utils.member_auth_spa import render_member_auth_spa


def test_auth_shell_is_static_cache_safe_and_escapes_flashes():
    static_folder = Path(__file__).resolve().parents[1] / 'oneirodex' / 'static'
    app = Flask(__name__, static_folder=str(static_folder))
    app.secret_key = 'auth-shell-test'
    with app.test_request_context('/login'):
        flash('<img src=x onerror=alert(1)>', 'error')
        response = render_member_auth_spa()

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    assert 'id="member-auth-root"' in body
    assert '&lt;img src=x onerror=alert(1)&gt;' in body
    assert '<img src=x onerror=alert(1)>' not in body
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Vary'] == 'Cookie'


def test_auth_runtime_bootstrap_returns_csrf_and_nonsecret_provider_state(monkeypatch):
    import oneirodex.routes_login as routes

    app = Flask(__name__)
    app.secret_key = 'auth-bootstrap-test'
    CSRFProtect(app)
    app.register_blueprint(login_bp)
    monkeypatch.setattr(routes, 'global_settings_row', lambda: None)
    monkeypatch.setattr(routes, 'build_oidc_config', lambda _settings: None)

    response = app.test_client().get('/api/auth/runtime-bootstrap')
    assert response.status_code == 200
    assert response.json['ok'] is True
    assert response.json['csrf_token']
    assert response.json['oidc_enabled'] is False
    assert response.json['runtime'] == 'flask-session-compat'
    assert 'no-store' in response.headers['Cache-Control']
