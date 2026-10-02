"""Badge / chip filters for /browse_games (aligned with badgeSignals.ts)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import false

from oneirodex.models import Game
from oneirodex.utils.filter_tree import (  # noqa: F401 -- window constants re-exported
    FIELDS as TREE_FIELDS,
    FilterTreeError,
    NEW_IMPORT_WINDOW_DAYS,
    RELEASE_WINDOW_DAYS,
    compile_filter_tree,
)
from oneirodex.utils.item_kind import parse_item_kinds_param
from oneirodex.utils.library_health import (
    PATH_STATUS_EMPTY,
    PATH_STATUS_MISSING,
    PATH_STATUS_OK,
)
from oneirodex.utils.secondary_scrapers import VR_COMPAT_VALUES
from oneirodex.utils.ownership_filters import apply_ownership_filters

_PATH_STATUS_ALLOWED = frozenset({
    PATH_STATUS_OK,
    PATH_STATUS_MISSING,
    PATH_STATUS_EMPTY,
})

# NEW_IMPORT_WINDOW_DAYS / RELEASE_WINDOW_DAYS now live in filter_tree, beside
# the clauses that read them, and are re-exported above because callers and
# tests have always imported them from this module.
# Keep both in sync with frontend/member-app/src/utils/badgeSignals.ts.

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


def _flag(args, name: str) -> bool:
    raw = args.get(name, '')
    if raw is None:
        return False
    return str(raw).strip().lower() in _TRUTHY


def _preferred_locale_from_user(user: Any | None) -> str:
    if user is None:
        return 'en-US'
    prefs = getattr(user, 'preferences', None)
    if prefs is None:
        return 'en-US'
    return getattr(prefs, 'preferred_game_locale', None) or 'en-US'


def _item_kind_raw_from_args(args) -> str | None:
    """Collect ``item_kind`` / ``content_kind`` (single, comma list, or repeated)."""
    parts: list[str] = []
    getlist = getattr(args, 'getlist', None)
    if callable(getlist):
        for key in ('item_kind', 'content_kind'):
            for value in getlist(key) or []:
                if value is not None and str(value).strip():
                    parts.append(str(value).strip())
    else:
        for key in ('item_kind', 'content_kind'):
            value = args.get(key) if hasattr(args, 'get') else None
            if value is not None and str(value).strip():
                parts.append(str(value).strip())
    if not parts:
        return None
    return ','.join(parts)


def apply_name_filter(query, args):
    """Filter by title substring ``name=`` (alias ``q=``).

    Case-insensitive ``ILIKE %name%``. Blank / whitespace → no filter.
    When both are present, ``name`` wins.
    """
    raw_name = args.get('name') if hasattr(args, 'get') else None
    raw_q = args.get('q') if hasattr(args, 'get') else None
    name = (raw_name or raw_q or '').strip()
    if not name:
        return query
    return query.filter(Game.name.ilike(f'%{name}%'))


def apply_item_kind_filter(query, args):
    """Filter by ``item_kind=`` / ``content_kind=`` (game|experience|emulator|tool).

    Omit / blank → no filter (all kinds). Comma list or repeated params OK.
    Unknown tokens ignored; only-unknown → empty result set.
    """
    kinds = parse_item_kinds_param(_item_kind_raw_from_args(args))
    if kinds is None:
        return query
    if not kinds:
        return query.filter(false())
    return query.filter(Game.item_kind.in_(tuple(sorted(kinds))))


def apply_path_status_filter(query, args):
    """Filter by ``path_status=ok|missing|empty`` (comma list OK).

    Cheap SQL on persisted scan signal — for admin/librarian missing-path tools.
    Unknown tokens ignored; only-unknown → empty result set. Omit / blank → no filter.
    """
    raw = None
    getlist = getattr(args, 'getlist', None)
    if callable(getlist):
        parts = [str(v).strip() for v in (getlist('path_status') or []) if v is not None]
        if parts:
            raw = ','.join(parts)
    if raw is None:
        value = args.get('path_status') if hasattr(args, 'get') else None
        if value is not None and str(value).strip():
            raw = str(value).strip()
    if not raw:
        return query
    values = []
    for token in raw.split(','):
        token = token.strip().lower()
        if token in _PATH_STATUS_ALLOWED and token not in values:
            values.append(token)
    if not values:
        return query.filter(false())
    return query.filter(Game.path_status.in_(tuple(values)))


def apply_badge_filters(query, args, *, user=None, now: datetime | None = None):
    """Apply optional badge chip query params to a Game select/query.

    Params (any of):
      is_vr=1
      vr_compat=…         — native_vr|injector_profile|flat (rider R3; native_vr also admits derived VR)
      freshness_behind=1  — OUT / ~ (behind | heuristic_behind)
      has_updates=1       — freshness behind OR local GameUpdate rows
      new_import=1        — date_identified/date_created within 14 days
      recent_release=1    — first_release_date within 30 days
      needs_translation=1 — ROM lang known and mismatches preferred_game_locale
      item_kind=…         — game|experience|emulator|tool (comma list / repeated)
      content_kind=…      — alias of item_kind
      path_missing=1      — MISSING badge chip (files gone from disk)
      path_status=…       — ok|missing|empty (comma list; admin/librarian tools)
      name=… / q=…        — case-insensitive title substring (Library type-to-search)
      store=…            — current member's recorded ownership (comma/repeated IDs)
      store_match=any|all — union/intersection of selected stores (default any)
      ownership=owned|unrecorded — no record is not proof of non-ownership
    """
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    query = apply_name_filter(query, args)
    query = apply_ownership_filters(query, args, user=user)

    # Every chip is one leaf of the same vocabulary the filter tree speaks, so
    # both compile through `filter_tree.FIELDS` rather than keeping a second
    # copy of each predicate here that could drift from it.
    ctx = {'user': user, 'now': clock}
    for field in (
        'is_vr',
        'freshness_behind',
        'has_updates',
        'new_import',
        'recent_release',
        'needs_translation',
        'path_missing',
    ):
        if _flag(args, field):
            query = query.filter(TREE_FIELDS[field][2](True, ctx))

    vr_compat = str(args.get('vr_compat') or '').strip().lower()
    if vr_compat in VR_COMPAT_VALUES:
        query = query.filter(TREE_FIELDS['vr_compat'][2](vr_compat, ctx))

    query = apply_item_kind_filter(query, args)
    query = apply_path_status_filter(query, args)
    return query


def apply_filter_tree(query, args, *, user=None, now: datetime | None = None):
    """Apply ``filter_tree=<json>`` when present (INSP-3).

    Deliberately a *conjunct* beside the chips rather than a replacement: a
    member who has built a tree and then taps a chip means both, and a tree
    that silently discarded the chips would be the surprising reading.

    Raises ``FilterTreeError`` -- the caller turns it into a 400 that says
    which part of the filter is wrong.
    """
    raw = args.get('filter_tree') if hasattr(args, 'get') else None
    if raw is None or not str(raw).strip():
        return query
    return query.filter(compile_filter_tree(raw, user=user, now=now))


def filter_tree_error_detail(exc: FilterTreeError) -> str:
    """One sentence a builder UI can put next to the offending row."""
    return str(exc)
