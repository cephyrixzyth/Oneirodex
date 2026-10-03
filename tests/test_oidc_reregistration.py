from oneirodex.utils import oidc


class FakeOAuth:
    def __init__(self):
        self.clients = {}

    def init_app(self, app):
        self.app = app

    def register(self, **kwargs):
        self.clients[kwargs['name']] = kwargs


def test_oidc_config_change_replaces_oauth_and_registers_new_client(app, monkeypatch):
    monkeypatch.setattr(oidc, 'AUTHLIB_AVAILABLE', True)
    monkeypatch.setattr(oidc, 'OAuth', FakeOAuth)
    monkeypatch.setattr(oidc, '_oauth', None)
    monkeypatch.setattr(oidc, '_oidc_registered_key', None)

    first = oidc.OidcConfig(
        enabled=True, issuer_url='https://idp-a.example', client_id='client-a',
        client_secret='secret-a', redirect_uri='https://app.example/callback',
        scopes='openid email', role_claim='groups', role_map={}, display_name='A',
    )
    second = oidc.OidcConfig(
        enabled=True, issuer_url='https://idp-b.example', client_id='client-b',
        client_secret='secret-b', redirect_uri='https://app.example/callback',
        scopes='openid profile', role_claim='groups', role_map={}, display_name='B',
    )

    oidc.register_oidc_provider(app, first)
    first_oauth = oidc.get_oauth_client()
    oidc.register_oidc_provider(app, second)
    second_oauth = oidc.get_oauth_client()

    assert second_oauth is not first_oauth
    client = second_oauth.clients['oidc']
    assert client['client_id'] == 'client-b'
    assert client['client_secret'] == 'secret-b'
    assert client['client_kwargs']['scope'] == 'openid profile'
