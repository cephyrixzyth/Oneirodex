"""Member-facing pages: collections, news, wishlist, updates inbox."""

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from oneirodex import cache
from oneirodex.utils.api_response import api_error
from oneirodex.utils.browse_payload import build_browse_payload
from oneirodex.utils.browse_query import run_browse_query
from oneirodex.utils.filter_tree import FilterTreeError
from oneirodex.utils.member_spa import render_member_spa
from oneirodex.utils.processors import get_global_settings

member_bp = Blueprint('member', __name__)


@member_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Inject global settings into member-blueprint templates.

    Matches every other member-facing blueprint. ``render_member_spa`` also
    merges these flags, so a forgotten processor cannot hide Help / Trailers.
    """
    return get_global_settings()


@member_bp.route('/browse_games')
@login_required
def browse_games():
    """Library grid for the member SPA.

    Arg parsing, filters and the per-page batch lookups are
    :func:`oneirodex.utils.browse_query.run_browse_query`; the response body
    (populated or guaranteed-empty, same shape either way) is
    :func:`oneirodex.utils.browse_payload.build_browse_payload`.

    Kept at the exact path ``/browse_games`` -- the member SPA
    (``frontend/member-app/src/api/browse.ts``) hits the raw URL, never
    ``url_for``. Moved off the retired ``'main'`` blueprint in wave A2.1f.
    """
    try:
        result = run_browse_query(request.args, current_user)
    except FilterTreeError as exc:
        # INSP-3. A filter we will not run has to say so: quietly dropping it
        # would hand back the whole library and let the member read that as the
        # answer to the question they asked.
        return api_error(str(exc), code='bad_request', detail={'path': exc.path})
    return jsonify(build_browse_payload(result))


@member_bp.route('/systems')
@login_required
def systems_page():
    return render_member_spa(title='Systems')


@member_bp.route('/systems/completion')
@login_required
def set_completion_page():
    return render_member_spa(title='Set completion')


@member_bp.route('/systems/catalog')
@login_required
def licensed_catalog_page():
    return render_member_spa(title='Licensed catalog')


@member_bp.route('/ways-to-play')
@login_required
def ways_to_play_page():
    return render_member_spa(title='Ways to Play')


@member_bp.route('/collections')
@login_required
def collections_page():
    return render_member_spa(title='Collections')


@member_bp.route('/collections/<collection_uuid>')
@login_required
def collection_detail_page(collection_uuid: str):
    return render_member_spa(title='Collection', collection_uuid=collection_uuid)


@member_bp.route('/news')
@login_required
def announcements_page():
    return render_member_spa(title='News')


@member_bp.route('/wishlist')
@login_required
def wishlist_page():
    return render_member_spa(title='Wishlist')


@member_bp.route('/updates')
@login_required
def updates_page():
    """Freshness updates inbox — librarians/admins see library-wide inbox."""
    return render_member_spa(title='Updates')


@member_bp.route('/acquire')
@login_required
def acquire_page():
    """BYO indexer/debrid acquire panel (feature-flagged on the API)."""
    return render_member_spa(title='Acquire')


@member_bp.route('/playtime')
@login_required
def playtime_page():
    return render_member_spa(title='Playtime')


@member_bp.route('/activity')
@login_required
def activity_page():
    # Gate the route, not just the nav link — hiding a menu entry while the URL
    # still serves the page is the kind of half-toggle this flag was guilty of.
    # Defaults on: the surface predates the flag.
    enabled = str(current_app.config.get('ENABLE_ACTIVITY_FEED', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )
    if not enabled:
        return redirect(url_for('library.library'))
    return render_member_spa(title='Activity')


@member_bp.route('/social-companion')
@login_required
def social_companion_page():
    """Stay-open friends companion window (pop-out / desktop overlay target)."""
    return render_member_spa(title='Friends')


@member_bp.route('/chat')
@login_required
def chat_page():
    return render_member_spa(title='Chat')


@member_bp.route('/notifications')
@login_required
def notifications_page():
    return render_member_spa(title='Notifications')


@member_bp.route('/tokens')
@login_required
def tokens_page():
    """Personal access tokens.

    The SPA has had `path="/tokens"` in its route table all along, but no
    server route rendered the shell for it, so a deep link or a refresh on
    /tokens returned a hard 404 while every other member route resolved.
    """
    return render_member_spa(title='Tokens')


@member_bp.route('/members/<int:user_id>')
@login_required
def member_profile_page(user_id: int):
    return render_member_spa(title='Profile')


@member_bp.route('/report')
@login_required
def report_issue_page():
    return render_member_spa(title='Report issue')


@member_bp.route('/big-picture')
@login_required
def big_picture_page():
    return render_member_spa(title='Big Picture')


@member_bp.route('/ownership')
@login_required
def ownership_page():
    """Register-only store ownership sync — never downloads from stores."""
    return render_member_spa(title='Store Ownership')


@member_bp.route('/welcome')
@login_required
def welcome_page():
    """First-run store setup: the same connection list as Ownership (LIB-02)."""
    return render_member_spa(title='Set up your stores')


@member_bp.route('/calendar')
@login_required
def calendar_page():
    """IGDB release calendar (metadata only)."""
    return render_member_spa(title='Release calendar')


@member_bp.route('/vr')
@login_required
def vr_browse_page():
    enabled = str(current_app.config.get('ENABLE_VR_BROWSE', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )
    if not enabled:
        return redirect(url_for('library.library'))
    return render_member_spa(title='VR Library')


@member_bp.route('/manifest.webmanifest')
def app_manifest():
    """Install manifest for the member app (TC-2b thin seats, Quest headsets).

    A route rather than a static file because the name and start URL follow the
    install: `PRODUCT_NAME` is the product's, but an operator who has renamed
    the site should see their name on the home screen, not ours.

    No login required — a manifest is fetched by the browser before the member
    is anywhere near signing in, and it contains nothing but branding.
    """
    from oneirodex.product import PRODUCT_NAME

    settings = get_global_settings() or {}
    site_name = str(settings.get('site_name') or '').strip() or PRODUCT_NAME
    manifest = {
        'id': '/library',
        'name': site_name,
        'short_name': site_name[:12] or PRODUCT_NAME[:12],
        'description': f'{site_name} — your household game library',
        # The library, not `/`: an installed window should open on the shelf.
        'start_url': '/library',
        # Site-wide so details, Discover, settings and browser play all stay
        # inside the installed window instead of kicking out to the browser.
        'scope': '/',
        'display': 'standalone',
        'display_override': ['window-controls-overlay', 'standalone', 'minimal-ui'],
        'orientation': 'any',
        'background_color': '#0b0f14',
        'theme_color': '#0b0f14',
        'categories': ['games', 'entertainment', 'utilities'],
        'icons': [
            {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-256.png', 'sizes': '256x256', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Library', 'url': '/library'},
            {'name': 'Discover', 'url': '/discover'},
            {'name': 'Big Picture', 'url': '/bigpicture'},
        ],
    }
    resp = jsonify(manifest)
    resp.mimetype = 'application/manifest+json'
    # Branding changes rarely; an hour keeps a rename from taking a day.
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@member_bp.route('/sw.js')
def app_service_worker():
    """Serve the member service worker at the origin root so its scope is `/`."""
    static_root = Path(current_app.static_folder or '')
    resp = send_from_directory(static_root, 'app-sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    # Never cached: a stale worker is a bug that outlives deploys.
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@member_bp.route('/offline')
def offline_page():
    """What an installed app shows with no network.

    Static and member-free on purpose — the service worker precaches it, and a
    precached page that carried library data would be readable by whoever opens
    the browser next.
    """
    resp = current_app.make_response(render_template('site/offline.html'))
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@member_bp.route('/vr/sw.js')
def vr_service_worker():
    """Serve VR PWA service worker under /vr/ so scope is valid."""
    static_root = Path(current_app.static_folder or '')
    resp = send_from_directory(static_root, 'vr-sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/vr'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp
