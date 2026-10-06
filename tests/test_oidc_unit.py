"""OIDC foundation unit tests (no live IdP)."""

import json
import os
from types import SimpleNamespace

from oneirodex.utils import oidc
from oneirodex.utils.proxy import apply_proxy_fix, parse_trusted_proxy_count


class _Settings:
    oidc_enabled = True


def test_env_flag_required_for_enable():
    settings = _Settings()
    original = os.environ.get('OIDC_ENABLED')
    try:
        os.environ['OIDC_ENABLED'] = 'false'
        assert oidc.is_oidc_enabled(settings) is False
        os.environ['OIDC_ENABLED'] = 'true'
        assert oidc.is_oidc_enabled(settings) is True
        settings.oidc_enabled = False
        assert oidc.is_oidc_enabled(settings) is False
    finally:
        if original is None:
            os.environ.pop('OIDC_ENABLED', None)
        else:
            os.environ['OIDC_ENABLED'] = original


def test_map_claims_to_role_defaults_to_user():
    claims = {'email': 'user@example.com'}
    assert oidc.map_claims_to_role(claims) == 'user'


def test_map_claims_to_role_oneirodex_admin_group():
    claims = {'groups': ['oneirodex-admin']}
    assert oidc.map_claims_to_role(claims) == 'admin'


def test_map_claims_to_role_single_value():
    claims = {'groups': 'admin'}
    assert oidc.map_claims_to_role(claims, role_claim='groups') == 'admin'


def test_map_claims_to_role_picks_highest_privilege():
    claims = {'groups': ['user', 'librarian', 'child']}
    role_map = {
        'user': 'user',
        'librarian': 'librarian',
        'child': 'child',
    }
    assert oidc.map_claims_to_role(claims, role_claim='groups', role_map=role_map) == 'librarian'


def test_map_claims_to_role_custom_claim_and_map():
    claims = {'roles': ['oneirodex-admin']}
    role_map = {'oneirodex-admin': 'admin'}
    assert oidc.map_claims_to_role(claims, role_claim='roles', role_map=role_map) == 'admin'


def test_parse_role_map_from_json_string():
    parsed = oidc.parse_role_map(json.dumps({'MyAdmins': 'admin'}))
    assert parsed == {'myadmins': 'admin'}


def test_extract_user_identity_prefers_preferred_username():
    username, email = oidc.extract_user_identity(
        {'preferred_username': 'alice', 'email': 'alice@example.com'}
    )
    assert username == 'alice'
    assert email == 'alice@example.com'


def test_build_oidc_config_requires_issuer_client_redirect(monkeypatch):
    monkeypatch.setenv('OIDC_ENABLED', 'true')
    settings = SimpleNamespace(
        oidc_enabled=True,
        oidc_issuer_url='https://idp.example.com/realms/oneirodex',
        oidc_client_id='oneirodex',
        oidc_client_secret='secret',
        oidc_redirect_uri='https://oneirodex.example.com/login/oidc/callback',
        oidc_scopes='openid email profile',
        oidc_role_claim='groups',
        oidc_role_map=None,
        oidc_display_name='Sign in with SSO',
    )
    config = oidc.build_oidc_config(settings)
    assert config is not None
    assert config.issuer_url.endswith('/realms/oneirodex')
    assert config.client_id == 'oneirodex'


def test_build_oidc_config_rejects_http_issuer(monkeypatch):
    monkeypatch.setenv('OIDC_ENABLED', 'true')
    settings = SimpleNamespace(
        oidc_enabled=True,
        oidc_issuer_url='http://idp.example.com',
        oidc_client_id='oneirodex',
        oidc_client_secret='secret',
        oidc_redirect_uri='https://oneirodex.example.com/login/oidc/callback',
        oidc_scopes='openid email profile',
        oidc_role_claim='groups',
        oidc_role_map=None,
        oidc_display_name='Sign in with SSO',
    )

    assert oidc.build_oidc_config(settings) is None


def test_generate_pkce_pair_returns_verifier_and_challenge():
    verifier, challenge = oidc.generate_pkce_pair()
    assert isinstance(verifier, str) and len(verifier) > 20
    assert isinstance(challenge, str) and len(challenge) > 10


def test_format_oidc_callback_error_redirect_uri_mismatch():
    message = oidc.format_oidc_callback_error(
        Exception('redirect_uri mismatch: invalid redirect')
    )
    assert 'redirect URI mismatch' in message


def test_format_oidc_idp_error_access_denied():
    message = oidc.format_oidc_idp_error('access_denied')
    assert 'cancelled or denied' in message


def test_parse_trusted_proxy_count():
    assert parse_trusted_proxy_count(None) == 0
    assert parse_trusted_proxy_count('0') == 0
    assert parse_trusted_proxy_count('1') == 1
    assert parse_trusted_proxy_count('invalid') == 0

    app = SimpleNamespace(config={'TRUSTED_PROXIES': 0}, wsgi_app='original')
    assert apply_proxy_fix(app) is False
    assert app.wsgi_app == 'original'

    app = SimpleNamespace(config={'TRUSTED_PROXIES': 1}, wsgi_app='original')
    assert apply_proxy_fix(app) is True
    assert app.wsgi_app != 'original'
