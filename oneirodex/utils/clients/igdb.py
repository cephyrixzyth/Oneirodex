"""IGDB search / fetch-by-id / URL-store + IGDB image-ref resolution.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GameURL
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.runtime_config import get_runtime_config
from oneirodex.utils.helpers.urls import website_category_to_string
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "normalize_igdb_image_ref",
    "_absolute_igdb_image_url",
    "_igdb_endpoint_for_image_type",
    "_resolve_igdb_download_url",
    "fetch_and_store_game_urls",
    "search_igdb_for_game",
    "fetch_game_by_igdb_id",
]


def normalize_igdb_image_ref(image_data):
    """Normalize an IGDB cover/screenshot ref to ``(id, url_or_none)``.

    IGDB returns bare integer IDs when a field is requested without expansion
    (``cover``, ``screenshots``) and dicts when expanded (``cover.url``).
    Passing a dict into ``where id={...}`` silently fails to store a cover
    while screenshot ID lists still succeed — the "screenshots yes, cover
    placeholder" symptom after identify/match.
    """
    if image_data is None:
        return None, None
    if isinstance(image_data, dict):
        raw_id = image_data.get('id')
        image_id = None
        if raw_id is not None and str(raw_id).strip() != '':
            try:
                image_id = int(raw_id)
            except (TypeError, ValueError):
                image_id = str(raw_id).strip()
        download_url = None
        raw_url = image_data.get('url')
        if isinstance(raw_url, str) and raw_url.strip():
            download_url = _absolute_igdb_image_url(raw_url)
        if not download_url and image_data.get('image_id'):
            stem = str(image_data['image_id']).strip()
            if stem:
                download_url = (
                    f'https://images.igdb.com/igdb/image/upload/t_original/{stem}.jpg'
                )
        return image_id, download_url
    if isinstance(image_data, (int, float)) and not isinstance(image_data, bool):
        return int(image_data), None
    text = str(image_data).strip()
    if not text:
        return None, None
    if text.isdigit():
        return int(text), None
    if text.startswith(('http://', 'https://', '//')):
        return None, _absolute_igdb_image_url(text)
    return text, None


def _absolute_igdb_image_url(url):
    """Force https + prefer original size for local download / remote fallback."""
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.startswith('//'):
        url = 'https:' + url
    elif not url.startswith(('http://', 'https://')):
        if url.startswith('images.igdb.com/') or url.startswith('www.igdb.com/'):
            url = 'https://' + url
        else:
            return url
    return url.replace('/t_thumb/', '/t_original/')


def _igdb_endpoint_for_image_type(image_type):
    if image_type == 'cover':
        return 'https://api.igdb.com/v4/covers'
    if image_type == 'screenshot':
        return 'https://api.igdb.com/v4/screenshots'
    return None


def _resolve_igdb_download_url(image_id, image_type, known_url=None):
    """Return an absolute download URL, using known_url or a covers/screenshots lookup."""
    if known_url:
        return _absolute_igdb_image_url(known_url)
    if image_id is None:
        return None
    endpoint = _igdb_endpoint_for_image_type(image_type)
    if not endpoint:
        return None
    response = make_igdb_api_request(endpoint, f'fields url, image_id; where id={image_id};')
    if not response or 'error' in response:
        return None
    row = response[0] if isinstance(response, list) and response else None
    if not row:
        return None
    url = row.get('url')
    if url:
        return _absolute_igdb_image_url(url)
    stem = row.get('image_id')
    if stem:
        return f'https://images.igdb.com/igdb/image/upload/t_original/{stem}.jpg'
    return None


def fetch_and_store_game_urls(game_uuid, igdb_id):
    try:
        website_query = f'fields url, category; where game={igdb_id};'        
        websites_response = make_igdb_api_request('https://api.igdb.com/v4/websites', website_query)
        
        if websites_response and 'error' not in websites_response:
            for website in websites_response:
                
                new_url = GameURL(
                    game_uuid=game_uuid,
                    url_type=website_category_to_string(website.get('category'), website.get('url')),
                    url=website.get('url')
                )
                db.session.add(new_url)
        else:
            logger.error(f"No URLs found or failed to retrieve URLs for game IGDB ID {igdb_id}.")
    except Exception as e:
        logger.error(f"Exception while fetching/storing URLs for game UUID {game_uuid}, IGDB ID {igdb_id}: {e}")
        

    
def search_igdb_for_game(search_name, platform_id, limit=10):
    """
    Search IGDB for games matching name (and optional platform).
    Returns a list of game dicts, or None if the API errors / returns empty.
    """
    query_fields = """fields id, name, cover.url, cover.image_id, summary, url, release_dates.date, release_dates.region, release_dates.platform, platforms.name, genres.name, themes.name, game_modes.name,
                      screenshots.url, screenshots.image_id, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
                      aggregated_rating_count, rating, rating_count, slug, status, category, total_rating,
                      total_rating_count;"""
    safe_limit = max(1, min(int(limit), 20))
    query_filter = f'search "{search_name}"; limit {safe_limit};'
    if platform_id is not None:
        query_filter += f' where platforms = ({platform_id});'

    response_json = make_igdb_api_request(get_runtime_config()['IGDB_API_ENDPOINT'], query_fields + query_filter)

    if 'error' not in response_json and response_json:
        return response_json
    return None


def fetch_game_by_igdb_id(igdb_id):
    """
    Fetch game data from IGDB API by exact IGDB ID.

    Args:
        igdb_id: IGDB game ID

    Returns:
        list: IGDB API response (list with one game dict), or None on error
    """
    from oneirodex.utils.igdb_api import make_igdb_api_request

    try:
        query = f"""
            fields id, name, summary, storyline, url, slug, first_release_date,
                   aggregated_rating, aggregated_rating_count, rating, rating_count,
                   total_rating, total_rating_count, status, category,
                   cover.url, screenshots.url, videos.video_id,
                   genres.name, themes.name, game_modes.name, platforms.name,
                   player_perspectives.name, involved_companies,
                   release_dates.date, release_dates.region, release_dates.platform;
            where id = {igdb_id};
            limit 1;
        """

        response = make_igdb_api_request(get_runtime_config()['IGDB_API_ENDPOINT'], query)

        if response and 'error' not in response and len(response) > 0:
            logger.info(f"Fetched game by ID {igdb_id}: {response[0].get('name')}")
            return response
        else:
            logger.error(f"Failed to fetch game by ID {igdb_id}: {response}")
            return None

    except Exception as e:
        logger.error(f"Error fetching game by IGDB ID {igdb_id}: {e}")
        return None
