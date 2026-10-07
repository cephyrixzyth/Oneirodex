"""Phase 1 of the security/legal playbook — HTTP response headers + upload cap.

The interesting assertions here are the *negative* ones. Permissions-Policy is
the header most likely to be "hardened" into breaking shipped features, so the
LiveKit and controller entries are pinned. CSP enforces by default: inline
``<script>`` and ``onclick=`` are gone from Jinja, and WebRetro is a static
document that never receives this Flask policy.

See docs/strategy/security-legal-playbook.md (S1, S3).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from oneirodex.utils.security_headers import (
    BASELINE_HEADERS,
    PERMISSIONS_POLICY,
    apply_security_headers,
    baseline_static_headers,
    build_csp,
)


@pytest.mark.parametrize('compose_file', ['docker-compose.yml', 'docker-compose.single.yml'])
def test_deployment_compose_defaults_authentication_cookies_to_secure(compose_file):
    root = Path(__file__).resolve().parents[1]
    compose = (root / compose_file).read_text(encoding='utf-8')

    assert (
        '- SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-true}' in compose
        or 'SESSION_COOKIE_SECURE: ${SESSION_COOKIE_SECURE:-true}' in compose
    )
    assert (
        '- REMEMBER_COOKIE_SECURE=${REMEMBER_COOKIE_SECURE:-true}' in compose
        or 'REMEMBER_COOKIE_SECURE: ${REMEMBER_COOKIE_SECURE:-true}' in compose
    )


def test_deployment_env_examples_default_authentication_cookies_to_secure():
    root = Path(__file__).resolve().parents[1]
    for name in (
        '.env.example', '.env.docker.example', '.env.nas.example',
        '.env.unraid.example',
    ):
        values = (root / name).read_text(encoding='utf-8')
        assert 'SESSION_COOKIE_SECURE=true' in values
        assert 'REMEMBER_COOKIE_SECURE=true' in values
        assert 'CHAT_ATTACHMENT_STORAGE_MAX_FILES=0' in values


def _app(**config) -> Flask:
    """A bare Flask app with the headers applied — no DB, no blueprints."""
    app = Flask(__name__)
    app.config.update(config)
    apply_security_headers(app)

    @app.route('/probe')
    def probe():
        return 'ok'

    return app


def _headers(**config):
    with _app(**config).test_client() as client:
        return client.get('/probe').headers


# --- baseline -------------------------------------------------------------

@pytest.mark.parametrize('name,value', sorted(BASELINE_HEADERS.items()))
def test_baseline_headers_present(name, value):
    assert _headers()[name] == value


def test_nosniff_is_set():
    # Chat attachments allow .txt/.csv/.pdf; none may be sniffed into an
    # active content type.
    assert _headers()['X-Content-Type-Options'] == 'nosniff'


def test_static_handler_gets_the_same_baseline():
    """/static/* is served natively in asgi.py and never reaches Flask."""
    as_bytes = dict(baseline_static_headers())
    for name, value in BASELINE_HEADERS.items():
        assert as_bytes[name.encode('ascii')] == value.encode('ascii')


def test_existing_header_is_not_overwritten():
    app = _app()

    @app.route('/custom')
    def custom():
        return 'ok', 200, {'Referrer-Policy': 'no-referrer'}

    with app.test_client() as client:
        assert client.get('/custom').headers['Referrer-Policy'] == 'no-referrer'


# --- permissions policy ---------------------------------------------------

@pytest.mark.parametrize('feature', ['microphone', 'camera', 'display-capture'])
def test_livekit_features_stay_allowed(feature):
    """Voice lobby and screenshare. Denying these breaks a shipped feature."""
    assert f'{feature}=(self)' in _headers()['Permissions-Policy']


def test_gamepad_and_fullscreen_stay_allowed():
    """Controller input and Big Picture."""
    policy = _headers()['Permissions-Policy']
    assert 'gamepad=(self)' in policy
    assert 'fullscreen=(self)' in policy


@pytest.mark.parametrize('feature', ['geolocation', 'payment', 'usb'])
def test_unused_features_are_denied(feature):
    assert f'{feature}=()' in PERMISSIONS_POLICY


# --- CSP ------------------------------------------------------------------

def test_csp_enforces_by_default():
    headers = _headers()
    assert 'Content-Security-Policy' in headers
    assert 'Content-Security-Policy-Report-Only' not in headers


def test_csp_report_only_when_asked():
    headers = _headers(CSP_ENFORCE=False)
    assert 'Content-Security-Policy-Report-Only' in headers
    assert 'Content-Security-Policy' not in headers


def test_csp_enforces_when_asked():
    headers = _headers(CSP_ENFORCE=True)
    assert 'Content-Security-Policy' in headers
    assert 'Content-Security-Policy-Report-Only' not in headers


def test_csp_can_be_switched_off_entirely():
    headers = _headers(CSP_ENABLED=False)
    assert 'Content-Security-Policy' not in headers
    assert 'Content-Security-Policy-Report-Only' not in headers


@pytest.mark.parametrize('directive', [
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])
def test_csp_carries_the_cheap_wins(directive):
    assert directive in build_csp()


def test_csp_allows_what_the_app_actually_loads():
    """Provider art and the LiveKit socket. No eval, no off-box script CDN."""
    csp = build_csp()
    assert "'unsafe-inline'" not in csp.split('script-src', 1)[-1].split(';', 1)[0]
    assert "'unsafe-eval'" not in csp
    assert "'wasm-unsafe-eval'" not in csp
    assert 'cdn.ckeditor.com' not in csp
    assert 'img-src' in csp and 'https:' in csp
    assert 'wss:' in csp


# --- HSTS -----------------------------------------------------------------

def test_hsts_requires_secure_cookies():
    """A LAN box reached by IP over HTTP must not be pinned to HTTPS."""
    assert 'Strict-Transport-Security' not in _headers(
        SESSION_COOKIE_SECURE=False, HSTS_SECONDS=31536000
    )


def test_hsts_sent_when_deployment_is_https():
    headers = _headers(SESSION_COOKIE_SECURE=True, HSTS_SECONDS=31536000)
    assert headers['Strict-Transport-Security'] == (
        'max-age=31536000; includeSubDomains'
    )


def test_hsts_suppressed_by_zero_max_age():
    assert 'Strict-Transport-Security' not in _headers(
        SESSION_COOKIE_SECURE=True, HSTS_SECONDS=0
    )


# --- upload ceiling -------------------------------------------------------

def test_max_content_length_is_configured():
    """Unset is what made the 413 handler unreachable."""
    from config import Config

    assert Config.MAX_CONTENT_LENGTH == Config.MAX_UPLOAD_MB * 1024 * 1024
    assert Config.MAX_CONTENT_LENGTH > 0


def test_global_cap_clears_the_largest_per_route_limit():
    """Firmware at 64MB is the biggest legitimate upload."""
    from config import Config
    from oneirodex.utils.emulator_bios import DEFAULT_BIOS_MAX_BYTES

    assert Config.MAX_CONTENT_LENGTH > DEFAULT_BIOS_MAX_BYTES


def test_payload_too_large_has_an_error_code():
    from oneirodex.utils.api_response import ERROR_CODES

    assert ERROR_CODES['payload_too_large'] == 413
