"""Versioned static asset URLs for the non-template shell builders."""

from pathlib import Path
from unittest.mock import patch

from flask import Flask


def test_asset_url_helpers_resolve_theme_and_versioned_dist_files(tmp_path):
    from oneirodex.utils.asset_urls import dist_asset_url, theme_asset_url

    root = tmp_path / 'oneirodex_pkg'
    theme = root / 'static' / 'library' / 'themes' / 'afterglow' / 'css'
    theme.mkdir(parents=True)
    (theme / 'base.css').write_text('/* afterglow */', encoding='utf-8')
    default = root / 'static' / 'library' / 'themes' / 'default' / 'css'
    default.mkdir(parents=True)
    (default / 'base.css').write_text('/* default */', encoding='utf-8')
    bundle = root / 'static' / 'dist' / 'member-app'
    bundle.mkdir(parents=True)
    (bundle / 'member-app.css').write_text('/* built */', encoding='utf-8')
    (bundle / 'member-app.js').write_text('export const built = true', encoding='utf-8')

    app = Flask(__name__, root_path=str(root))
    app.config.update(SERVER_NAME='localhost', APPLICATION_ROOT='/', PREFERRED_URL_SCHEME='http')
    with app.app_context(), app.test_request_context('/'):
        theme_url = theme_asset_url('css/base.css', theme='afterglow')
        fallback_url = theme_asset_url('css/base.css', theme='missing')
        css_url = dist_asset_url('member-app/member-app.css')
        js_url = dist_asset_url('member-app/member-app.js')

    assert 'library/themes/afterglow/css/base.css' in theme_url and 'v=' in theme_url
    assert 'library/themes/default/css/base.css' in fallback_url and 'v=' in fallback_url
    assert 'dist/member-app/member-app.css' in css_url and 'v=' in css_url
    assert js_url.endswith('dist/member-app/member-app.js') and '?' not in js_url


def test_asset_helpers_do_not_register_framework_template_filters():
    source = (Path(__file__).resolve().parents[1] / 'oneirodex' / 'routes_theme.py')
    assert not source.exists()


def test_verify_file_checks_exists_and_readability():
    from oneirodex.utils.asset_urls import verify_file

    with patch('oneirodex.utils.asset_urls.os.path.exists', return_value=True):
        assert verify_file('/test/path') is True
    with patch('oneirodex.utils.asset_urls.os.path.exists', return_value=False):
        with patch('oneirodex.utils.asset_urls.os.access', return_value=False):
            assert verify_file('/test/path') is False
        with patch('oneirodex.utils.asset_urls.os.access', return_value=True):
            assert verify_file('/test/path') is True
