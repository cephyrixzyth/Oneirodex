"""Host header must not decide the origin of an emailed link.

Covers the password-reset poisoning path: `/reset_password_request` is
unauthenticated, so before this the `Host` header of an attacker's own request
chose the origin of a *victim's* reset email. See oneirodex/utils/trusted_host.
"""

import pytest

from oneirodex.utils.trusted_host import (
    host_is_trusted,
    is_private_hostname,
    parse_trusted_hosts,
    split_host_port,
    trusted_origin_from_request,
)


def test_native_host_helpers_are_usable_without_flask(monkeypatch):
    """The FastAPI runtime deliberately ships without Flask installed."""
    import builtins

    from oneirodex.utils import trusted_host

    real_import = builtins.__import__

    def without_flask(name, *args, **kwargs):
        if name == 'flask':
            raise ImportError('Flask is not installed in the native runtime')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', without_flask)
    assert trusted_host.configured_trusted_hosts() == ()
    assert trusted_host.trusted_origin_from_request() is None
    assert trusted_host.host_is_trusted('192.168.50.116:5006')


class TestParseTrustedHosts:
    def test_empty_is_empty(self):
        assert parse_trusted_hosts(None) == ()
        assert parse_trusted_hosts('') == ()

    def test_separators_and_normalisation(self):
        assert parse_trusted_hosts('A.example, b.example;c.example d.example') == (
            'a.example',
            'b.example',
            'c.example',
            'd.example',
        )

    def test_dedupes_and_strips_trailing_dot(self):
        assert parse_trusted_hosts('games.example.,games.example') == ('games.example',)

    def test_accepts_iterable(self):
        assert parse_trusted_hosts(['One.LAN', 'two.lan']) == ('one.lan', 'two.lan')


class TestSplitHostPort:
    @pytest.mark.parametrize(
        'raw,expected',
        [
            ('192.168.50.116:5006', ('192.168.50.116', '5006')),
            ('oneirodex', ('oneirodex', '')),
            ('games.example.com', ('games.example.com', '')),
            ('[::1]:5006', ('::1', '5006')),
            ('[fe80::1]', ('fe80::1', '')),
            # A bare IPv6 literal must not read its last group as a port.
            ('fe80::1', ('fe80::1', '')),
            ('', ('', '')),
        ],
    )
    def test_split(self, raw, expected):
        assert split_host_port(raw) == expected


class TestIsPrivateHostname:
    @pytest.mark.parametrize(
        'host',
        [
            '127.0.0.1',
            '192.168.50.116',
            '10.1.2.3',
            '172.16.0.9',
            '169.254.1.1',
            '::1',
            'localhost',
            'oneirodex',
            'nas.local',
            'box.lan',
            'host.home.arpa',
        ],
    )
    def test_private(self, host):
        assert is_private_hostname(host) is True

    @pytest.mark.parametrize(
        'host',
        ['attacker.example', 'evil.com', '8.8.8.8', '1.2.3.4', ''],
    )
    def test_public(self, host):
        assert is_private_hostname(host) is False


class TestHostIsTrusted:
    def test_lan_host_trusted_with_no_allowlist(self):
        assert host_is_trusted('192.168.50.116:5006') is True

    def test_public_host_rejected_with_no_allowlist(self):
        assert host_is_trusted('attacker.example') is False
        assert host_is_trusted('attacker.example:5006') is False

    def test_allowlist_admits_named_public_host(self):
        allowed = parse_trusted_hosts('games.example.com')
        assert host_is_trusted('games.example.com', allowed) is True
        assert host_is_trusted('games.example.com:443', allowed) is True

    def test_allowlist_closes_the_door_on_everything_else(self):
        """An explicit allowlist beats the private-host default."""
        allowed = parse_trusted_hosts('games.example.com')
        assert host_is_trusted('attacker.example', allowed) is False
        assert host_is_trusted('192.168.50.116:5006', allowed) is False

    def test_allowlist_entry_with_port_requires_that_port(self):
        allowed = parse_trusted_hosts('10.0.0.5:5006')
        assert host_is_trusted('10.0.0.5:5006', allowed) is True
        assert host_is_trusted('10.0.0.5:9999', allowed) is False

    def test_empty_host_never_trusted(self):
        assert host_is_trusted('') is False
        assert host_is_trusted(None) is False


class TestTrustedOriginFromRequest:
    def test_none_without_request_context(self):
        assert trusted_origin_from_request() is None

    def test_lan_host_gives_origin(self, app):
        with app.test_request_context('/', base_url='http://192.168.50.116:5006'):
            assert trusted_origin_from_request() == 'http://192.168.50.116:5006'

    def test_forged_host_gives_none(self, app):
        with app.test_request_context('/', base_url='http://attacker.example'):
            assert trusted_origin_from_request() is None

    def test_allowlist_from_config(self, app):
        app.config['TRUSTED_LINK_HOSTS'] = 'games.example.com'
        try:
            with app.test_request_context('/', base_url='http://games.example.com'):
                assert trusted_origin_from_request() == 'http://games.example.com'
            with app.test_request_context('/', base_url='http://192.168.50.116:5006'):
                assert trusted_origin_from_request() is None
        finally:
            app.config['TRUSTED_LINK_HOSTS'] = ''


class TestPublicOriginUsesTrustedHostOnly:
    def test_forged_host_does_not_become_the_origin(self, app):
        from oneirodex.utils.public_origin import invite_url, public_origin

        with app.test_request_context('/', base_url='http://attacker.example'):
            assert 'attacker.example' not in public_origin()
            assert 'attacker.example' not in invite_url('tok123')

    def test_lan_host_still_usable(self, app):
        from oneirodex.utils.public_origin import public_origin

        with app.test_request_context('/', base_url='http://192.168.50.116:5006'):
            assert public_origin() == 'http://192.168.50.116:5006'

    def test_native_request_origin_uses_only_a_trusted_matching_host(self, monkeypatch):
        from types import SimpleNamespace

        from oneirodex.utils import public_origin as origins

        monkeypatch.setattr(origins, 'configured_site_url', lambda: '')
        request = SimpleNamespace(
            base_url='http://192.168.50.116:5006/',
            headers={'host': '192.168.50.116:5006'},
        )
        assert origins.public_origin_for_request(request, {}) == 'http://192.168.50.116:5006'

        forged = SimpleNamespace(
            base_url='http://attacker.example/',
            headers={'host': 'attacker.example'},
        )
        assert origins.public_origin_for_request(forged, {}) == 'http://127.0.0.1'

        mismatch = SimpleNamespace(
            base_url='http://attacker.example/',
            headers={'host': 'games.example.test'},
        )
        assert origins.public_origin_for_request(
            mismatch, {'TRUSTED_LINK_HOSTS': 'games.example.test'},
        ) == 'http://127.0.0.1'

        malformed = SimpleNamespace(
            base_url='http://192.168.50.116:bad-port/',
            headers={'host': '192.168.50.116:bad-port'},
        )
        assert origins.public_origin_for_request(malformed, {}) == 'http://127.0.0.1'

    def test_native_request_prefers_configured_public_site_url(self, monkeypatch):
        from types import SimpleNamespace

        from oneirodex.utils import public_origin as origins

        monkeypatch.setattr(origins, 'configured_site_url', lambda: 'https://games.example.test')
        request = SimpleNamespace(
            base_url='http://attacker.example/',
            headers={'host': 'attacker.example'},
        )
        assert origins.public_origin_for_request(request, {}) == 'https://games.example.test'


class TestResetEmailUrl:
    def test_reset_url_builds_against_a_real_endpoint(self, app, monkeypatch):
        """`url_for('main.reset_password')` raised BuildError — no mail was sent."""
        from oneirodex.utils import smtp

        sent = {}
        monkeypatch.setattr(
            smtp, 'send_email', lambda to, subject, html: sent.update(html=html)
        )
        with app.test_request_context('/', base_url='http://192.168.50.116:5006'):
            smtp.send_password_reset_email('member@example.com', 'tok123')

        assert 'http://192.168.50.116:5006/reset_password/tok123' in sent['html']

    def test_forged_host_never_reaches_the_reset_link(self, app, monkeypatch):
        from oneirodex.utils import smtp

        sent = {}
        monkeypatch.setattr(
            smtp, 'send_email', lambda to, subject, html: sent.update(html=html)
        )
        with app.test_request_context('/', base_url='http://attacker.example'):
            smtp.send_password_reset_email('member@example.com', 'tok123')

        assert 'attacker.example' not in sent['html']
        assert '/reset_password/tok123' in sent['html']
