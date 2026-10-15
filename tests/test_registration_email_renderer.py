from oneirodex.routes_login import _registration_confirmation_email


def test_registration_confirmation_email_preserves_copy_and_escapes_url():
    html = _registration_confirmation_email('https://example.test/confirm/a?x="<&')
    assert '<title>Confirm your Oneirodex email</title>' in html
    assert 'Ready, Player One!' in html
    assert 'Confirm Your Email' in html
    assert 'href="https://example.test/confirm/a?x=&quot;&lt;&amp;"' in html
    assert 'href="https://example.test/confirm/a?x="<&"' not in html
