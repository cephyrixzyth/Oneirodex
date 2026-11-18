"""Canonical game image kind taxonomy (BE-DET-10).

Persisted on ``Image.image_type``. Existing cover/screenshot rows map 1:1.
No scrapers — taxonomy only for API persist + queue/filter.
"""

from __future__ import annotations

# Locked GM/Art taxonomy (Art Studio / UI filter later).
IMAGE_KINDS: frozenset[str] = frozenset({
    'cover',
    'screenshot',
    'box',
    'cart',
    'disc',
    'logo',
    'hero',
    'fanart',
})

# Ordered for API docs / UI pickers.
IMAGE_KIND_ORDER: tuple[str, ...] = (
    'cover',
    'screenshot',
    'box',
    'cart',
    'disc',
    'logo',
    'hero',
    'fanart',
)

# At most one primary row per game (screenshots stay multi).
SINGULAR_IMAGE_KINDS: frozenset[str] = frozenset({
    'cover',
    'box',
    'cart',
    'disc',
    'logo',
    'hero',
    'fanart',
})

# Safe aliases → locked kind (never invent new public kinds).
_KIND_ALIASES: dict[str, str] = {
    'cart_label': 'cart',
    'disc_label': 'disc',
    'fan_art': 'fanart',
    'fan-art': 'fanart',
    'clearlogo': 'logo',
    'grid': 'cover',  # SteamGridDB grids → cover
}

# IGDB download endpoints only exist for these.
IGDB_DOWNLOAD_KINDS: frozenset[str] = frozenset({'cover', 'screenshot'})

# SteamGridDB search surface (provider API limitation).
STEAMGRIDDB_SEARCH_KINDS: frozenset[str] = frozenset({'cover', 'logo', 'hero'})


def normalize_image_kind(raw: str | None, *, default: str | None = None) -> str | None:
    """Normalize and coerce aliases. Returns None if empty and no default."""
    if raw is None or not str(raw).strip():
        return default
    kind = str(raw).strip().lower()
    kind = _KIND_ALIASES.get(kind, kind)
    return kind


def parse_image_kind(
    raw: str | None,
    *,
    default: str | None = 'cover',
    allow_all: bool = False,
) -> str:
    """
    Parse a kind for persist/filter.

    Raises ValueError on unknown kinds (unless allow_all and value is ``all``).
    """
    if allow_all:
        if raw is None or not str(raw).strip() or str(raw).strip().lower() == 'all':
            return 'all'
    kind = normalize_image_kind(raw, default=default)
    if kind is None:
        raise ValueError('image_type is required')
    if kind not in IMAGE_KINDS:
        allowed = ', '.join(IMAGE_KIND_ORDER)
        raise ValueError(f'image_type must be one of: {allowed}')
    return kind


def image_kinds_error_message() -> str:
    return 'image_type must be one of: ' + ', '.join(IMAGE_KIND_ORDER)
