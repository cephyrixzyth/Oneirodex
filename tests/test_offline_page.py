from oneirodex.utils.offline_page import render_offline_page


def test_offline_page_is_self_contained_dark_and_member_free():
    html = render_offline_page('/static/js/od_offline_retry.js?v=1-2')

    assert '<meta name="theme-color" content="#0b0d10">' in html
    assert '--od-accent: #2fd67b' in html
    assert 'No route to your library' in html
    assert 'Installed copies keep no games and no covers' in html
    assert 'browse_games' not in html
    assert 'game-card' not in html
    assert '{{' not in html and '{%' not in html


def test_offline_page_escapes_the_retry_asset_url():
    html = render_offline_page('/static/js/retry.js?next="bad"&x=1')

    assert 'src="/static/js/retry.js?next=&quot;bad&quot;&amp;x=1"' in html
