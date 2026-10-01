"""Scoped factory reset for the admin surface.

What this does and, more importantly, does not do
-------------------------------------------------
This empties Oneirodex's *database* — the catalog it built, the accounts it
holds, the settings it was given. It never touches a single file on disk.

That distinction is the whole point. A game library is years of collecting; the
rows describing it are a cache that a scan can rebuild in an afternoon. So the
reset deliberately has no filesystem access at all: no ``os.remove``, no
``shutil.rmtree``, nothing that takes a path. Scanned media, artwork the
operator supplied, firmware on the BIOS volume and the theme tree all survive by
construction rather than by remembering to exclude them. If a future change
needs to delete a file, it does not belong in this module.

Scopes
------
Four, chosen so an operator can clear the thing that is actually wrong instead
of starting over:

``catalog``
    Games, matches, unmatched folders, scan jobs, artwork records, reference
    sets. The output of scanning. Library *definitions* survive, so the next
    scan starts immediately.
``libraries``
    The library rows themselves, plus the filters and access grants that hang
    off them. Implies ``catalog`` — a library row cannot go while its games
    remain pointing at it.
``users``
    Members and everything personal: favorites, collections, playtime, chat,
    invites, notifications, saves. The acting admin is recreated afterwards, so
    the operator is never locked out of the install they just reset.
``settings``
    Server settings, integration credentials, themes, discovery sections,
    announcements. Returns the install to first-boot configuration.

Ordering and integrity
----------------------
Tables are emptied with a single ``TRUNCATE ... RESTART IDENTITY CASCADE``.
One statement, so it is one transaction: either the whole reset lands or none of
it does, and there is no half-cleared database to explain. ``CASCADE`` lets
Postgres resolve foreign keys rather than this module hard-coding a dependency
order that would rot the first time a model gains a relationship.

Because ``CASCADE`` can reach past the tables named, :func:`plan_reset` reports
the full closure it will empty, and the route shows that list before the
operator confirms. A reset that quietly cleared more than it listed would be
exactly the kind of surprise this module exists to avoid.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import text

from oneirodex import db

__all__ = [
    'RESET_SCOPES',
    'SCOPE_IMPLIES',
    'expand_scopes',
    'plan_reset',
    'perform_reset',
]


# Every table, assigned to exactly one scope.
#
# `test_system_reset.py` asserts this covers the full model metadata: a new
# table has to be placed here or the suite fails. That is deliberate — the
# failure mode for a reset feature is silently leaving rows behind after the
# schema grows, and a stale hand-written list is how that happens.
RESET_SCOPES: dict[str, tuple[str, ...]] = {
    'catalog': (
        'games',
        'game_developer_association',
        'game_game_mode_association',
        'game_genre_association',
        'game_multiplayer_mode_association',
        'game_platform_association',
        'game_player_perspective_association',
        'game_theme_association',
        'game_extras',
        'game_updates',
        'game_urls',
        'game_vr_profiles',
        'game_related_media',
        'game_similarity',
        'game_servers',
        'game_requests',
        'images',
        'unmatched_folders',
        'scan_jobs',
        'duplicate_fix_logs',
        'pc_cheats',
        'developers',
        'publishers',
        'genres',
        'platforms',
        'game_modes',
        'multiplayer_modes',
        'player_perspectives',
        'reference_sets',
        'reference_set_entries',
        # Cached IGDB release_dates per platform + region, behind the Systems
        # "Licensed catalog" counts. Catalog scope: it is derived from IGDB and
        # rebuilt on demand, and leaving it behind meant a wiped catalog still
        # reported release counts for titles that were gone.
        'igdb_platform_releases',
        # Cached RetroAchievements (console, hash) -> set index. Catalog scope
        # for the same reason as the IGDB releases above: it is provider-derived
        # and refetched on demand, and a wiped catalog that kept it would go on
        # claiming achievement sets for games that are gone.
        'retroachievements_index',
        'free_game_offers',
        'download_requests',
        'system_events',
    ),
    'libraries': (
        'libraries',
        'filters',
        'user_library_access',
        'allowed_file_types',
        'ignored_file_types',
    ),
    'users': (
        'users',
        'user_preferences',
        'user_favorites',
        'user_friendships',
        'user_game_progress',
        'user_game_status',
        'user_notifications',
        'user_owned_titles',
        # A member's match history for those titles; cascades with the title.
        'ownership_match_decisions',
        'user_taste_facets',
        'user_content_filters',
        'user_attract_mode_settings',
        'user_discover_impressions',
        # A saved filter is a member's own question about the library, keyed to
        # their user row. It survives a catalog wipe on purpose -- the filter is
        # a query, not a reference to particular games -- but it dies with the
        # member, which the FK cascade already does and this states out loud.
        'saved_filters',
        'game_collections',
        'game_collection_items',
        'play_sessions',
        'emulator_saves',
        'store_accounts',
        # Per-member store sync runs (LIB-04); meaningless without the account.
        'store_sync_jobs',
        'api_tokens',
        'client_devices',
        'invite_tokens',
        'support_tickets',
        'whitelist',
        'chat_channels',
        'chat_channel_members',
        'chat_messages',
        'chat_message_attachments',
        'chat_message_reactions',
        'chat_spaces',
        'chat_space_members',
        'chat_space_invites',
        'custom_emoji',
    ),
    'settings': (
        'global_settings',
        'themes',
        'discovery_sections',
        'announcements',
        'newsletters',
        'detail_layout_presets',
    ),
}

# Clearing library rows while their games still reference them would leave the
# catalog pointing at nothing, so asking for one implies the other. Expressed as
# data rather than as a note in the docs, because the route has to enforce it.
SCOPE_IMPLIES: dict[str, tuple[str, ...]] = {
    'libraries': ('catalog',),
}


def expand_scopes(scopes: Iterable[str]) -> list[str]:
    """Add implied scopes and drop anything unrecognised.

    Unknown names are ignored rather than raising: the caller validates user
    input and reports it properly, and this function is also used to describe a
    plan, where being strict would turn a typo into a 500.
    """
    resolved: set[str] = set()
    for scope in scopes or ():
        if scope not in RESET_SCOPES:
            continue
        resolved.add(scope)
        resolved.update(SCOPE_IMPLIES.get(scope, ()))
    # Stable order so the plan reads the same way twice.
    return [name for name in RESET_SCOPES if name in resolved]


def _cascade_closure(tables: Iterable[str]) -> list[str]:
    """Every table TRUNCATE CASCADE would also empty, as Postgres sees it.

    Postgres cascades a truncate to anything holding a foreign key into the
    named tables, transitively. Reporting only what was asked for would
    understate the blast radius, so the plan walks the model metadata the same
    way and reports the closure.
    """
    named = set(tables)
    # `db.metadata` is only populated once the model module has been imported.
    # Without this the closure silently comes back as "just what you asked for",
    # which would have the UI understate the blast radius — the one thing this
    # function exists to prevent.
    import oneirodex.models  # noqa: F401

    metadata = db.metadata

    # Reverse dependency edges: child -> the parents it references.
    changed = True
    while changed:
        changed = False
        for table in metadata.sorted_tables:
            if table.name in named:
                continue
            for fk in table.foreign_keys:
                if fk.column.table.name in named:
                    named.add(table.name)
                    changed = True
                    break

    return sorted(named)


def plan_reset(scopes: Iterable[str]) -> dict[str, Any]:
    """Describe what a reset would empty, without touching anything.

    The route calls this to show the operator the real list before they confirm,
    including tables reached only by cascade.
    """
    resolved = expand_scopes(scopes)
    requested: list[str] = []
    for scope in resolved:
        requested.extend(RESET_SCOPES[scope])

    closure = _cascade_closure(requested)
    return {
        'scopes': resolved,
        'tables': sorted(set(requested)),
        # Named separately so the UI can say "and these too, by cascade".
        'cascaded': sorted(set(closure) - set(requested)),
        'table_count': len(closure),
        # Stated in the payload as well as the docs: the UI shows this to the
        # operator, and it is the reassurance that actually matters to them.
        'touches_files': False,
    }


def _snapshot_actor(user_id: int) -> dict[str, Any] | None:
    """Columns needed to put the acting admin back after a users reset."""
    row = db.session.execute(
        text('SELECT * FROM users WHERE id = :uid'), {'uid': user_id}
    ).mappings().first()
    return dict(row) if row else None


def _restore_actor(actor: dict[str, Any]) -> None:
    """Re-insert the acting admin so the operator is not locked out.

    Reinstated verbatim — same id, name, password hash and role — so the session
    cookie they are holding still resolves and they stay signed in through the
    reset. Rebuilding them as a fresh account would log them out of an install
    that now has no other way in.
    """
    columns = list(actor)
    placeholders = ', '.join(f':{name}' for name in columns)
    column_list = ', '.join(f'"{name}"' for name in columns)
    db.session.execute(
        text(f'INSERT INTO users ({column_list}) VALUES ({placeholders})'), actor
    )
    # The sequence was restarted by TRUNCATE; move it past the restored row or
    # the next signup collides with the admin's id.
    db.session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('users', 'id'), "
            "GREATEST((SELECT MAX(id) FROM users), 1))"
        )
    )


def perform_reset(scopes: Iterable[str], *, actor_user_id: int | None = None) -> dict[str, Any]:
    """Empty the selected scopes. Returns the plan that was carried out.

    Never touches the filesystem — see the module docstring.
    """
    plan = plan_reset(scopes)
    if not plan['tables']:
        return {**plan, 'performed': False, 'actor_restored': False}

    actor = None
    if 'users' in plan['scopes'] and actor_user_id is not None:
        actor = _snapshot_actor(actor_user_id)

    quoted = ', '.join(f'"{name}"' for name in plan['tables'])
    try:
        # One statement, one transaction: no partially-cleared database to
        # explain if something fails halfway.
        db.session.execute(text(f'TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE'))
        if actor:
            _restore_actor(actor)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        **plan,
        'performed': True,
        'actor_restored': bool(actor),
    }
