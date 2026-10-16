# File: /oneirodex/igdb_api.py
# This file contains functions for interacting with the IGDB API extracted from routes.py

import requests
import time
import threading
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.global_settings import global_settings_row
from sqlalchemy import select



def make_igdb_api_request(endpoint_url, query_params):
    # Get IGDB settings from database
    settings = global_settings_row()
    if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
        return {"error": "IGDB settings not configured in database"}

    access_token = get_access_token(settings.igdb_client_id, settings.igdb_client_secret) 

    if not access_token:
        return {"error": "Failed to retrieve access token"}

    headers = {
        'Client-ID': settings.igdb_client_id,
        'Authorization': f"Bearer {access_token}"
    }

    try:
        # print(f"make_igdb_api_request Attempting to make a request to {endpoint_url} with headers: {headers} and query: {query_params}")
        response = requests.post(endpoint_url, headers=headers, data=query_params, timeout=20)
        response.raise_for_status()
        # print(f"make_igdb_api_request Response from IGDB API: {data}")
        return response.json()

    except requests.RequestException as e:
        return {"error": f"make_igdb_api_request API Request failed: {e}"}

    except ValueError:
        return {"error": "make_igdb_api_request Invalid JSON in response"}

    except Exception as e:
        return {"error": f"make_igdb_api_request An unexpected error occurred: {e}"}
    
# Twitch client-credentials tokens last ~60m; cache with a safety margin.
_token_lock = threading.Lock()
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}
_TOKEN_REFRESH_SKEW_SEC = 60


def clear_access_token_cache():
    """Test helper — drop cached Twitch tokens."""
    with _token_lock:
        _token_cache.clear()


def get_access_token(client_id, client_secret):
    key = (str(client_id or ''), str(client_secret or ''))
    now = time.time()
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] > now + _TOKEN_REFRESH_SKEW_SEC:
            return cached[0]

    url = "https://id.twitch.tv/oauth2/token"
    params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, params=params, timeout=15)
    if response.status_code == 200:
        payload = response.json()
        token = payload.get('access_token')
        if not token:
            print("Failed to obtain access token")
            return None
        expires_in = int(payload.get('expires_in') or 3600)
        with _token_lock:
            _token_cache[key] = (token, now + max(120, expires_in))
        return token
    else:
        print("Failed to obtain access token")
        return None



def get_cover_thumbnail_url(igdb_id):
    """
    Takes an IGDB ID number and returns the URL to the cover thumbnail.

    Parameters:
    igdb_id (int): The IGDB ID of the game.

    Returns:
    str: The URL of the cover thumbnail, or None if not found.
    """
    cover_query = f'fields url; where game={igdb_id};'
    response = make_igdb_api_request('https://api.igdb.com/v4/covers', cover_query)

    if response and 'error' not in response and len(response) > 0:
        cover_url = response[0].get('url')
        if cover_url:

            return 'https:' + cover_url
        else:
            print(f"No cover URL found for IGDB ID {igdb_id}.")
    else:
        print(f"Failed to retrieve cover for IGDB ID {igdb_id}. Response: {response}")

    return None
    
def get_cover_url(igdb_id):
    """
    Takes an IGDB ID number and returns the cover URL to the cover.

    Parameters:
    igdb_id (int): The IGDB ID of the game.

    Returns:
    str: The cover URL of the cover image, or None if not found.
    """
    cover_query = f'fields image_id; where game={igdb_id};'
    response = make_igdb_api_request('https://api.igdb.com/v4/covers', cover_query)

    if response and 'error' not in response and len(response) > 0:
        cover_image_id = response[0].get('image_id')
        if cover_image_id:

            return 'https://images.igdb.com/igdb/image/upload/t_cover_big_2x/' + cover_image_id + '.jpg'
        else:
            print(f"No cover image ID found for IGDB ID {igdb_id}.")
    else:
        print(f"Failed to retrieve cover image ID for IGDB ID {igdb_id}. Response: {response}")

    return None


class IGDBRateLimiter:
    """
    Rate limiter for IGDB API scanning operations.
    Ensures compliance with IGDB rate limits: 4 requests/second, max 8 concurrent requests.
    """
    def __init__(self, max_requests_per_second=4, max_concurrent_requests=8):
        self.max_requests_per_second = max_requests_per_second
        self.max_concurrent_requests = max_concurrent_requests
        self.request_times = []
        self.concurrent_requests = 0
        self.lock = threading.Lock()
        
    def acquire(self):
        """Acquire permission to make an IGDB API request.

        Sleeps outside the lock so release() from other threads can proceed
        (sleeping while holding the lock deadlocks when concurrent slots are full).
        """
        while True:
            rate_sleep = None
            with self.lock:
                if self.concurrent_requests >= self.max_concurrent_requests:
                    rate_sleep = 0.05
                else:
                    current_time = time.time()
                    self.request_times = [
                        req_time for req_time in self.request_times
                        if current_time - req_time < 1.0
                    ]
                    if len(self.request_times) >= self.max_requests_per_second:
                        rate_sleep = max(0.0, 1.0 - (current_time - self.request_times[0]))
                    else:
                        self.request_times.append(current_time)
                        self.concurrent_requests += 1
                        return

            if rate_sleep is not None and rate_sleep > 0:
                time.sleep(rate_sleep)

            # After waiting out a rate window, grant a slot (same as pre-fix behavior).
            if rate_sleep is not None and rate_sleep != 0.05:
                with self.lock:
                    if self.concurrent_requests >= self.max_concurrent_requests:
                        continue
                    current_time = time.time()
                    self.request_times = [
                        req_time for req_time in self.request_times
                        if current_time - req_time < 1.0
                    ]
                    self.request_times.append(current_time)
                    self.concurrent_requests += 1
                    return
            
    def release(self):
        """Release a concurrent request slot."""
        with self.lock:
            self.concurrent_requests = max(0, self.concurrent_requests - 1)

