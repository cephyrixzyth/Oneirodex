"""theme_asset must resolve per render, from the Flask app root — not process CWD."""
import pathlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def theme_app(tmp_path):
    app_root = tmp_path / 'oneirodex_pkg'
    afterglow = app_root / 'static' / 'library' / 'themes' / 'afterglow' / 'css'
    afterglow.mkdir(parents=True)
    (afterglow / 'base.css').write_text('/* afterglow */', encoding='utf-8')
    default = app_root / 'static' / 'library' / 'themes' / 'default' / 'css'
    default.mkdir(parents=True)
    (default / 'base.css').write_text('/* default */', encoding='utf-8')

    app = Flask(__name__, root_path=str(app_root))
    app.config['SERVER_NAME'] = 'localhost'
    app.config['APPLICATION_ROOT'] = '/'
    app.config['PREFERRED_URL_SCHEME'] = 'http'
    return app


def test_theme_asset_finds_file_when_cwd_is_not_repo_root(theme_app, tmp_path, monkeypatch):
    elsewhere = tmp_path / 'not_the_repo'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    fake_user = MagicMock()
    fake_user.is_authenticated = True
    fake_user.preferences = MagicMock()
    fake_user.preferences.theme = 'afterglow'

    from oneirodex.routes_theme import theme_asset_filter

    with theme_app.app_context(), theme_app.test_request_context('/'):
        with patch('flask_login.current_user', fake_user):
            url = theme_asset_filter(None, 'css/base.css')

    assert 'library/themes/afterglow/css/base.css' in url


def test_theme_asset_is_not_constant_folded(theme_app):
    """A theme change must reach the *next* render, not the next restart.

    Every call site passes a literal, and Jinja constant-folds a filter applied
    to a constant at compile time. Flask then caches the compiled template for
    the life of the process, so without `@pass_context` the first render's theme
    was baked into every later one: `data-theme` on <html> tracked the new
    preference (a variable lookup, never folded) while every stylesheet link
    stayed on the old one. That is the whole of "changing the theme does nothing
    on reload".

    Rendering the same template source twice with different preferences is the
    only honest check — asserting on the decorator would pass against a filter
    that had been re-marked and still folded.
    """
    from oneirodex.routes_theme import theme_asset_filter

    # The marker is what makes the fold illegal; assert it is still the *reason*
    # rather than a decoration, then prove the behaviour it buys.
    assert getattr(theme_asset_filter, 'jinja_pass_arg', None) is not None

    theme_app.jinja_env.filters['theme_asset'] = theme_asset_filter
    template = theme_app.jinja_env.from_string("{{ 'css/base.css'|theme_asset }}")

    fake_user = MagicMock()
    fake_user.is_authenticated = True
    fake_user.preferences = MagicMock()

    rendered = []
    with theme_app.app_context(), theme_app.test_request_context('/'):
        with patch('flask_login.current_user', fake_user):
            for theme in ('afterglow', 'default'):
                fake_user.preferences.theme = theme
                rendered.append(template.render())

    assert 'themes/afterglow/css/base.css' in rendered[0]
    # The same compiled template, a different preference: the second render must
    # follow the preference rather than repeat the first render's answer.
    assert 'themes/default/css/base.css' in rendered[1]


def test_pass_context_makes_the_fold_impossible(theme_app):
    """Pin the Jinja mechanism, so an upgrade that changes it fails loudly here.

    `nodes._FilterTestCommon.as_const` raises `Impossible` for a filter marked
    `_PassArg.context`. If a future Jinja drops that rule, the filter above
    starts folding again and the theme silently sticks — a failure that is very
    hard to attribute from the symptom.
    """
    from jinja2 import nodes

    from oneirodex.routes_theme import theme_asset_filter

    theme_app.jinja_env.filters['theme_asset'] = theme_asset_filter
    parsed = theme_app.jinja_env.parse("{{ 'css/base.css'|theme_asset }}")
    filter_node = next(parsed.find_all(nodes.Filter))

    with theme_app.app_context(), theme_app.test_request_context('/'):
        with pytest.raises(nodes.Impossible):
            filter_node.as_const()


def test_dist_bundles_are_versioned_so_a_rebuild_is_visible(theme_app):
    """A built SPA bundle must carry a cache-busting token.

    asgi.py serves everything outside static/library/themes with
    `public, max-age=3600`, so an unversioned bundle URL means a browser keeps
    the previous member-app.css and .js for an hour after a deploy. The symptom
    is not "the cache is stale" — it is a change that half works, because a rule
    living in the theme (served no-cache) lands immediately while a rule in the
    bundle does not.
    """
    dist = pathlib.Path(theme_app.root_path) / 'static' / 'dist' / 'member-app'
    dist.mkdir(parents=True)
    (dist / 'member-app.css').write_text('/* built */', encoding='utf-8')

    from oneirodex.routes_theme import dist_asset_filter

    with theme_app.app_context(), theme_app.test_request_context('/'):
        url = dist_asset_filter(None, 'member-app/member-app.css')

    assert 'dist/member-app/member-app.css' in url
    assert 'v=' in url, f'no cache-busting token in {url}'
    assert not url.endswith('v=0'), 'token fell back to the missing-file value'


def test_dist_js_entry_is_linked_at_its_bare_path(theme_app):
    """The module entry must NOT carry a query string.

    Lazy route chunks `import` the entry by its bare path. A `?v=` on the
    `<script type="module">` made the browser evaluate the entry twice -- one
    module per URL -- so the React contexts created in the entry existed twice,
    and every lazily loaded page calling `useViewer()` / `useShellConfig()`
    threw "must be used within a <...Provider>" and blanked the SPA (`/chat`,
    `/calendar`, `/ways-to-play`). asgi.py serves the entry `no-cache`, so
    freshness does not need the token; module identity forbids it.
    """
    dist = pathlib.Path(theme_app.root_path) / 'static' / 'dist' / 'member-app'
    dist.mkdir(parents=True, exist_ok=True)
    (dist / 'member-app.js').write_text('export const built = true', encoding='utf-8')

    from oneirodex.routes_theme import dist_asset_filter

    with theme_app.app_context(), theme_app.test_request_context('/'):
        url = dist_asset_filter(None, 'member-app/member-app.js')

    assert url.endswith('dist/member-app/member-app.js'), url
    assert '?' not in url, f'module entry must be a single module identity: {url}'


def test_dist_asset_is_not_constant_folded(theme_app):
    """Same trap as theme_asset: every call site passes a literal."""
    from jinja2 import nodes

    from oneirodex.routes_theme import dist_asset_filter

    theme_app.jinja_env.filters['dist_asset'] = dist_asset_filter
    parsed = theme_app.jinja_env.parse("{{ 'member-app/member-app.css'|dist_asset }}")
    filter_node = next(parsed.find_all(nodes.Filter))

    with theme_app.app_context(), theme_app.test_request_context('/'):
        with pytest.raises(nodes.Impossible):
            filter_node.as_const()
