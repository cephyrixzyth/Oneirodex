"""Deep store discounts for Discover (CheapShark, read-only).

Never checkout, never DRM download queues, never Game.store_specs prices.
Articles only: HTTPS redirect to the store product page. Ownership register
filters titles the household already owns (INSP-8).
"""

from __future__ import annotations

import threading
import time
from typing import Any
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import UserOwnedTitle
from oneirodex.utils.http_retry import request_with_backoff

CHEAPSHARK_DEALS_URL = 'https://www.cheapshark.com/api/1.0/deals'
# Steam, GOG, Humble Store, Epic Games Store
CHEAPSHARK_STORE_IDS = '1,7,11,25'
MIN_SAVINGS_PERCENT = 75.0
CACHE_TTL_SEC = 900
# CheapShark 400s python-requests / curl default UAs. Same house string as
# Giant Bomb / secondary scrapers.
USER_AGENT = 'Oneirodex/1.0 (self-hosted library)'
# Their Savings sort treats desc=0 as steepest-first. desc=1 returns 0% off.

_STORE_BY_ID = {
    '1': 'steam',
    '7': 'gog',
    '11': 'humble',
    '25': 'epic',
}

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {'at': 0.0, 'rows': []}


def _normalize_title(value: str) -> str:
    return ' '.join(''.join(ch.lower() if ch.isalnum() else ' ' for ch in (value or '')).split())


def fetch_cheapshark_deals(
    *,
    min_savings: float = MIN_SAVINGS_PERCENT,
    page_size: int = 60,
) -> list[dict[str, Any]] | None:
    """Live CheapShark deals at or above ``min_savings`` percent off.

    ``None`` is a transport or parse failure. An empty list is an honest
    pull with no qualifying deals.
    """
    response = request_with_backoff(
        CHEAPSHARK_DEALS_URL,
        host_key='cheapshark',
        params={
            'storeID': CHEAPSHARK_STORE_IDS,
            'pageSize': str(page_size),
            'sortBy': 'Savings',
            'desc': '0',
        },
        timeout=8,
        max_retries=2,
        headers={'User-Agent': USER_AGENT},
    )
    if response is None:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, list):
        return None

    out: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            savings = float(row.get('savings') or 0)
        except (TypeError, ValueError):
            continue
        if savings < min_savings:
            continue
        try:
            sale_price = Decimal(str(row.get('salePrice')))
        except (InvalidOperation, TypeError, ValueError):
            continue
        # Free promotions have their own Discover shelf. CheapShark can return
        # them alongside deep discounts, which otherwise duplicates the same
        # offer in both rows.
        if not sale_price.is_finite() or sale_price <= 0:
            continue
        deal_id = str(row.get('dealID') or '').strip()
        title = str(row.get('title') or '').strip()
        if not deal_id or not title:
            continue
        store_id = str(row.get('storeID') or '')
        store = _STORE_BY_ID.get(store_id, 'other')
        steam_app = str(row.get('steamAppID') or '').strip() or None
        thumb = str(row.get('thumb') or '').strip() or None
        # CheapShark's ``thumb`` is the short Steam capsule (roughly 460x215),
        # which reads as a banner inside Discover's 2:3 poster tile. Steam's
        # public library capsule is the matching portrait asset. Keep the
        # CheapShark image as a fallback for apps without that artwork.
        portrait = (
            f'https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app}/library_600x900_2x.jpg'
            if steam_app and steam_app.isdigit()
            else None
        )
        out.append({
            'deal_id': deal_id,
            'title': title,
            'store': store,
            'savings': round(savings),
            'sale_price': str(sale_price),
            'normal_price': str(row.get('normalPrice') or ''),
            'steam_app_id': steam_app,
            'image_url': portrait or thumb,
            'image_fallback_url': thumb if portrait else None,
            'href': f'https://www.cheapshark.com/redirect?dealID={deal_id}',
        })
    return out


def cached_deep_discounts(*, force: bool = False) -> list[dict[str, Any]]:
    now = time.monotonic()
    with _cache_lock:
        rows = list(_cache['rows'])
        age = now - float(_cache['at'])
        if not force and rows and age < CACHE_TTL_SEC:
            return rows
    fetched = fetch_cheapshark_deals()
    with _cache_lock:
        if fetched is None:
            # CheapShark 400/timeout must not wipe a good snapshot, or
            # Discover hides the shelf until the next successful poll.
            if _cache['rows']:
                return list(_cache['rows'])
            _cache['at'] = time.monotonic()
            _cache['rows'] = []
            return []
        _cache['at'] = time.monotonic()
        _cache['rows'] = list(fetched)
        return list(fetched)


def refresh_deep_discounts() -> int:
    """Force a CheapShark pull. Used by the boot poller."""
    return len(cached_deep_discounts(force=True))


def _owned_keys(user) -> tuple[set[tuple[str, str]], set[str]]:
    """(store, external_app_id) pairs and normalised titles the user owns."""
    if user is None or getattr(user, 'id', None) is None:
        return set(), set()
    rows = db.session.execute(
        select(UserOwnedTitle.store, UserOwnedTitle.external_app_id, UserOwnedTitle.name)
        .where(UserOwnedTitle.user_id == user.id)
    ).all()
    pairs: set[tuple[str, str]] = set()
    titles: set[str] = set()
    for store, app_id, name in rows:
        store_key = (store or '').strip().lower()
        app_key = (app_id or '').strip()
        if store_key and app_key:
            pairs.add((store_key, app_key))
        norm = _normalize_title(name or '')
        if norm:
            titles.add(norm)
    return pairs, titles


def list_deep_discount_articles(user, *, limit: int = 20) -> list[dict[str, Any]]:
    """Article payloads for the Discover ``store_deals`` shelf."""
    owned_pairs, owned_titles = _owned_keys(user)
    articles: list[dict[str, Any]] = []
    for deal in cached_deep_discounts():
        store = deal['store']
        steam_app = deal.get('steam_app_id')
        if store == 'steam' and steam_app and (store, steam_app) in owned_pairs:
            continue
        if _normalize_title(deal['title']) in owned_titles:
            continue
        savings = int(deal['savings'])
        articles.append({
            'kind': 'deal',
            'id': f"deal-{deal['deal_id']}",
            'title': deal['title'],
            'summary': f"{savings}% off · was {deal['normal_price']} · now {deal['sale_price']}",
            'image_url': deal.get('image_url'),
            'href': deal['href'],
            'store': store,
            'savings': savings,
            'published_at': None,
        })
        if len(articles) >= limit:
            break
    return articles
