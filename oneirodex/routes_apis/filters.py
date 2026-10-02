# /oneirodex/routes_apis/filters.py
from typing import Tuple, Type
from flask import jsonify, request, Response, url_for
from flask_login import current_user, login_required
from oneirodex.models import Genre, Theme, GameMode, PlayerPerspective, Library, Platform, Game
from oneirodex import cache, db
from oneirodex.platform import mapped_core_ids, play_mode_for_platform
from oneirodex.utils.api_response import api_error
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.library_acl import allowed_library_uuids, apply_game_access_filters, filter_libraries
from oneirodex.utils.set_completion import completion_summaries_by_platform
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from . import apis_bp


def _get_filter_data(model_class: Type[db.Model], filter_type: str) -> Tuple[Response, int]:
    """
    Generic helper function to fetch and format filter data.

    Args:
        model_class: SQLAlchemy model class to query
        filter_type: String identifier for logging purposes

    Returns:
        Tuple of JSON response and HTTP status code
    """
    try:
        results = db.session.execute(select(model_class).order_by(model_class.name.asc())).scalars().all()
        data_list = [{'id': item.id, 'name': item.name} for item in results]

        return jsonify(data_list), 200

    except SQLAlchemyError as e:
        log_system_event('filters_api', f'Database error fetching {filter_type}: {str(e)}', 'error')
        return api_error(f'Database error retrieving {filter_type}', code='internal')

    except Exception as e:
        log_system_event('filters_api', f'Unexpected error fetching {filter_type}: {str(e)}', 'error')
        return api_error(f'Error retrieving {filter_type}', code='internal')


def _taxonomy_list(model_class: Type[db.Model]) -> list[dict]:
    results = db.session.execute(select(model_class).order_by(model_class.name.asc())).scalars().all()
    return [{'id': item.id, 'name': item.name} for item in results]


def _libraries_payload(user) -> list[dict]:
    libraries_query = filter_libraries(
        db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all(),
        user,
    )
    return [
        {
            'uuid': lib.uuid,
            'name': lib.name,
            'image_url': lib.image_url if lib.image_url else url_for(
                'static', filename='newstyle/default_library.jpg'
            ),
        }
        for lib in libraries_query
    ]


def _library_platforms_payload(user, *, include_completion: bool = False) -> list[dict]:
    allowed = allowed_library_uuids(user)
    if allowed is not None and not allowed:
        return []

    accessible_games = apply_game_access_filters(select(Game.id, Game.library_uuid), user).subquery()
    query = (
        select(Library.platform, func.count(accessible_games.c.id))
        .select_from(Library)
        .outerjoin(accessible_games, accessible_games.c.library_uuid == Library.uuid)
        .group_by(Library.platform)
    )
    if allowed is not None:
        query = query.filter(Library.uuid.in_(list(allowed)))

    count_rows = db.session.execute(query).all()
    counts = {}
    for platform, game_count in count_rows:
        if platform is None:
            continue
        counts[platform] = counts.get(platform, 0) + int(game_count or 0)

    completion_by_platform = {}
    if include_completion:
        completion_by_platform = completion_summaries_by_platform(user)

    data = []
    for p, game_count in sorted(counts.items(), key=lambda item: item[0].value.lower()):
        mode = play_mode_for_platform(p.name)
        row = {
            'id': p.name,
            'name': p.value,
            'value': p.name,
            'game_count': game_count,
            'play_mode': mode,
            'companion_cores': mapped_core_ids(p.name),
        }
        summary = completion_by_platform.get(p.name)
        if summary:
            regions = summary.get('regions') or []
            row['set_completion'] = {
                key: value for key, value in summary.items() if key != 'regions'
            }
            if regions:
                row['set_completion_regions'] = regions
        data.append(row)

    return data


def _igdb_platforms_payload() -> list[dict]:
    results = db.session.execute(
        select(Platform)
        .join(Platform.games)
        .distinct()
        .order_by(Platform.name.asc())
    ).scalars().all()
    return [{'id': item.id, 'name': item.name} for item in results]


@apis_bp.route('/genres')
@login_required
def get_genres() -> Tuple[Response, int]:
    return _get_filter_data(Genre, 'genres')


@apis_bp.route('/themes')
@login_required
def get_themes() -> Tuple[Response, int]:
    return _get_filter_data(Theme, 'themes')


@apis_bp.route('/game_modes')
@login_required
def get_game_modes() -> Tuple[Response, int]:
    return _get_filter_data(GameMode, 'game_modes')


@apis_bp.route('/player_perspectives')
@login_required
def get_player_perspectives() -> Tuple[Response, int]:
    return _get_filter_data(PlayerPerspective, 'player_perspectives')


@apis_bp.route('/library_platforms')
@login_required
def get_library_platforms():
    try:
        include_completion = request.args.get('include_completion', '0') in ('1', 'true', 'yes')
        data = _library_platforms_payload(current_user, include_completion=include_completion)
        return jsonify(data), 200
    except SQLAlchemyError as e:
        log_system_event('filters_api', f'Database error fetching library_platforms: {str(e)}', 'error')
        return api_error('Database error retrieving library platforms', code='internal')


@apis_bp.route('/igdb_platforms')
@login_required
def get_igdb_platforms():
    try:
        return jsonify(_igdb_platforms_payload()), 200
    except SQLAlchemyError as e:
        log_system_event('filters_api', f'Database error fetching igdb_platforms: {str(e)}', 'error')
        return api_error('Database error retrieving igdb platforms', code='internal')


def _ownership_store_options():
    """Stores the browse `store=` filter can answer for (LIB-02): recorded
    ownership only, and only while the operator policy allows the provider.
    Names come from the provider registry; no member data is read."""
    from oneirodex.utils.store_capabilities import provider_capabilities
    from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled, unofficial_store_opt_in

    return [
        {'id': p['id'], 'name': p['name']}
        for p in provider_capabilities(enabled=is_ownership_sync_enabled(), unofficial_stores=unofficial_store_opt_in())
        if p['capabilities']['store_filter'] == 'recorded_ownership' and p['policy_enabled']
    ]


@apis_bp.route('/filters/bundle')
@login_required
def filters_bundle():
    """Single payload for FilterBar — replaces 7 parallel filter GETs."""
    try:
        cache_key = f'filters_bundle_u{current_user.id}'
        cached = cache.get(cache_key)
        if cached is not None:
            return jsonify(cached), 200

        payload = {
            'libraries': _libraries_payload(current_user),
            'libraryPlatforms': _library_platforms_payload(current_user, include_completion=False),
            'igdbPlatforms': _igdb_platforms_payload(),
            'genres': _taxonomy_list(Genre),
            'themes': _taxonomy_list(Theme),
            'gameModes': _taxonomy_list(GameMode),
            'playerPerspectives': _taxonomy_list(PlayerPerspective),
            'ownershipStores': _ownership_store_options(),
        }
        cache.set(cache_key, payload, timeout=60)
        return jsonify(payload), 200
    except SQLAlchemyError as e:
        log_system_event('filters_api', f'Database error fetching filters bundle: {str(e)}', 'error')
        return api_error('Database error retrieving filters', code='internal')
