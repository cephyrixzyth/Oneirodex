"""Free-game offers: fetch, normalize, claim deeplinks, DB sync (Wave 18)."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from oneirodex.utils.http_retry import request_with_backoff

VALID_STORES = frozenset({
    'steam', 'epic', 'gog', 'amazon', 'itch', 'humble', 'other',
})

EPIC_FREE_URL = (
    'https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions'
    '?locale=en-US&country=US&allowCountries=US'
)
STEAM_FEATURED_URL = 'https://store.steampowered.com/api/featuredcategories'
GAMERPOWER_URL = 'https://www.gamerpower.com/api/giveaways'

_GP_PLATFORM_MAP = {
    'steam': 'steam',
    'epic games': 'epic',
    'epic games store': 'epic',
    'epic': 'epic',
    'gog': 'gog',
    'itch.io': 'itch',
    'itch': 'itch',
    'amazon': 'amazon',
    'amazon games': 'amazon',
    'prime gaming': 'amazon',
    'humble': 'humble',
    'humble bundle': 'humble',
}

# Discover / News tiles are 2×3 cover frames. Prefer tall store keys so the art
# is not a wide banner cropped through the middle of a landscape key art.
_EPIC_TALL_IMAGE_TYPES = (
    'OfferImageTall',
    'DieselGameBoxTall',
    'DieselGameBox',
    'Thumbnail',
)
_EPIC_WIDE_IMAGE_TYPES = (
    'OfferImageWide',
    'DieselStoreFrontWide',
    'DieselGameBoxWide',
)


def _epic_cover_image_url(images: Any) -> str | None:
    """Pick a portrait-leaning Epic keyImage URL when the catalog offers one."""
    if not isinstance(images, list):
        return None
    by_type: dict[str, str] = {}
    fallback: str | None = None
    for img in images:
        if not isinstance(img, dict):
            continue
        url = (img.get('url') or '').strip()
        if not url:
            continue
        kind = str(img.get('type') or '')
        if kind:
            by_type[kind] = url
        if fallback is None:
            fallback = url
    for kind in _EPIC_TALL_IMAGE_TYPES:
        if kind in by_type:
            return by_type[kind]
    for kind in _EPIC_WIDE_IMAGE_TYPES:
        if kind in by_type:
            return by_type[kind]
    return fallback


def _steam_portrait_capsule_url(appid: str) -> str:
    """Steam's 600×900 library capsule — the 2×3 shape Discover tiles use.

    Not every app has one: the tall capsule is an optional upload, so older and
    free titles often 404 here while ``header.jpg`` always exists. The tile
    falls back through :func:`steam_image_fallback_url` on load error.
    """
    return (
        f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg'
    )


_STEAM_CAPSULE_SUFFIX = '/library_600x900.jpg'


def steam_image_fallback_url(image_url: str | None) -> str | None:
    """The wide ``header.jpg`` for a Steam 2×3 capsule URL, else None.

    Human, 2026-09-06: "news row again has missing 2x3 image (they do have
    image in other ratios)". The 600×900 capsule is the only shape the poller
    stored, and when Steam has no such upload the tile showed nothing although
    the store has a header. The card swaps to this on ``onError``; the
    letterbox rule already handles a wide image in a tall frame.
    """
    if not image_url or not image_url.endswith(_STEAM_CAPSULE_SUFFIX):
        return None
    return image_url[: -len(_STEAM_CAPSULE_SUFFIX)] + '/header.jpg'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # Epoch ms / s
    if text.isdigit():
        n = int(text)
        if n > 1_000_000_000_000:
            n //= 1000
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = text.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _stable_id(*parts: str) -> str:
    raw = '|'.join(p.strip().lower() for p in parts if p)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]


def normalize_store(label: str | None) -> str:
    if not label:
        return 'other'
    key = str(label).strip().lower()
    if key in VALID_STORES:
        return key
    mapped = _GP_PLATFORM_MAP.get(key)
    if mapped:
        return mapped
    for needle, store in _GP_PLATFORM_MAP.items():
        if needle in key:
            return store
    return 'other'


_STORE_WORDS = sorted(
    set(_GP_PLATFORM_MAP) | (VALID_STORES - {'other'}),
    key=len,
    reverse=True,
)
_STORE_PAREN_RE = re.compile(
    r'[\(\[]\s*(?:' + '|'.join(re.escape(w) for w in _STORE_WORDS) + r')'
    r'(?:\s+(?:store|games|gaming))?\s*[\)\]]',
    re.IGNORECASE,
)
# The qualifier chain deliberately excludes words that end real titles.
# `game` was in it once, and "Known Game (GOG) Giveaway" normalized to
# "known" — the chain ate the title's own last word, which would fold
# unrelated offers together. `key` would do the same to "Skeleton Key".
# Failing to strip only costs a missed dedupe; over-stripping loses an offer.
_TRAILING_GIVEAWAY_RE = re.compile(
    r'(?:\s*[-–—:|]\s*|\s+)'
    r'(?:free\s+|pc\s+|steam\s+)*'
    r'giveaway\s*$',
    re.IGNORECASE,
)


_TRAILING_PAREN_RE = re.compile(r'\s*[\(\[][^\)\]]*[\)\]]\s*$')


def dedupe_title_keys(title: str | None) -> set[str]:
    """Comparison keys that survive GamerPower's title decoration.

    GamerPower republishes offers the official feeds already carry, but with a
    qualifier and the word giveaway appended: Epic's "Alone With You" arrives
    as "Alone With You (Epic Games) Giveaway", so matching on the exact title
    let both through and the member saw the same game twice.

    The qualifier is not always a store — "(Mobile)", "(IndieGala)" and
    "(DRM-Free)" all show up — so rather than chase that vocabulary, a title
    gets a second key with its trailing parenthetical removed. Two keys instead
    of one, because dropping the parenthetical outright would fold a real
    "(Deluxe Edition)" into the base game; keeping both means the pair still
    matches when either side carries the suffix, and an offer is only ever
    dropped when something else in the feed genuinely covers it.
    """
    original = (title or '').strip()
    key = original.lower().replace('’', "'")
    previous = None
    while previous != key:
        previous = key
        key = _STORE_PAREN_RE.sub(' ', key)
        key = _TRAILING_GIVEAWAY_RE.sub('', key)
        key = key.strip(' -–—:|')
    key = re.sub(r'\s+', ' ', key).strip()
    # A title that is nothing but decoration keeps its raw form rather than
    # becoming the empty string, which would match every other stripped title.
    key = key or original.lower()
    keys = {key}
    trimmed = _TRAILING_PAREN_RE.sub('', key).strip()
    if trimmed:
        keys.add(trimmed)
    return keys


_HTTP_URL_RE = re.compile(r'^https?://[^\s/?#]', re.IGNORECASE)
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x1f\x7f]')


def http_url_or_none(value: Any) -> str | None:
    """The URL if it is an absolute ``http(s)`` URL, else ``None``.

    Offer feeds are untrusted. A ``javascript:`` or ``data:`` claim URL would
    otherwise be stored, returned by the API, handed to ``window.open`` and
    wrapped into a ``steam://openurl/`` deeplink. Control characters are
    refused outright: browsers strip a tab or newline inside a scheme, so a
    TAB-split ``javascript:`` must not get past a prefix check.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _CONTROL_CHAR_RE.search(text) or not _HTTP_URL_RE.match(text):
        return None
    return text


def claim_links(offer: dict[str, Any], connected_stores: set[str] | frozenset[str] | None = None) -> dict[str, str | None]:
    """HTTPS claim URL plus optional protocol deeplink when store is connected."""
    connected = {str(s).lower() for s in (connected_stores or set())}
    # Rows stored before claim URLs were scheme-checked are cleaned here too.
    https = http_url_or_none(offer.get('claim_url')) or http_url_or_none(offer.get('store_url'))
    store = normalize_store(offer.get('store'))
    protocol = None
    if https and store in connected:
        if store == 'steam':
            protocol = f'steam://openurl/{https}'
        elif store == 'epic':
            # Prefer launcher store deep link when path looks like a product page.
            path = urlparse(https).path or ''
            m = re.search(r'/p/([^/?#]+)', path)
            if m:
                slug = m.group(1)
                protocol = f'com.epicgames.launcher://store/en-US/p/{quote(slug)}'
            else:
                protocol = f'com.epicgames.launcher://open/{quote(https, safe="")}'
    return {'https': https, 'protocol': protocol}


def external_app_id_for_offer(offer: dict[str, Any] | Any) -> str | None:
    """Best-effort store app/product id for ownership register."""
    store = normalize_store(getattr(offer, 'store', None) or (offer.get('store') if isinstance(offer, dict) else None))
    eid = str(
        getattr(offer, 'external_id', None)
        or (offer.get('external_id') if isinstance(offer, dict) else '')
        or ''
    ).strip()
    claim = str(
        getattr(offer, 'claim_url', None)
        or (offer.get('claim_url') if isinstance(offer, dict) else '')
        or ''
    )
    if store == 'steam':
        if eid.isdigit():
            return eid
        m = re.search(r'/app/(\d+)', claim)
        if m:
            return m.group(1)
        if eid.startswith('gp-'):
            return None
        return eid or None
    if eid.startswith('gp-'):
        return eid[3:] or eid
    return eid or None


def claim_assist_for_user(user_id: int, offer: Any) -> dict[str, Any]:
    """
    Avenue B when a store is connected:
    - Register the offer on the ownership list (optimistic after member claims)
    - Steam: live GetOwnedGames sync when API key + Steam ID are set
    - Epic/GOG/Amazon: register-only upsert (no silent DRM claim API)

    Never downloads DRM titles. Deeplinks remain avenue A.
    """
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import StoreAccount
    from oneirodex.utils.store_ownership import (
        get_ownership_summary,
        is_ownership_sync_enabled,
        sync_steam_owned_games,
        upsert_owned_title,
    )

    store = normalize_store(getattr(offer, 'store', None))
    if store not in ('steam', 'gog', 'epic', 'amazon'):
        return {
            'ok': False,
            'error': f'Ownership assist not available for store {store}',
            'links': claim_links({
                'store': store,
                'claim_url': getattr(offer, 'claim_url', None),
                'store_url': getattr(offer, 'store_url', None),
            }),
        }

    account = db.session.execute(
        select(StoreAccount).where(
            StoreAccount.user_id == user_id,
            StoreAccount.store == store,
        )
    ).scalars().first()
    if account is None:
        return {
            'ok': False,
            'error': f'Connect {store} under Ownership first',
            'needs_connect': True,
            'links': claim_links({
                'store': store,
                'claim_url': getattr(offer, 'claim_url', None),
                'store_url': getattr(offer, 'store_url', None),
            }),
        }

    if not is_ownership_sync_enabled():
        return {'ok': False, 'error': 'Store ownership sync is disabled by administrator'}

    app_id = external_app_id_for_offer(offer)
    title = getattr(offer, 'title', None)
    registered = False
    if app_id:
        upsert_owned_title(user_id, store, app_id, title)
        db.session.commit()
        registered = True

    sync_result = None
    sync_error = None
    if store == 'steam':
        # Recorded as an ordinary sync job; only a catalogue sentence comes
        # back. str(exc) here once returned the Steam request URL, server key
        # included, to the member's browser.
        from oneirodex.utils.store_sync_errors import SyncOutcomeError, reason_payload
        from oneirodex.utils.store_sync_jobs import run_store_sync

        try:
            outcome = run_store_sync(user_id, 'steam', trigger='member', actor_id=user_id,
                                     sync_fn=sync_steam_owned_games)
        except SyncOutcomeError as exc:
            sync_error = reason_payload(exc.reason, 'Steam')['message']
        else:
            if outcome['job'].status in ('succeeded', 'partial'):
                sync_result = outcome['result']
            else:
                sync_error = reason_payload(outcome['reason'], 'Steam')['message']

    connected = {store}
    links = claim_links(
        {
            'store': store,
            'claim_url': getattr(offer, 'claim_url', None),
            'store_url': getattr(offer, 'store_url', None),
        },
        connected_stores=connected,
    )
    return {
        'ok': True,
        'store': store,
        'registered': registered,
        'external_app_id': app_id,
        'sync': sync_result,
        'sync_error': sync_error,
        'links': links,
        'summary': get_ownership_summary(user_id),
        'message': (
            'Registered on your ownership list'
            + ('; Steam library re-synced' if sync_result else '')
            + '. Claim still happens on the store (deeplink).'
        ),
    }


def fetch_epic_free_games() -> list[dict[str, Any]]:
    resp = request_with_backoff(
        EPIC_FREE_URL,
        host_key='epic',
        timeout=15,
        headers={'User-Agent': 'Oneirodex/0.2 (free-games)'},
    )
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    elements = (
        ((payload.get('data') or {}).get('Catalog') or {})
        .get('searchStore', {})
        .get('elements')
        or []
    )
    out: list[dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        promotions = el.get('promotions') or {}
        current = promotions.get('promotionalOffers') or []
        if not current:
            continue
        # Only include if a promotional offer has a 0% discount window now
        offer_window = None
        for block in current:
            for offer in (block.get('promotionalOffers') or []):
                start = _parse_dt(offer.get('startDate'))
                end = _parse_dt(offer.get('endDate'))
                discount = ((offer.get('discountSetting') or {}).get('discountPercentage'))
                if discount is not None and int(discount) != 0:
                    continue
                offer_window = (start, end)
                break
            if offer_window:
                break
        if not offer_window:
            continue
        title = (el.get('title') or '').strip()
        if not title or title.lower() == 'mystery game':
            continue
        slug = (el.get('productSlug') or el.get('urlSlug') or '').strip().rstrip('/')
        page_slug = None
        for page in (el.get('catalogNs') or {}).get('mappings') or []:
            if isinstance(page, dict) and page.get('pageType') == 'productHome':
                page_slug = (page.get('pageSlug') or '').strip()
                break
        path_slug = page_slug or slug
        if not path_slug:
            continue
        claim = f'https://store.epicgames.com/en-US/p/{path_slug}'
        image_url = _epic_cover_image_url(el.get('keyImages') or [])
        eid = str(el.get('id') or _stable_id('epic', path_slug, title))
        out.append({
            'store': 'epic',
            'external_id': eid,
            'title': title[:255],
            'description': (el.get('description') or '')[:500] or None,
            'image_url': image_url,
            'claim_url': claim,
            'store_url': claim,
            'worth': None,
            'starts_at': offer_window[0],
            'ends_at': offer_window[1],
            'source': 'epic',
        })
    return out


def fetch_steam_free_games() -> list[dict[str, Any]]:
    resp = request_with_backoff(
        STEAM_FEATURED_URL,
        host_key='steam',
        params={'l': 'english', 'cc': 'US'},
        timeout=15,
        headers={'User-Agent': 'Oneirodex/0.2 (free-games)'},
    )
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for section_key in ('specials', 'top_sellers', 'new_releases', 'coming_soon'):
        section = payload.get(section_key) or {}
        items = section.get('items') if isinstance(section, dict) else None
        if not items:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            # final == 0 and original > 0 → free promo; or discount_percent == 100
            final = item.get('final')
            original = item.get('original')
            discount = item.get('discount_percent')
            is_free = (
                (discount is not None and int(discount) == 100)
                or (final is not None and int(final) == 0 and original is not None and int(original) > 0)
            )
            if not is_free:
                continue
            appid = item.get('id')
            if appid is None:
                continue
            eid = str(appid)
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            name = (item.get('name') or f'Steam app {eid}').strip()
            claim = f'https://store.steampowered.com/app/{eid}/'
            # Portrait library capsule — Discover tiles are 2×3 cover frames.
            image_url = _steam_portrait_capsule_url(eid)
            out.append({
                'store': 'steam',
                'external_id': eid,
                'title': name[:255],
                'description': None,
                'image_url': image_url,
                'claim_url': claim,
                'store_url': claim,
                'worth': None,
                'starts_at': None,
                'ends_at': None,
                'source': 'steam',
            })
    return out


def fetch_gamerpower_giveaways() -> list[dict[str, Any]]:
    resp = request_with_backoff(
        GAMERPOWER_URL,
        host_key='gamerpower',
        params={'type': 'game'},
        timeout=20,
        headers={'User-Agent': 'Oneirodex/0.2 (free-games)'},
    )
    if resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        status = (item.get('status') or '').lower()
        if status and status not in ('active',):
            continue
        title = (item.get('title') or '').strip()
        # Only http(s) survives; a hostile feed serving javascript: or data:
        # loses the offer rather than reaching the browser.
        claim = (
            http_url_or_none(item.get('open_giveaway_url'))
            or http_url_or_none(item.get('gamerpower_url'))
            or ''
        )
        if not title or not claim:
            continue
        platforms = item.get('platforms') or ''
        # Prefer first mapped platform
        store = 'other'
        for part in re.split(r'[,/|]', str(platforms)):
            store = normalize_store(part.strip())
            if store != 'other':
                break
        eid = str(item.get('id') or _stable_id('gp', title, claim))
        # GamerPower only ships wide banners, which crop through the middle of
        # the key art in Discover's 2×3 frame. A Steam giveaway carries its
        # appid in the claim URL, and Steam's portrait capsule is a
        # deterministic URL off that — so those tiles can have real cover art
        # without a lookup. Other stores keep the banner; there is no
        # equivalent well-known portrait for them.
        appid = re.search(r'/app/(\d+)', claim)
        image_url = item.get('image') or item.get('thumbnail')
        portrait = False
        if store == 'steam' and appid:
            image_url = _steam_portrait_capsule_url(appid.group(1))
            portrait = True
        out.append({
            'store': store,
            'external_id': f'gp-{eid}',
            'title': title[:255],
            'description': (item.get('description') or '')[:500] or None,
            'image_url': image_url,
            # Consumed by collect_remote_offers, not persisted — says whether
            # this offer still needs a cover looked up.
            'portrait': portrait,
            'claim_url': claim,
            'store_url': claim,
            'worth': (str(item.get('worth')).strip() if item.get('worth') else None),
            'starts_at': _parse_dt(item.get('published_date')),
            'ends_at': _parse_dt(item.get('end_date')),
            'source': 'gamerpower',
        })
    return out


_COVER_TTL_SEC = 30 * 24 * 3600
_cover_cache: dict[str, tuple[str | None, float]] = {}


def _cover_lookup_enabled() -> bool:
    """False outside an app context — there are no IGDB credentials there."""
    try:
        from flask import current_app

        return bool(current_app.config.get('ENABLE_FREE_GAMES_COVER_LOOKUP', True))
    except RuntimeError:
        return False


def clear_cover_cache() -> None:
    """Test helper — drop memoized IGDB cover lookups."""
    _cover_cache.clear()


def igdb_cover_for_title(title: str) -> str | None:
    """A 2×3 IGDB cover for a giveaway title, or None.

    GOG, itch, Humble and IndieGala offers — and Epic ones routed through
    GamerPower — have no well-known portrait URL the way Steam does, so the
    only way to get real cover art is to look the title up.

    Memoized for a month and keyed on the *normalized* title, so the 3-hourly
    sync costs one call per distinct game rather than one per sync, and a miss
    is cached too — a title IGDB does not know must not be re-asked every time.
    """
    keys = sorted(dedupe_title_keys(title))
    if not keys:
        return None
    key = keys[0]
    hit = _cover_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[1] < _COVER_TTL_SEC:
        return hit[0]

    from oneirodex.utils.igdb_api import make_igdb_api_request

    # `search` is IGDB's fuzzy match; the where-clause keeps rows that can
    # actually answer the question we are asking.
    query = (
        f'search "{key.replace(chr(34), "")}"; '
        'fields name,cover.image_id; where cover != null; limit 1;'
    )
    url = None
    try:
        response = make_igdb_api_request('https://api.igdb.com/v4/games', query)
        if isinstance(response, list) and response:
            image_id = (response[0].get('cover') or {}).get('image_id')
            if image_id:
                url = (
                    'https://images.igdb.com/igdb/image/upload/'
                    f't_cover_big_2x/{image_id}.jpg'
                )
    except Exception:
        # A cover is decoration. A provider outage must not fail the sync that
        # brings in the offers themselves — the banner stays and we retry on
        # the next TTL window.
        url = None

    _cover_cache[key] = (url, now)
    return url


def collect_remote_offers() -> dict[str, list[dict[str, Any]]]:
    """Fetch per source (empty list still counts so stale rows can deactivate)."""
    official_epic = fetch_epic_free_games()
    official_steam = fetch_steam_free_games()
    gp = fetch_gamerpower_giveaways()
    official_keys = {
        (o['store'], key)
        for o in (official_epic + official_steam)
        for key in dedupe_title_keys(o['title'])
    }
    gp_filtered = [
        o for o in gp
        if not any(
            (o['store'], key) in official_keys for key in dedupe_title_keys(o['title'])
        )
    ]
    if _cover_lookup_enabled():
        for offer in gp_filtered:
            if offer.get('portrait'):
                continue
            cover = igdb_cover_for_title(offer['title'])
            if cover:
                offer['image_url'] = cover
                offer['portrait'] = True
    return {
        'epic': official_epic,
        'steam': official_steam,
        'gamerpower': gp_filtered,
    }


def offer_to_api_dict(
    row: Any,
    *,
    connected_stores: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    base = {
        'id': getattr(row, 'id', None),
        'store': row.store,
        'external_id': row.external_id,
        'title': row.title,
        'description': row.description,
        'image_url': row.image_url,
        'claim_url': http_url_or_none(row.claim_url),
        'store_url': http_url_or_none(row.store_url),
        'worth': row.worth,
        'starts_at': row.starts_at.isoformat() if row.starts_at else None,
        'ends_at': row.ends_at.isoformat() if row.ends_at else None,
        'source': row.source,
        'active': bool(row.active),
        'first_seen_at': row.first_seen_at.isoformat() if row.first_seen_at else None,
        'last_seen_at': row.last_seen_at.isoformat() if row.last_seen_at else None,
        'connected': row.store in (connected_stores or set()),
    }
    links = claim_links(base, connected_stores)
    base['links'] = links
    return base


def sync_free_game_offers(*, notify: bool = True) -> dict[str, int]:
    """Upsert remote offers; deactivate missing per source; optionally notify on inserts."""
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import FreeGameOffer

    by_source = collect_remote_offers()
    now = _now()
    fetched = sum(len(v) for v in by_source.values())

    had_rows = db.session.execute(select(FreeGameOffer.id).limit(1)).first() is not None
    new_rows: list[FreeGameOffer] = []

    for source, offers in by_source.items():
        seen_ids: set[str] = set()
        for offer in offers:
            eid = offer['external_id']
            seen_ids.add(eid)
            row = db.session.execute(
                select(FreeGameOffer).where(
                    FreeGameOffer.store == offer['store'],
                    FreeGameOffer.external_id == eid,
                )
            ).scalars().first()
            if row is None:
                row = FreeGameOffer(
                    store=offer['store'],
                    external_id=eid,
                    title=offer['title'],
                    description=offer.get('description'),
                    image_url=offer.get('image_url'),
                    claim_url=offer.get('claim_url'),
                    store_url=offer.get('store_url'),
                    worth=offer.get('worth'),
                    starts_at=offer.get('starts_at'),
                    ends_at=offer.get('ends_at'),
                    source=source,
                    active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                db.session.add(row)
                new_rows.append(row)
            else:
                row.title = offer['title']
                row.description = offer.get('description')
                row.image_url = offer.get('image_url')
                row.claim_url = offer.get('claim_url')
                row.store_url = offer.get('store_url')
                row.worth = offer.get('worth')
                row.starts_at = offer.get('starts_at') or row.starts_at
                row.ends_at = offer.get('ends_at') or row.ends_at
                row.source = source
                row.active = True
                row.last_seen_at = now

        # Deactivate stale rows for this source (even if offers list is empty)
        existing = db.session.execute(
            select(FreeGameOffer).where(FreeGameOffer.source == source)
        ).scalars().all()
        for row in existing:
            if row.external_id not in seen_ids:
                row.active = False
                row.last_seen_at = now

    db.session.commit()

    notified = 0
    if notify and had_rows and new_rows:
        notified = notify_new_free_games(new_rows)

    return {
        'fetched': fetched,
        'inserted': len(new_rows),
        'notified': notified,
        'sources': len(by_source),
    }


def notify_new_free_games(rows: list[Any]) -> int:
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import User
    from oneirodex.utils.notifications import notify_user

    users = db.session.execute(select(User.id)).scalars().all()
    count = 0
    for row in rows[:20]:
        title = f'Free on {str(row.store).title()}: {row.title}'
        body = 'Claim it before it ends — see News → Free now.'
        for user_id in users:
            created = notify_user(
                user_id,
                kind='free_game',
                title=title[:200],
                body=body,
                link='/news#free-games',
                payload={
                    'store': row.store,
                    'external_id': row.external_id,
                    'claim_url': row.claim_url,
                },
                pref_flag='notify_free_games',
            )
            if created:
                count += 1
    return count


def list_active_offers(
    *,
    store: str | None = None,
    limit: int = 40,
    connected_stores: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import FreeGameOffer

    q = select(FreeGameOffer).where(FreeGameOffer.active.is_(True))
    if store:
        q = q.where(FreeGameOffer.store == normalize_store(store))
    q = q.order_by(FreeGameOffer.first_seen_at.desc())
    rows = db.session.execute(q.limit(max(1, min(limit, 100)))).scalars().all()
    return [offer_to_api_dict(r, connected_stores=connected_stores) for r in rows]


def connected_stores_for_user(user_id: int) -> set[str]:
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import StoreAccount

    rows = db.session.execute(
        select(StoreAccount.store).where(StoreAccount.user_id == user_id)
    ).scalars().all()
    return {str(s).lower() for s in rows if s}
