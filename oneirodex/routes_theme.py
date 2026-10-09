"""Theme-asset template helpers.

Extracted verbatim from ``oneirodex/routes.py`` (wave A2.1e). These are all
**app-level** Jinja helpers -- one template global (``verify_file``) and three
filters (``dist_asset``, ``avatar_url``, ``theme_asset``) -- not route handlers,
so they were never tied to the ``main`` blueprint's URL map. They now register
through :func:`register_theme_helpers`, called from ``create_app()``.

The version memo (``_THEME_ASSET_VERSIONS`` / ``_theme_asset_version`` /
``clear_theme_asset_versions``) stays with them; Reset Themes still imports
``clear_theme_asset_versions`` (now from this module).

Function bodies moved verbatim; the ``print()`` calls become module-level
``logger`` calls. ``import os`` stays module-level so
``tests/test_routes.py`` can still patch ``routes_theme.os.path.exists``.
"""

import logging
import os
from pathlib import Path

from flask import current_app, url_for
from jinja2 import pass_context
from oneirodex.utils.library_paths import library_dir

logger = logging.getLogger(__name__)


def verify_file(full_path):
    if os.path.exists(full_path) or os.access(full_path, os.R_OK):
        return True
    else:
        return False


# Version tokens for theme asset URLs, keyed by resolved filesystem path.
#
# Theme files are *mutable at the same URL*: Reset Themes rewrites
# static/library/themes/<theme>/… in place while every template still points at
# the identical path. Static responses carry `max-age=3600`, so a browser served
# the old stylesheet keeps it for an hour — which is why a reset appeared to do
# nothing and why "hard-refresh" was the standing workaround. Appending a token
# that changes with the file makes the URL new, so the cache is bypassed
# correctly rather than being asked not to cache.
#
# Memoised because a page links a few dozen of these and this can sit on a
# network path where stat() is not free. `clear_theme_asset_versions()` empties
# it, and Reset Themes calls it — that is what makes the reset visible.
_THEME_ASSET_VERSIONS: dict[str, str] = {}


def clear_theme_asset_versions():
    """Drop memoised asset versions. Call after anything that rewrites themes."""
    _THEME_ASSET_VERSIONS.clear()


def _theme_asset_version(fs_path: Path) -> str:
    key = str(fs_path)
    cached = _THEME_ASSET_VERSIONS.get(key)
    if cached is not None:
        return cached
    try:
        stat = fs_path.stat()
        token = f'{int(stat.st_mtime)}-{stat.st_size}'
    except OSError:
        # Missing file still gets a URL — the 404 is the honest answer, and a
        # made-up version would only hide which asset is absent.
        token = '0'
    _THEME_ASSET_VERSIONS[key] = token
    return token


@pass_context
def dist_asset_filter(_ctx, path):
    """Version a built SPA bundle URL so a rebuild is visible immediately.

    The theme tree got this treatment in W28 and the SPA dists did not, which
    left a gap nobody could see from either side. `asgi.py` serves anything
    outside `static/library/themes/` with `public, max-age=3600`, and these were
    linked at a bare, unchanging path — so after a deploy every browser kept the
    previous `member-app.css` and `member-app.js` for an hour.

    That produced symptoms that look like a CSS bug rather than a cache: a rule
    living in the theme (served `no-cache`) took effect at once while a rule in
    the bundle did not, so one half of a change would work and the other half
    appeared broken. A hovered tile clearing its neighbours *within* a row while
    still being covered by the row below is exactly that split — the card rule
    is in components.css, the row rule is in the bundle.

    Same token as `theme_asset`: mtime and size, memoised per resolved path.

    **Except for the JavaScript entry, which gets no token.** A `<script
    type="module">` is a module *identity*, and the browser keys that identity
    on the full URL including the query. The lazy route chunks import the entry
    by its bare path (`import { g } from "../member-app.js"`), so a versioned
    script tag and an unversioned chunk import are two different modules --
    each with its own copy of every React context the entry defines. The
    provider in copy one never reaches the hook in copy two, and any page
    loaded lazily that calls `useViewer()` or `useShellConfig()` threw
    "must be used within a <...Provider>" and unmounted the whole SPA: `/chat`,
    `/calendar`, `/ways-to-play` and their neighbours rendered as a bare room
    backdrop. Seen live on 2026-09-21 (two fetches of member-app.js, one with
    `?v=` and one without).

    Freshness for the entry is carried by `asgi.py` instead, which already
    serves every unhashed `static/dist/` file `no-cache` for the caching half
    of the same bug. The stylesheet keeps its token: CSS has no module graph.

    `@pass_context` for the same reason `theme_asset` needs it — every call site
    passes a literal, and Jinja folds a filter applied to a constant at compile
    time, which would bake one token in for the life of the process and undo the
    point of versioning after a rebuild-without-restart.
    """
    root = Path(current_app.root_path) / 'static'
    target = root / 'dist' / path
    if target.suffix.lower() in ('.js', '.mjs'):
        return url_for('static', filename=f'dist/{path}')
    return url_for(
        'static',
        filename=f'dist/{path}',
        v=_theme_asset_version(target),
    )


@pass_context
def avatar_url_filter(_ctx, path):
    """`{{ current_user.avatarpath|avatar_url }}` — themed for shipped avatars.

    `@pass_context` for exactly the reason `theme_asset` needs it, and it is
    load-bearing here too: `partials/rail.html` passes `current_user.avatarpath`
    (a variable, so safe), but a template passing a literal default would be
    constant-folded at compile time and freeze every install on whichever theme
    rendered it first. Marking the filter context-dependent makes the fold
    illegal everywhere rather than relying on every call site staying dynamic.
    """
    from oneirodex.utils.avatar import avatar_url

    return avatar_url(path)


@pass_context
def theme_asset_filter(_ctx, path):
    """Convert a relative theme path to the correct themed URL with fallback to default.

    `@pass_context` is load-bearing and has nothing to do with the context.

    Every call site passes a string literal — `{{ 'css/base.css'|theme_asset }}` —
    and Jinja's optimiser constant-folds a filter applied to a constant at
    *compile* time, baking the returned URL into the compiled template. Flask
    caches compiled templates for the life of the process, so the whole install
    kept serving whichever theme happened to be current when each template was
    first rendered. Changing the theme updated `data-theme` on <html> (a real
    variable lookup, so never folded) while every stylesheet link stayed on the
    previous theme — which is exactly "changing the theme does nothing on
    reload", and why it looked like the preference had not saved.

    `nodes._FilterTestCommon.as_const` raises `Impossible` for a filter marked
    `_PassArg.context`, so this marker is what makes the fold illegal and the
    call happen per render. The context itself is unused; `current_user` still
    comes from the request. Do not "tidy" this decorator away — see
    tests/test_theme_asset.py::test_theme_asset_is_not_constant_folded.
    """
    from flask_login import current_user

    # Get current theme from user preferences or default
    if current_user.is_authenticated and hasattr(current_user, 'preferences') and current_user.preferences:
        from oneirodex.utils.preset_themes import canonical_theme_slug

        current_theme = canonical_theme_slug(current_user.preferences.theme)
    else:
        current_theme = 'default'

    # Resolve against the app package root — not process CWD (Docker/uvicorn).
    root = Path(library_dir()) / 'themes'
    themed = root / current_theme / path
    if themed.is_file():
        return url_for(
            'static',
            filename=f'library/themes/{current_theme}/{path}',
            v=_theme_asset_version(themed),
        )

    # Fallback to default theme
    fallback = root / 'default' / path
    return url_for(
        'static',
        filename=f'library/themes/default/{path}',
        v=_theme_asset_version(fallback),
    )


def register_theme_helpers(app):
    """Wire the theme-asset Jinja helpers onto ``app``.

    Called from ``create_app()``. Registers the same four names the ``main``
    blueprint used to expose via ``@bp.add_app_template_global`` /
    ``@bp.app_template_filter`` — app-level, so identical effect.
    """
    app.add_template_global(verify_file, 'verify_file')
    app.template_filter('dist_asset')(dist_asset_filter)
    app.template_filter('avatar_url')(avatar_url_filter)
    app.template_filter('theme_asset')(theme_asset_filter)
