"""DB-free contract tests for the non-Jinja member SPA document."""
from types import SimpleNamespace

from flask import Flask, flash, session
from flask_login import LoginManager, UserMixin, login_user

from oneirodex.utils import member_spa


class Member(UserMixin):
    id = 42
    name = 'Arcade <Guest>'
    role = 'librarian'
    avatarpath = 'newstyle/avatars/controller.svg'
    preferences = SimpleNamespace(
        theme='default', icon_pack='outline', tile_size='75',
        show_tile_titles=False, locale='fr-CA', items_per_page=40,
        default_sort='last_played', default_sort_order='desc',
    )


def test_non_jinja_member_shell_keeps_bootstrap_contract_and_escapes_values(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY='member-shell-test', ENABLE_VR_BROWSE=True,
        ENABLE_ACTIVITY_FEED=False, ENABLE_NEW_CHROME=True,
        ONEIRODEX_SOURCE_URL='https://example.invalid/source?x="quoted"',
    )
    manager = LoginManager(app)
    manager.user_loader(lambda _identity: Member())
    app.add_url_rule('/manifest.webmanifest', endpoint='member.app_manifest', view_func=lambda: '')
    app.add_url_rule('/theme-fonts.css', endpoint='apis.theme_fonts_css', view_func=lambda: '')
    monkeypatch.setattr(member_spa, 'get_global_settings', lambda: {
        'show_trailers': True, 'show_help_button': False,
        'show_play_status': False, 'enable_delete_game_on_disk': True,
    })
    monkeypatch.setattr(member_spa, 'theme_asset_url', lambda path, **_kwargs: f'/theme/{path}?v=1')
    monkeypatch.setattr(member_spa, 'dist_asset_url', lambda path: f'/dist/{path}')
    monkeypatch.setattr(member_spa, 'icon_pack_css_url', lambda _pack: '/icon-pack.css')
    monkeypatch.setattr(member_spa, 'icon_pack_previews_css_url', lambda: '/icon-previews.css')
    monkeypatch.setattr(member_spa, 'avatar_url', lambda _path: '/avatar.svg')

    with app.test_request_context('/discover'):
        login_user(Member())
        flash('<Scan finished>', 'error')
        flash('Image updated', 'image-refresh')
        session['image_refresh_game_uuid'] = 'game-123'
        response = member_spa.render_member_spa(
            library_count=2,
            games_count=9,
            scan_has_run=True,
            unmatched_count=3,
            filters={'search': 'A&B', 'page': 2},
        )
        html = response.get_data(as_text=True)

    assert response.mimetype == 'text/html'
    assert '<html lang="en" data-theme="default" data-era=' in html
    assert 'id="member-app-root"' in html
    assert 'data-tile-size="75"' in html
    assert 'data-is-admin="false"' in html
    assert 'data-is-librarian="true"' in html
    assert 'data-user-id="42"' in html
    assert 'data-show-help="false"' in html
    assert 'data-enable-vr="true"' in html
    assert 'data-enable-activity="false"' in html
    assert 'data-show-play-status="false"' in html
    assert 'data-show-tile-titles="false"' in html
    assert 'data-username="Arcade &lt;Guest&gt;"' in html
    assert 'data-source-url="https://example.invalid/source?x=&#34;quoted&#34;"' in html
    assert 'data-current-filters="{&#34;search&#34;:&#34;A&amp;B&#34;,&#34;page&#34;:2}"' in html
    assert 'class="alert alert-danger' in html
    assert '&lt;Scan finished&gt;' in html
    assert 'Image updated' in html
    assert 'data-game-uuid="game-123"' in html
    assert 'name="csrf_token" value="' in html
    assert 'href="/dist/member-app/member-app.css"' in html
    assert 'src="/dist/member-app/member-app.js"' in html
    assert html.index('bootstrap.min.css') < html.index('bootstrap.bundle.min.js')
    assert html.index('/dist/member-app/member-app.css') < html.index('/theme/css/od-era.css')
    assert html.index('/theme/css/od-era.css') < html.index('/theme/js/od_loading_motifs.js')
    assert 'id="od-era-atmosphere"' in html
    assert 'id="preferencesModalContainer"' in html
    assert '{{' not in html and '{%' not in html


def test_non_jinja_member_shell_applies_route_overrides(monkeypatch):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'member-shell-test'
    manager = LoginManager(app)
    manager.user_loader(lambda _identity: None)
    app.add_url_rule('/manifest.webmanifest', endpoint='member.app_manifest', view_func=lambda: '')
    app.add_url_rule('/theme-fonts.css', endpoint='apis.theme_fonts_css', view_func=lambda: '')
    monkeypatch.setattr(member_spa, 'get_global_settings', lambda: {})
    monkeypatch.setattr(member_spa, 'theme_asset_url', lambda path, **_kwargs: f'/theme/{path}')
    monkeypatch.setattr(member_spa, 'dist_asset_url', lambda path: f'/dist/{path}')
    monkeypatch.setattr(member_spa, 'icon_pack_css_url', lambda _pack: None)
    monkeypatch.setattr(member_spa, 'icon_pack_previews_css_url', lambda: None)
    monkeypatch.setattr(member_spa, 'avatar_url', lambda _path: '/avatar.svg')

    with app.test_request_context('/library'):
        html = member_spa.render_member_spa(
            user_per_page=77,
            user_default_sort='release_date',
            user_default_sort_order='desc',
            filters=None,
        ).get_data(as_text=True)

    assert 'data-per-page="77"' in html
    assert 'data-default-sort="release_date"' in html
    assert 'data-default-sort-order="desc"' in html
    assert 'data-current-filters="null"' in html
