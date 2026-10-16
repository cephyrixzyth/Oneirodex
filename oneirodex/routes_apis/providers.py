"""Artwork provider API routes (search + apply cover — no game downloads)."""

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.schemas.providers import ApplyArtworkBody
from oneirodex.utils.artwork_apply import apply_cover_from_url
from oneirodex.utils.auth import admin_required
from oneirodex.utils.image_kinds import (
    STEAMGRIDDB_SEARCH_KINDS,
    image_kinds_error_message,
    normalize_image_kind,
    parse_image_kind,
)
from oneirodex.utils.providers import ProviderDisabledError, get_provider, list_providers
from oneirodex.utils.providers.giantbomb import pcgamingwiki_enrichment
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _refuse_no_query():
    """Five search endpoints answer a missing `q` this way."""
    return api_error('Query parameter q is required', code='bad_request')


def _refuse_not_configured(provider_id: str, message: str):
    """503 for an integration that is switched off or missing credentials.

    Four endpoints spelled this out. `provider` rides along as an envelope extra
    because the admin UI uses it to link straight to that integration's card.
    """
    return api_error(message, code='unavailable', provider=provider_id)


@apis_bp.route('/providers', methods=['GET'])
@login_required
@admin_required
def providers_list():
    """List registered artwork providers and whether each is enabled."""
    return jsonify({'providers': list_providers()})


@apis_bp.route('/providers/steamgriddb/search', methods=['GET'])
@login_required
@admin_required
def steamgriddb_search():
    """Search SteamGridDB artwork by game title (cover/logo/hero)."""
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return _refuse_no_query()

    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20

    art_kind = normalize_image_kind(
        request.args.get('image_type') or request.args.get('art_kind') or request.args.get('kind'),
        default='cover',
    )
    if art_kind not in STEAMGRIDDB_SEARCH_KINDS:
        return api_error('image_type must be cover, logo, or hero', code='bad_request')

    provider = get_provider('steamgriddb')
    if not provider.is_enabled():
        return _refuse_not_configured(provider.id, 'SteamGridDB is not configured. Set STEAMGRIDDB_API_KEY.')

    try:
        results = provider.search_artwork(query, limit=limit, art_kind=art_kind)
    except ProviderDisabledError as exc:
        return api_error(exc.message, code='unavailable', provider=exc.provider_id)
    except RuntimeError:
        return api_error('Artwork provider request failed', code='bad_gateway', provider=provider.id)

    return jsonify({
        'provider': provider.id,
        'query': query,
        'image_type': art_kind,
        'results': [item.to_dict() for item in results],
    })


@apis_bp.route('/providers/igdb/search', methods=['GET'])
@login_required
@admin_required
def igdb_cover_search():
    """Search IGDB covers by game title (existing IGDB credentials)."""
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return _refuse_no_query()

    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20

    provider = get_provider('igdb')
    if not provider.is_enabled():
        return _refuse_not_configured(provider.id, 'IGDB is not configured. Set IGDB client ID/secret in Integrations.')

    try:
        results = provider.search_covers(query, limit=limit)
    except ProviderDisabledError as exc:
        return api_error(exc.message, code='unavailable', provider=exc.provider_id)
    except RuntimeError:
        return api_error('Artwork provider request failed', code='bad_gateway', provider=provider.id)

    return jsonify({
        'provider': provider.id,
        'query': query,
        'results': [item.to_dict() for item in results],
    })


@apis_bp.route('/games/<game_uuid>/artwork/steamgriddb', methods=['POST'])
@login_required
@admin_required
@validate_body(ApplyArtworkBody)
def steamgriddb_apply_artwork(game_uuid, body: ApplyArtworkBody):
    """Download artwork URL and persist as a locked image kind (cover/box/…/fanart)."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found', game_uuid=game_uuid)

    image_url = body.url
    provider_id = (body.provider or 'steamgriddb').strip().lower() or 'steamgriddb'
    try:
        image_type = parse_image_kind(
            body.image_type or body.kind,
            default='cover',
        )
    except ValueError:
        return api_error(image_kinds_error_message(), code='bad_request')
    if provider_id not in ('steamgriddb', 'igdb'):
        return api_error('provider must be steamgriddb or igdb', code='bad_request')
    if provider_id == 'igdb' and image_type != 'cover':
        # IGDB apply URL path remains cover-only (screenshots use identify pipeline).
        return api_error('IGDB only supports image_type=cover', code='bad_request')

    try:
        result = apply_cover_from_url(
            game_uuid,
            image_url,
            provider_id=provider_id,
            image_type=image_type,
        )
    except ValueError as exc:
        current_app.logger.info(
            'Artwork URL rejected for provider %s (%s)',
            provider_id, type(exc).__name__,
        )
        return api_error('Artwork image URL was rejected', code='bad_request', game_uuid=game_uuid)
    except LookupError as exc:
        return api_error(str(exc), code='not_found', game_uuid=game_uuid)
    except ProviderDisabledError as exc:
        return api_error(exc.message, code='unavailable', provider=exc.provider_id)
    except RuntimeError as exc:
        current_app.logger.warning(
            'Artwork application unavailable for provider %s (%s)',
            provider_id, type(exc).__name__,
        )
        return api_error('Artwork provider unavailable', code='unavailable', game_uuid=game_uuid)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning(
            'Artwork application failed for provider %s (%s)',
            provider_id, type(exc).__name__,
        )
        return api_error('Failed to apply artwork', code='bad_gateway', game_uuid=game_uuid)

    return jsonify(result), 200


@apis_bp.route('/providers/giantbomb/search', methods=['GET'])
@login_required
@admin_required
def giantbomb_search():
    """Search GiantBomb covers by game title."""
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return _refuse_no_query()
    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20

    provider = get_provider('giantbomb')
    if not provider.is_enabled():
        return _refuse_not_configured(provider.id, 'GiantBomb is not configured. Set GIANTBOMB_API_KEY.')
    try:
        results = provider.search_covers(query, limit=limit)
    except ProviderDisabledError as exc:
        return api_error(exc.message, code='unavailable', provider=exc.provider_id)
    except RuntimeError:
        return api_error('Artwork provider request failed', code='bad_gateway', provider=provider.id)

    return jsonify({
        'provider': provider.id,
        'query': query,
        'results': [item.to_dict() for item in results],
    })


@apis_bp.route('/providers/pcgamingwiki/search', methods=['GET'])
@login_required
def pcgamingwiki_search():
    """Find PCGamingWiki pages for a game title (links only)."""
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return _refuse_no_query()
    try:
        return jsonify(pcgamingwiki_enrichment(query))
    except RuntimeError:
        return api_error('Artwork provider request failed', code='bad_gateway', provider='pcgamingwiki')


@apis_bp.route('/providers/meta_quest/search', methods=['GET'])
@login_required
@admin_required
def meta_quest_cover_search():
    """Search Meta/Quest covers via IGDB platform filter (artwork only)."""
    query = (request.args.get('q') or request.args.get('query') or '').strip()
    if not query:
        return _refuse_no_query()
    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20

    provider = get_provider('meta_quest')
    if not provider.is_enabled():
        return api_error(
            'Meta/Quest search requires IGDB credentials.',
            code='unavailable',
            provider=provider.id,
            hint=provider.config_hint(),
        )
    try:
        results = provider.search_covers(query, limit=limit)
    except ProviderDisabledError as exc:
        return api_error(exc.message, code='unavailable', provider=exc.provider_id)
    except RuntimeError:
        return api_error('Artwork provider request failed', code='bad_gateway', provider=provider.id)

    return jsonify({
        'provider': provider.id,
        'query': query,
        'ownership_only': True,
        'results': [item.to_dict() for item in results],
    })


@apis_bp.route('/theme/fonts', methods=['GET'])
@login_required
def theme_fonts_list():
    """Fonts available for theming, incl. operator drop-ins (font theming).

    ``installed: false`` means the CSS stack will fall through to the next
    family — surfaced so a picker can say so rather than silently doing nothing.
    """
    from oneirodex.utils.theme_fonts import (
        PLATFORM_FONT_HINTS,
        available_fonts,
        fonts_dir,
    )

    catalogue = available_fonts()
    return api_ok({
        'fonts': [
            {'id': key, **{k: v for k, v in entry.items() if k != 'file'}}
            for key, entry in sorted(catalogue.items())
        ],
        'platform_hints': PLATFORM_FONT_HINTS,
        'fonts_dir': fonts_dir(),
        'note': (
            'Console manufacturers\' typefaces are not bundled — these are '
            'OFL/public-domain faces chosen to evoke each era. Drop your own '
            'licensed fonts in fonts_dir to have them offered here.'
        ),
    })


@apis_bp.route('/theme/fonts.css', methods=['GET'])
def theme_fonts_css():
    """``@font-face`` rules plus the caller's chosen family.

    Served as a stylesheet rather than injected inline so the browser caches it
    and so a page can link it before first paint. Without this route the font
    files are installed and the picker lists them, but nothing on any page ever
    declares the families — the whole feature is inert.

    Unauthenticated on purpose: it is public CSS for public font files, and the
    login page should render in the household face too.
    """
    from flask import make_response, request

    from oneirodex.utils.theme_fonts import (
        DEFAULT_FONT_ID,
        font_face_css,
        resolve_font,
    )

    chosen = request.args.get('font')
    if not chosen and getattr(current_user, 'is_authenticated', False):
        chosen = getattr(getattr(current_user, 'preferences', None), 'font', None)
    entry = resolve_font(chosen or DEFAULT_FONT_ID)

    css = (
        f"{font_face_css()}\n\n"
        ":root {\n"
        f"  --od-font-family: {entry['stack']};\n"
        "}\n"
        "body, .od-shell, .od-topnav, button, input, select, textarea {\n"
        "  font-family: var(--od-font-family);\n"
        "}\n"
    )
    response = make_response(css)
    response.headers['Content-Type'] = 'text/css; charset=utf-8'
    # Short cache: a font upload or preference change should show up promptly.
    response.headers['Cache-Control'] = 'public, max-age=60'
    return response
