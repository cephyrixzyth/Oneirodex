# /oneirodex/routes_apis/filters.py
from typing import Tuple, Type
from flask import jsonify, request, Response, url_for
from flask_login import current_user, login_required
from oneirodex.models import Genre, Theme, GameMode, PlayerPerspective
from oneirodex import cache, db
from oneirodex.utils.api_response import api_error
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.filter_catalog import (
    igdb_platforms_payload as _igdb_platforms_payload,
    libraries_payload as _libraries_payload_shared,
    library_platforms_payload as _library_platforms_payload,
    ownership_store_options as _ownership_store_options_shared,
    taxonomy_list as _taxonomy_list,
)
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
        log_system_event(
            f'Database error fetching {filter_type}: {str(e)}',
            event_type='filters_api', event_level='error',
        )
        return api_error(f'Database error retrieving {filter_type}', code='internal')

    except Exception as e:
        log_system_event(
            f'Unexpected error fetching {filter_type}: {str(e)}',
            event_type='filters_api', event_level='error',
        )
        return api_error(f'Error retrieving {filter_type}', code='internal')


def _libraries_payload(user, *, fallback_image_url: str | None = None) -> list[dict]:
    return _libraries_payload_shared(user, fallback_image_url=fallback_image_url or url_for(
        'static', filename='newstyle/default_library.jpg'
    ))


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
        log_system_event('Database error fetching library_platforms', event_type='filters_api', event_level='error')
        return api_error('Database error retrieving library platforms', code='internal')


@apis_bp.route('/igdb_platforms')
@login_required
def get_igdb_platforms():
    try:
        return jsonify(_igdb_platforms_payload()), 200
    except SQLAlchemyError as e:
        log_system_event('Database error fetching igdb_platforms', event_type='filters_api', event_level='error')
        return api_error('Database error retrieving igdb platforms', code='internal')


def _ownership_store_options():
    """Stores the browse `store=` filter can answer for (LIB-02): recorded
    ownership only, and only while the operator policy allows the provider.
    Names come from the provider registry; no member data is read."""
    return _ownership_store_options_shared()


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
        log_system_event('Database error fetching filters bundle', event_type='filters_api', event_level='error')
        return api_error('Database error retrieving filters', code='internal')
