"""Installable member app — TC-2b thin seats and Quest headsets.

The pieces that have to be true together, or the app is not installable and
nothing says why:

* a manifest is *served* and *linked* from the shells,
* a service worker is served at the origin root with a root scope header,
* the worker caches nothing that belongs to a member,
* an installed window with no network lands on a page that holds no library
  data (the worker precaches it, and a precached shelf would be readable by
  whoever opens the browser next on a shared machine).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'oneirodex' / 'static'
SW = (STATIC / 'app-sw.js').read_text(encoding='utf-8')


def test_manifest_is_served_without_a_login(client, configured_install):
    """The browser asks for this before anyone has signed in."""
    response = client.get('/manifest.webmanifest')
    assert response.status_code == 200
    assert response.mimetype == 'application/manifest+json'
    body = json.loads(response.get_data(as_text=True))
    # Installed windows should open on the shelf, not the marketing root.
    assert body['start_url'] == '/library'
    # Site-wide scope, or details and play kick out to the browser.
    assert body['scope'] == '/'
    assert body['display'] == 'standalone'
    assert body['name']
    assert len(body['short_name']) <= 12
    sizes = {icon['sizes'] for icon in body['icons']}
    assert {'192x192', '512x512'} <= sizes
    assert any(icon.get('purpose') == 'maskable' for icon in body['icons'])
    for icon in body['icons']:
        assert (ROOT / 'oneirodex' / icon['src'].lstrip('/')).is_file(), icon['src']


def test_service_worker_is_served_at_the_root_with_root_scope(client, configured_install):
    response = client.get('/sw.js')
    assert response.status_code == 200
    assert 'javascript' in response.mimetype
    # Without this header the browser refuses a scope wider than the file's path.
    assert response.headers['Service-Worker-Allowed'] == '/'
    assert response.headers['Cache-Control'] == 'no-cache'


def test_python_shells_link_the_manifest_and_load_the_installer():
    for name in ('member_spa.py', 'admin_spa.py'):
        html = (ROOT / 'oneirodex' / 'utils' / name).read_text(encoding='utf-8')
        assert "rel=\"manifest\"" in html, name
        assert 'member.app_manifest' in html, name
        # Count the <script> tags, not the string: the surrounding comments
        # name the file too, and a duplicated *comment* is not a bug.
        tags = re.findall(r"<script[^>]*od_pwa_install\.js[^>]*>", html)
        assert len(tags) == 1, f'{name} loads the installer {len(tags)} times'
        assert 'name="theme-color"' in html, name

    renderer = (ROOT / 'oneirodex' / 'utils' / 'styleguide_page.py').read_text(encoding='utf-8')
    assert 'member.app_manifest' in renderer
    assert 'od_pwa_install.js' in renderer
    assert 'name="theme-color"' in renderer


def test_offline_page_carries_no_member_data(client, configured_install):
    response = client.get('/offline')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-cache'
    html = response.get_data(as_text=True)
    assert 'No route to your library' in html
    assert 'id="od-offline-retry"' in html
    assert '/static/js/od_offline_retry.js?v=' in html
    assert '{{' not in html and '{%' not in html
    # Not a shelf: nothing member-specific may be precached with this page.
    assert 'game-card' not in html
    assert 'browse_games' not in html


def test_worker_never_caches_member_data():
    """The cache is per-origin, not per-session: it outlives a sign-out."""
    assert "'/api/'" in SW
    assert "'/static/library/images/'" in SW  # cover art is member-visible content
    assert "'/login'" in SW and "'/logout'" in SW
    # Navigations are network-only with a data-free fallback.
    assert "request.mode === 'navigate'" in SW
    assert 'OFFLINE_URL' in SW
    # and a sign-out can drop the lot
    assert 'od-clear-caches' in SW


def test_worker_only_caches_versioned_static_assets():
    assert "'/static/dist/'" in SW
    assert "'/static/vendor/'" in SW
    assert "/static/library/themes/" in SW
    # Same-origin, 200, basic responses only.
    assert "response.status === 200" in SW
    assert "response.type === 'basic'" in SW
    assert "url.origin !== self.location.origin" in SW


def test_installer_refuses_insecure_origins_and_says_where_the_control_is():
    js = (STATIC / 'js' / 'od_pwa_install.js').read_text(encoding='utf-8')
    # Service workers need HTTPS; an install button that cannot install is
    # worse than no button.
    assert 'isSecureContext' in js
    assert 'beforeinstallprompt' in js
    assert 'display-mode: standalone' in js
    # Browsers with no prompt event get a hint, not a dead control.
    assert 'data-od-install-hint' in js
    assert 'od-clear-caches' in js


def test_preferences_offers_the_install_hidden_by_default():
    component = (ROOT / 'frontend' / 'shared' / 'src' / 'PreferencesModal.tsx').read_text(encoding='utf-8')
    assert 'window.isSecureContext' in component
    assert 'installPrompt ?' in component
    assert 'Install this library' in component
    assert 'Add to Home Screen' in component


def test_worker_only_caches_urls_that_change_when_their_bytes_change():
    """Cache-first is a promise that a URL identifies its content.

    `/static/vendor/` also holds the EmulatorJS release, whose loader and cores
    are fetched with no version query at all (`EJS_pathtodata + 'loader.js'`).
    Caching those by prefix meant an installed app kept booting the old cores
    after an operator upgraded EmulatorJS — unreachable short of uninstalling.
    """
    # The rule is enforced, not merely described.
    assert "url.searchParams.has('v')" in SW
    assert 'CONTENT_HASHED_PREFIX' in SW
    # A bare prefix match is no longer sufficient on its own.
    assert 'CACHEABLE_PREFIXES.some' in SW
    assert 'if (url.pathname.startsWith(THEME_PREFIX)) return true;' not in SW
    # Bumped so installs holding the unversioned copies drop them on activate.
    assert "const VERSION = 'v2'" in SW


def test_worker_drops_superseded_caches_on_activate():
    """Otherwise a fixed rule never reaches the browsers that need it."""
    assert 'caches.delete(name)' in SW
    assert "name.startsWith('oneirodex-')" in SW
    assert '!name.endsWith(VERSION)' in SW
