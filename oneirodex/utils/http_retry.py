import time
import random
import threading
import requests

from oneirodex.utils.http_safe import BlockedOutboundUrl, safe_get
from oneirodex.utils.security import validate_user_outbound_http_url

_last_request_at = {}
_lock = threading.Lock()
_MIN_INTERVAL_SEC = {
    'steam': 1.0,
    'rawg': 1.0,
    'gog': 1.0,
    'epic': 1.0,
    'itch': 1.0,
    'giantbomb': 1.0,
    # MobyGames non-commercial: max ~1 req/sec (720/hr).
    'mobygames': 1.0,
    # TheGamesDB free tier is monthly-quota limited — keep polite spacing.
    'thegamesdb': 1.0,
    # CheapShark public deals API — keep polite spacing.
    'cheapshark': 1.0,
}


def request_with_backoff(url, *, host_key, params=None, timeout=5, max_retries=3, headers=None):
    """GET with per-host min interval and exponential backoff on 429/5xx/timeout."""
    min_interval = _MIN_INTERVAL_SEC.get(host_key, 0.5)
    last_exc = None

    for attempt in range(max_retries):
        with _lock:
            now = time.monotonic()
            last = _last_request_at.get(host_key, 0.0)
            wait = min_interval - (now - last)
            if wait > 0:
                time.sleep(wait)
            _last_request_at[host_key] = time.monotonic()

        try:
            # Every host_key here is a public metadata/store provider, so the
            # never-LAN validator is the right one — and it now applies to
            # redirect hops too, not just the URL we were handed.
            resp = safe_get(
                url,
                validator=validate_user_outbound_http_url,
                params=params,
                timeout=timeout,
                headers=headers,
            )
        except BlockedOutboundUrl as exc:
            # A blocked hop is a policy decision, not a transient failure —
            # retrying only repeats it.
            print(f"http_retry blocked for {host_key}: {exc.reason}")
            return None
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep((2 ** attempt) + random.uniform(0, 0.25))
            continue

        if resp.status_code == 200:
            return resp
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep((2 ** attempt) + random.uniform(0, 0.25))
            continue
        return None

    if last_exc:
        # Request exceptions often include the fully prepared URL. Some public
        # metadata providers accept API keys in query parameters, so logging
        # the exception here can persist those credentials in container logs.
        print(
            f"http_retry exhausted for {host_key}: "
            f"{type(last_exc).__name__}"
        )
    return None
