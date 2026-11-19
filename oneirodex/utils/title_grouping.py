"""Catalog grouping keys and platform ordering."""

from __future__ import annotations

import unicodedata

from sqlalchemy import case, func

from oneirodex.platform_recency import PLATFORM_LAUNCH_YEAR, platform_rank


def normalize_title(value: str | None) -> str:
    """Case-fold a title while retaining letters, numbers and combining marks in every script."""
    folded = unicodedata.normalize('NFC', (value or '').casefold())
    tokens = ''.join(
        char if unicodedata.category(char)[0] in ('L', 'M', 'N') else ' '
        for char in folded
    )
    return ' '.join(tokens.split())


def title_key_expr(game):
    """Rows with no usable key remain individually visible."""
    return func.coalesce(func.nullif(game.browse_title_key, ''), '#' + game.uuid)


def platform_rank_case(platform_column):
    """SQL CASE ranking a platform column by hardware recency; higher is newer.

    Built from `PLATFORM_LAUNCH_YEAR` rather than restated, so the table stays
    the single source of truth and `test_platform_recency.py` guards both uses.
    Anything unmatched falls to 0, which is how an unranked platform loses the
    representative slot instead of winning it by accident.
    """
    return case(
        {name: rank for name, rank in PLATFORM_LAUNCH_YEAR.items()},
        value=platform_column,
        else_=0,
    )


def platforms_newest_first(platform_keys) -> list[str]:
    """Distinct platforms ordered newest hardware first, ties alphabetical.

    The order is the payload's promise: the client reads element 0 as "the
    latest system this was released on" and never has to know about ranking.
    Ties are broken by name so a tile does not swap systems between page loads.
    """
    unique = {str(key) for key in (platform_keys or []) if key}
    return sorted(unique, key=lambda key: (-platform_rank(key), key))


def editions_by_title_key(rows) -> dict[str, list[str]]:
    """Group `(title_key, platform_key)` pairs into platforms per title.

    Takes the rows of one bulk lookup for a whole page rather than a query per
    tile: the page is at most `per_page` titles, so this is one extra round trip
    for the grid instead of up to a thousand.
    """
    grouped: dict[str, set[str]] = {}
    for title_key, platform_key in rows:
        if not title_key:
            continue
        grouped.setdefault(str(title_key), set())
        if platform_key:
            grouped[str(title_key)].add(str(platform_key))
    return {key: platforms_newest_first(values) for key, values in grouped.items()}
