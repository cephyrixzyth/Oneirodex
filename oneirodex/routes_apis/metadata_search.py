"""Manual multi-source metadata search for identify / add game UI."""

from flask import current_app, jsonify, request
from flask_login import login_required

from oneirodex.utils.api_response import api_error
from oneirodex.utils.auth import admin_required
from oneirodex.utils.providers.meta_quest import (
    get_meta_quest_api_mode,
    normalize_meta_quest_source,
    unofficial_graphql_enabled,
)
from oneirodex.utils.providers.mobygames import (
    get_mobygames_api_key,
    mobygames_config_hint,
)
from oneirodex.utils.providers.thegamesdb import (
    get_thegamesdb_api_key,
    thegamesdb_config_hint,
)
from oneirodex.utils.secondary_scrapers import (
    search_epic_games,
    search_giantbomb_games,
    search_gog_games,
    search_itch_games,
    search_meta_quest_games,
    search_mobygames_games,
    search_rawg_games,
    search_steam_games,
    search_thegamesdb_games,
)

from . import apis_bp

# DRM store sources are metadata / ownership-register only — never download games.
SUPPORTED_SOURCES = (
    'steam',
    'rawg',
    'gog',
    'epic',
    'itch',
    'giantbomb',
    'mobygames',
    'thegamesdb',
    'meta_quest',
)
# UI aliases accepted for Meta Quest Store (canonical id remains meta_quest).
_META_QUEST_ALIASES = frozenset({'meta_quest', 'meta', 'quest'})
# Aliases for MobyGames chip.
_MOBYGAMES_ALIASES = frozenset({'mobygames', 'moby'})
# Aliases for TheGamesDB chip.
_THEGAMESDB_ALIASES = frozenset({'thegamesdb', 'tgdb'})


@apis_bp.route('/search_metadata', methods=['GET'])
@login_required
@admin_required
def search_metadata():
    """Search Steam / RAWG / GOG / Epic / itch / GiantBomb / MobyGames / TheGamesDB / Meta Quest by name.

    Query args:
      name (required)
      source: steam|rawg|gog|epic|itch|giantbomb|mobygames|moby|thegamesdb|tgdb|meta_quest|meta|quest (required)
      limit: int (default 10, max 20)
      include_software: bool (Steam only, default true) — include Steam
        type=software/application hits for gaming-adjacent apps

    Meta Quest, Epic: ownership/register + metadata only — never DRM installs.
    Steam results include steam_type + item_kind for UI kind badges.
    MobyGames / TheGamesDB: optional API key — empty results when unset (honest, no 500).
    """
    name = (request.args.get('name') or '').strip()
    source_raw = (request.args.get('source') or '').strip().lower()
    source = normalize_meta_quest_source(source_raw) or source_raw
    if source_raw in _MOBYGAMES_ALIASES or source == 'moby':
        source = 'mobygames'
    if source_raw in _THEGAMESDB_ALIASES or source == 'tgdb':
        source = 'thegamesdb'
    try:
        limit = min(int(request.args.get('limit') or 10), 20)
    except (TypeError, ValueError):
        limit = 10
    include_software_raw = (request.args.get('include_software') or '1').strip().lower()
    include_software = include_software_raw not in ('0', 'false', 'no')

    if not name:
        return api_error('No game name provided', code='bad_request')
    if (
        source not in SUPPORTED_SOURCES
        and source_raw not in _META_QUEST_ALIASES
        and source_raw not in _MOBYGAMES_ALIASES
        and source_raw not in _THEGAMESDB_ALIASES
    ):
        return api_error(
            (
                f'Unsupported source. Use one of: {", ".join(SUPPORTED_SOURCES)} '
                '(aliases: meta, quest, moby, tgdb)'
            ),
            code='bad_request',
            sources=list(SUPPORTED_SOURCES),
        )

    mobygames_key_present = False
    thegamesdb_key_present = False
    if source == 'steam':
        results = search_steam_games(name, limit=limit, include_software=include_software)
    elif source == 'rawg':
        api_key = current_app.config.get('RAWG_API_KEY') or None
        results = search_rawg_games(name, api_key=api_key, limit=limit)
    elif source == 'gog':
        results = search_gog_games(name, limit=limit)
    elif source == 'epic':
        results = search_epic_games(name, limit=limit)
    elif source == 'itch':
        results = search_itch_games(name, limit=limit)
    elif source == 'giantbomb':
        results = search_giantbomb_games(name, limit=limit)
    elif source == 'mobygames':
        mobygames_key_present = bool(get_mobygames_api_key())
        results = search_mobygames_games(name, limit=limit)
    elif source == 'thegamesdb':
        thegamesdb_key_present = bool(get_thegamesdb_api_key())
        results = search_thegamesdb_games(name, limit=limit)
    else:
        results = search_meta_quest_games(name, limit=limit)
        source = 'meta_quest'

    payload = {
        'source': source,
        'results': results,
        'ownership_only': source in ('meta_quest', 'epic'),
    }
    if source == 'steam':
        payload['include_software'] = include_software
        payload['note'] = (
            'Steam results may include type=software (emulators/tools). '
            'Use item_kind for badges; never auto-treat software as IGDB Main Game. '
            'Ownership register-only — no DRM download queues.'
        )
    if source == 'mobygames':
        payload['needs_key'] = True
        payload['key_configured'] = mobygames_key_present
        if not mobygames_key_present:
            payload['note'] = (
                'MOBYGAMES_API_KEY not configured — empty results. '
                'Set env or GlobalSettings.mobygames_api_key '
                '(https://www.mobygames.com/info/api/). '
                'Metadata only — never downloads games.'
            )
        else:
            payload['note'] = (
                'MobyGames Class D metadata search. Select a hit → custom/enrich path. '
                'Not in Stage D scan cascade yet (manual identify only).'
            )
    if source == 'thegamesdb':
        payload['needs_key'] = True
        payload['key_configured'] = thegamesdb_key_present
        if not thegamesdb_key_present:
            payload['note'] = (
                'THEGAMESDB_API_KEY not configured — empty results. '
                'Set env or GlobalSettings.thegamesdb_api_key '
                '(https://thegamesdb.net/api/register.php). '
                'Metadata / covers only — never downloads games.'
            )
        else:
            payload['note'] = (
                'TheGamesDB Class D metadata search (console-friendly). '
                'Select a hit → custom/enrich path. '
                'Not in Stage D scan cascade yet (manual identify only).'
            )
    if source == 'meta_quest':
        payload['api_mode'] = get_meta_quest_api_mode()
        payload['unofficial_graphql'] = unofficial_graphql_enabled()
    return jsonify(payload)


@apis_bp.route('/search_metadata/sources', methods=['GET'])
@login_required
@admin_required
def search_metadata_sources():
    """List identify-search sources and whether each needs an API key."""
    from oneirodex.utils.metadata_search_sources import build_metadata_search_sources

    return jsonify(build_metadata_search_sources())
