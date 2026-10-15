from oneirodex.utils.email_rendering import (
    render_daily_digest,
    render_invite_email,
    render_social_notification,
)


def test_daily_digest_escapes_dynamic_text_and_links():
    html = render_daily_digest(
        [{
            'title': '<script>title</script>',
            'body': 'hello <img src=x>',
            'link': 'https://example.test/?a=1&b="2"',
        }],
        'https://example.test/notifications?next="home"',
    )

    assert '<script>' not in html
    assert '&lt;script&gt;title&lt;/script&gt;' in html
    assert '&lt;img src=x&gt;' in html
    assert 'href="https://example.test/?a=1&amp;b=&quot;2&quot;"' in html
    assert 'href="https://example.test/notifications?next=&quot;home&quot;"' in html
    assert '<strong>1</strong> unread notification.' in html


def test_daily_digest_keeps_empty_and_plural_states():
    empty = render_daily_digest([], None)
    plural = render_daily_digest([{'title': 'A'}, {'title': 'B'}], None)

    assert '<strong>0</strong> unread notifications.' in empty
    assert '<ul>\n\n  </ul>' in empty
    assert '<strong>2</strong> unread notifications.' in plural
    assert 'Open notifications in Oneirodex' not in plural


def test_social_notification_escapes_content_and_keeps_optional_body():
    html = render_social_notification(
        title='A < B', body='<b>message</b>', link='https://example.test/?a=1&b=2',
    )

    assert '<title>A &lt; B</title>' in html
    assert '<strong>A &lt; B</strong>' in html
    assert '<p>&lt;b&gt;message&lt;/b&gt;</p>' in html
    assert 'href="https://example.test/?a=1&amp;b=2"' in html
    without_body = render_social_notification(title='Notice', body=None, link=None)
    assert '<strong>Notice</strong>' in without_body
    assert 'Open in Oneirodex' not in without_body


def test_invite_email_escapes_the_dynamic_url():
    html = render_invite_email('https://example.test/invite?a=1&next="home"')

    assert 'href="https://example.test/invite?a=1&amp;next=&quot;home&quot;"' in html
    assert 'Complete Your Registration' in html
    assert 'expire after 48 hours' in html
