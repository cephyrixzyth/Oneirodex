"""Admin Integrations hub inventory — all configured APIs / providers.

Used by ``GET /api/admin/integrations/inventory`` so the admin UI can list
every integration with status + deep links (not IGDB-only).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select


def _settings_row():
    from oneirodex import db
    from oneirodex.models import GlobalSettings

    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()


def _status(*, configured: bool, enabled: bool | None = None) -> str:
    if enabled is False:
        return 'disabled'
    if configured:
        return 'configured'
    return 'available'


def build_integrations_inventory() -> list[dict[str, Any]]:
    """Return inventory rows for Admin Integrations honesty."""
    settings = _settings_row()
    rows: list[dict[str, Any]] = []

    def add(
        *,
        id: str,
        name: str,
        category: str,
        admin_href: str,
        configured: bool,
        enabled: bool | None = None,
        notes: str = '',
        settings_href: str | None = None,
    ) -> None:
        rows.append({
            'id': id,
            'name': name,
            'category': category,
            'status': _status(configured=configured, enabled=enabled),
            'configured': bool(configured),
            'enabled': enabled,
            'admin_href': admin_href,
            'settings_href': settings_href or admin_href,
            'notes': notes,
        })

    # --- Metadata / artwork ---
    igdb_ok = bool(
        settings
        and getattr(settings, 'igdb_client_id', None)
        and getattr(settings, 'igdb_client_secret', None)
    )
    add(
        id='igdb',
        name='IGDB',
        category='metadata',
        admin_href='/admin/integrations#igdb',
        settings_href='/admin/igdb_settings',
        configured=igdb_ok,
        notes='Primary game metadata',
    )

    # --- Cascade sources (GT-B26) ---
    #
    # metadata_cascade already walks eight sources — Steam, GOG, Epic, itch.io,
    # Giant Bomb, MobyGames, RAWG and TheGamesDB — but only four of them were
    # listed here. So the Integrations page said Oneirodex scraped IGDB and
    # three databases while it was in fact querying five more, and an operator
    # had no way to see or reason about them.
    #
    # These are keyless public endpoints: there is no credential to configure,
    # so `configured=True` states "usable right now", not "you set this up".
    # Reporting them as unconfigured would read as broken.
    add(
        id='steam',
        name='Steam',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=True,
        notes='PC storefront metadata — normalised into the IGDB field shape',
    )
    add(
        id='gog',
        name='GOG',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=True,
        notes='PC storefront search — DRM-free catalogue',
    )
    add(
        id='epic',
        name='Epic Games Store',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=True,
        notes='PC storefront search',
    )
    add(
        id='itch',
        name='itch.io',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=True,
        notes='Indie storefront search',
    )
    add(
        id='rawg',
        name='RAWG',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=True,
        notes='Catalogue database backstop for PC and console',
    )

    sgdb_key = ''
    try:
        from oneirodex.utils.providers import get_steamgriddb_api_key

        sgdb_key = get_steamgriddb_api_key() or ''
    except Exception:
        sgdb_key = ''
    add(
        id='steamgriddb',
        name='SteamGridDB',
        category='artwork',
        admin_href='/admin/integrations#steamgriddb',
        configured=bool(sgdb_key),
        notes='Cover / hero art',
    )

    gb_key = bool(settings and getattr(settings, 'giantbomb_api_key', None))
    try:
        from oneirodex.utils.providers.mobygames import get_mobygames_api_key

        moby_key = bool(get_mobygames_api_key())
    except Exception:
        moby_key = bool(settings and getattr(settings, 'mobygames_api_key', None))
    try:
        from oneirodex.utils.providers.thegamesdb import get_thegamesdb_api_key

        tgdb_key = bool(get_thegamesdb_api_key())
    except Exception:
        tgdb_key = bool(settings and getattr(settings, 'thegamesdb_api_key', None))
    try:
        from oneirodex.utils.retroachievements import configured as ra_configured

        ra_ok = ra_configured()
    except Exception:
        ra_ok = False
    add(
        id='retroachievements',
        name='RetroAchievements',
        category='emulation',
        admin_href='/admin/integrations#retro-achievements-settings',
        configured=ra_ok,
        notes='Configure the household account in Integrations; match systems under Emulators. Member progress is read-only.',
    )
    try:
        from oneirodex.utils.hash_identify import base_url as _hash_base, is_enabled as _hash_on

        hash_on = bool(_hash_on())
        hash_host = _hash_base()
    except Exception:
        hash_on, hash_host = False, ''
    add(
        id='hash_identify',
        name='Hash identify',
        category='metadata',
        admin_href='/admin/integrations#metadata-providers',
        configured=hash_on,
        enabled=hash_on,
        notes=f'Keyless community hash lookup ({hash_host or "unset"}) for console ROMs after an IGDB and local-DAT miss -- identity only, never a download (ENABLE_HASH_IDENTIFY, HASH_IDENTIFY_BASE_URL)',
    )
    add(
        id='giantbomb',
        name='Giant Bomb',
        category='metadata',
        admin_href='/admin/integrations#giantbomb',
        configured=gb_key,
        notes='Secondary metadata / wiki',
    )
    add(
        id='mobygames',
        name='MobyGames',
        category='metadata',
        admin_href='/admin/integrations#mobygames',
        configured=moby_key,
        notes='Optional Class D identify search (MOBYGAMES_API_KEY)',
    )
    add(
        id='thegamesdb',
        name='TheGamesDB',
        category='metadata',
        admin_href='/admin/integrations#thegamesdb',
        configured=tgdb_key,
        notes='Optional Class D identify / covers (THEGAMESDB_API_KEY)',
    )

    # INSP-22 -- read-only mod registries. Keyless, so `configured` reads
    # "usable right now" (the flag is on), like the cascade sources above.
    try:
        from oneirodex.utils.mod_catalog import SOURCE_LABELS, SOURCE_NOTES, catalog_enabled, source_configured

        catalog_on = catalog_enabled()
        for sid, label in SOURCE_LABELS.items():
            add(
                id=f'mod_catalog_{sid}',
                name=f'{label} (mods)',
                category='mods',
                admin_href='/admin/integrations#mods',
                configured=catalog_on and source_configured(sid),
                enabled=catalog_on,
                notes=f'{SOURCE_NOTES[sid]} Browse + deep link only; the companion stages the URL the librarian chose (ENABLE_MOD_CATALOG).',
            )
    except Exception:  # noqa: BLE001
        pass
    add(
        id='mod_catalog_curseforge',
        name='CurseForge (mods)',
        category='mods',
        admin_href='/admin/integrations#mods',
        configured=False,
        enabled=False,
        notes='Declined: its API terms forbid third-party download automation and require a key per app; Modrinth covers the same games without either.',
    )

    # INSP-35 -- keyless community list, read-only. `configured` means the
    # daily fetch has landed at least once, so lookups can answer.
    try:
        from oneirodex.utils.anticheat_compat import status_summary as _anticheat_status

        ac = _anticheat_status()
    except Exception:  # noqa: BLE001
        ac = {'enabled': False, 'configured': False, 'count': 0}
    add(
        id='anticheat_compat',
        name='Anti-cheat reports',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=bool(ac.get('configured')),
        enabled=bool(ac.get('enabled')),
        notes=(
            f"Community anti-cheat compatibility, {ac.get('count', 0)} titles cached; one keyless fetch a day, reports not guarantees (ENABLE_ANTICHEAT_COMPAT)"
            if ac.get('configured')
            else 'Community anti-cheat compatibility; the daily fetch has not landed yet (ENABLE_ANTICHEAT_COMPAT)'
        ),
    )

    hltb_on = bool(settings and getattr(settings, 'enable_hltb_integration', True))
    add(
        id='hltb',
        name='HowLongToBeat',
        category='metadata',
        admin_href='/admin/integrations#hltb',
        settings_href='/admin/new_server_settings',
        configured=hltb_on,
        enabled=hltb_on,
        notes='Playtime estimates (no API key)',
    )

    try:
        from oneirodex.utils.providers.meta_quest import get_meta_quest_api_mode

        mq_mode = get_meta_quest_api_mode()
    except Exception:
        mq_mode = 'csv_only'
    add(
        id='meta_quest',
        name='Meta / Quest',
        category='ownership',
        admin_href='/admin/integrations#meta_quest',
        configured=mq_mode != 'off',
        notes=f'Ownership register — mode={mq_mode}',
    )

    # INSP-6 -- BYO notification bus. Configured = an endpoint is named.
    try:
        from oneirodex.utils.notification_bus import status_summary as _bus_status

        bus = _bus_status()
    except Exception:  # noqa: BLE001
        bus = {'configured': False, 'apprise': 0, 'ntfy': False, 'social_to_bus': False}
    add(
        id='notify_bus',
        name='Notification bus (Apprise API / ntfy)',
        category='notify',
        admin_href='/admin/integrations#notify',
        configured=bool(bus.get('configured')),
        enabled=bool(bus.get('configured')),
        notes=(
            f"{bus.get('apprise', 0)} Apprise endpoint(s), ntfy {'on' if bus.get('ntfy') else 'off'}; admin alerts ride the admin_notify_* flags, social kinds {'also pushed (NOTIFY_SOCIAL_TO_BUS)' if bus.get('social_to_bus') else 'in-app only'}. Test: POST /api/admin/notify-bus/test"
            if bus.get('configured')
            else 'Nothing bundled: name an Apprise API notify URL (NOTIFY_APPRISE_URLS) and/or an ntfy topic (NOTIFY_NTFY_URL) to push admin alerts to a phone'
        ),
    )

    # INSP-42 -- unofficial, opt-in, register-only stores (G5: default off).
    try:
        from oneirodex.utils.store_ownership_common import unofficial_store_opt_in
        from oneirodex.utils.store_ownership_psn import client_available as _psn_client
        from oneirodex.utils.store_ownership_xbox import client_available as _xbox_client

        _opted = unofficial_store_opt_in()
        for sid, label, pkg, has_client in (
            ('xbox', 'Xbox', 'xbox-webapi', _xbox_client()),
            ('psn', 'PlayStation Network', 'psnawp', _psn_client()),
        ):
            on = sid in _opted
            add(
                id=f'store_{sid}',
                name=label,
                category='ownership',
                admin_href='/admin/integrations#ownership',
                configured=on and has_client,
                enabled=on,
                notes=(
                    f'Ownership register, live via the unofficial {pkg} client (installed: {"yes" if has_client else "no"}); IDs + names only, never a download'
                    if on
                    else f'Ownership register, CSV snapshot only. Live sync is opt-in: ENABLE_UNOFFICIAL_STORE_SYNC={sid} plus the optional {pkg} package'
                ),
            )
    except Exception:  # noqa: BLE001
        pass
    # INSP-1 -- community save-location manifest, read-only. `configured` means
    # the daily fetch built the index at least once.
    try:
        from oneirodex.utils.save_paths import status_summary as _sp_status

        sp = _sp_status()
    except Exception:  # noqa: BLE001
        sp = {'enabled': False, 'configured': False, 'count': 0}
    add(
        id='save_paths',
        name='Save locations',
        category='metadata',
        admin_href='/admin/integrations#metadata',
        configured=bool(sp.get('configured')),
        enabled=bool(sp.get('enabled')),
        notes=(
            f"Community save-location manifest, {sp.get('count', 0)} titles indexed; one keyless fetch a day, paths only -- nothing synced (ENABLE_SAVE_PATHS)"
            if sp.get('configured')
            else 'Community save-location manifest; the daily fetch has not landed yet (ENABLE_SAVE_PATHS)'
        ),
    )

    # --- Auth / mail / support ---
    smtp_ok = bool(settings and getattr(settings, 'smtp_server', None))
    add(
        id='smtp',
        name='SMTP Email',
        category='email',
        admin_href='/admin/integrations#email',
        settings_href='/admin/smtp_settings',
        configured=smtp_ok,
        notes='Invites, resets, digests',
    )

    oidc_env = os.environ.get('OIDC_ENABLED', '').lower() in ('1', 'true', 'yes')
    oidc_db = bool(settings and getattr(settings, 'oidc_enabled', False))
    oidc_cfg = bool(
        settings
        and getattr(settings, 'oidc_issuer_url', None)
        and getattr(settings, 'oidc_client_id', None)
    )
    add(
        id='oidc',
        name='OIDC / SSO',
        category='auth',
        admin_href='/admin/integrations#oidc',
        configured=oidc_cfg and (oidc_env or oidc_db),
        enabled=oidc_env and oidc_db,
        notes='Opt-in; needs OIDC_ENABLED env + Integrations toggle',
    )

    add(
        id='support',
        name='Support inbox',
        category='support',
        admin_href='/admin/support',
        configured=True,
        notes='In-app Report → admin inbox + GitHub Issues',
    )

    # --- Social / RTC ---
    chat_url = bool(settings and getattr(settings, 'community_chat_url', None))
    add(
        id='community_chat',
        name='Community chat link',
        category='social',
        admin_href='/admin/integrations#community',
        configured=chat_url,
        notes='BYO Stoat/Matrix deep-link',
    )

    try:
        from oneirodex.utils.livekit_rtc import livekit_config, livekit_enabled

        lk_cfg = livekit_config()
        lk_on = livekit_enabled()
        lk_ready = bool(lk_on and lk_cfg.get('url') and lk_cfg.get('api_key') and lk_cfg.get('api_secret'))
    except Exception:
        lk_on = False
        lk_ready = False
    add(
        id='livekit',
        name='LiveKit voice',
        category='rtc',
        admin_href='/admin/features',
        settings_href='/admin/ops',
        configured=lk_ready,
        enabled=lk_on,
        notes='Household voice SFU — ENABLE_LIVEKIT + LIVEKIT_* secrets',
    )

    # --- Acquire (admin-facing indexers / hubs) ---
    try:
        from oneirodex.utils.arr_connectors import connector_status

        for row in connector_status():
            cid = row.get('id') or 'arr'
            configured = bool(row.get('configured'))
            add(
                id=f"arr_{cid}",
                name=str(row.get('name') or cid),
                category='acquire',
                admin_href='/admin/arr',
                configured=configured,
                notes=str(row.get('note') or row.get('kind') or 'Acquire connector'),
            )
    except Exception:
        add(
            id='arr_module',
            name='Arr / indexers',
            category='acquire',
            admin_href='/admin/arr',
            configured=False,
            notes='Native Torznab + optional Prowlarr/Jackett/qBit',
        )

    # Ownership stores (register-only)
    add(
        id='ownership_steam',
        name='Steam ownership',
        category='ownership',
        admin_href='/admin/integrations#ownership',
        configured=True,
        notes='Register-only — no DRM download queues',
    )

    return rows
