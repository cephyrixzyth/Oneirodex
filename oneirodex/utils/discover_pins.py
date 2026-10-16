"""Which rows sit at the top of a member's feed, and who decided.

Two independent sources fill the reserved block the feed budget keeps free:
an admin forcing a shelf for everyone, and a member pinning rows for
themselves. Both are capped, so neither can starve the other — an admin keeps a
dependable announcement position, and a member's pins can never be pushed below
the fold on their own home page.

Reading is deliberately forgiving. A pinned row is allowed to stop existing: a
genre row can go away when a member's taste moves, and an admin can hide a shelf
that somebody had pinned. Neither is an error, so an identifier that no longer
resolves is dropped on read rather than raised.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import DiscoverySection, UserPreference
from oneirodex.utils.discover_feed import MAX_ADMIN_FORCED, MAX_MEMBER_PINS


class PinnedByAdmin(ValueError):
    """Raised when a member tries to hide a shelf an admin forced on everyone."""


def _stored_list(user, attribute: str) -> list[str]:
    """A raw identifier list off the member's preferences, defensively typed.

    The JSON column hands back ``{}`` when a value fails to decode, so a list
    column can legitimately return a dict. Anything that is not a list of
    strings is treated as empty rather than allowed to propagate.
    """
    prefs = getattr(user, 'preferences', None)
    raw = getattr(prefs, attribute, None)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, (str, int)) and str(item).strip()]


def _stored_pins(user) -> list[str]:
    return _stored_list(user, 'discover_pins')


def _preferences(user) -> UserPreference:
    """The member's preference row, created on first write."""
    prefs = getattr(user, 'preferences', None)
    if prefs is None:
        prefs = UserPreference(user_id=user.id)
        db.session.add(prefs)
        user.preferences = prefs
    return prefs


def _deduped(identifiers) -> list[str]:
    """Trimmed, de-duplicated, order preserved."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in identifiers or []:
        identifier = str(item).strip()
        if identifier and identifier not in seen:
            seen.add(identifier)
            ordered.append(identifier)
    return ordered


def member_pins(user, *, available: Iterable[str] | None = None) -> list[str]:
    """Row identifiers this member pinned, in their order.

    ``available`` is the set of rows the feed actually has. Pins outside it are
    dropped rather than reported — see the module note on forgiving reads.
    """
    pins = _stored_pins(user)
    if available is not None:
        allowed = set(available)
        pins = [identifier for identifier in pins if identifier in allowed]

    # De-duplicate while preserving the member's order; a repeated pin is one
    # pin, not two slots.
    seen: set[str] = set()
    ordered: list[str] = []
    for identifier in pins:
        if identifier not in seen:
            seen.add(identifier)
            ordered.append(identifier)
    return ordered[:MAX_MEMBER_PINS]


def set_member_pins(user, identifiers, *, available: Iterable[str]) -> list[str]:
    """Replace a member's pins. Returns what was actually stored.

    Unknown identifiers are rejected here rather than silently dropped: on the
    way *in* a bad identifier is a client bug worth surfacing, whereas on the
    way out it is just a row that has since gone away.
    """
    allowed = set(available)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in identifiers or []:
        identifier = str(item).strip()
        if not identifier or identifier in seen:
            continue
        if identifier not in allowed:
            raise ValueError(identifier)
        seen.add(identifier)
        cleaned.append(identifier)
        if len(cleaned) >= MAX_MEMBER_PINS:
            break

    _preferences(user).discover_pins = cleaned
    db.session.commit()
    return cleaned


def hidden_rows(user, *, available: Iterable[str] | None = None) -> list[str]:
    """Row identifiers this member excluded from their own feed.

    Read exactly as forgivingly as pins are: a hidden row that no longer exists
    is dropped rather than raised, so a member who hid a genre row keeps a valid
    preference after that row stops being generated for them.
    """
    hidden = _deduped(_stored_list(user, 'discover_hidden'))
    if available is not None:
        allowed = set(available)
        hidden = [identifier for identifier in hidden if identifier in allowed]
    return hidden


def set_hidden_rows(user, identifiers, *, available: Iterable[str]) -> list[str]:
    """Replace a member's hidden rows. Returns what was actually stored.

    Uncapped, unlike pins: pins are capped because the feed reserves a fixed
    number of slots for them, and there is no equivalent budget on the other
    side — a member is allowed to hide every row on their feed if that is what
    they want, and the restore control makes that reversible.

    An admin-forced shelf cannot be hidden. That is the one row an operator is
    promised a dependable position for — a maintenance notice or an outage
    banner — and a feed where it can be dismissed permanently is not a feed you
    can announce anything on. Everything else is the member's to arrange.
    """
    allowed = set(available)
    forced = set(admin_forced())
    cleaned: list[str] = []
    for identifier in _deduped(identifiers):
        if identifier not in allowed:
            raise ValueError(identifier)
        if identifier in forced:
            raise PinnedByAdmin(identifier)
        cleaned.append(identifier)

    _preferences(user).discover_hidden = cleaned
    db.session.commit()
    return cleaned


def admin_forced() -> list[str]:
    """Shelf identifiers an admin forced to the top, lowest rank first."""
    rows = db.session.execute(
        select(DiscoverySection.identifier)
        .where(DiscoverySection.pin_rank.isnot(None))
        .order_by(DiscoverySection.pin_rank, DiscoverySection.display_order)
    ).all()
    return [row[0] for row in rows][:MAX_ADMIN_FORCED]
