"""Lightweight plugin / connector registry (Wave 10–12)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PluginInfo:
    id: str
    name: str
    category: str
    description: str
    enabled: bool = True
    status: str = 'available'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_BUILTIN: list[PluginInfo] = [
    PluginInfo('provider.igdb', 'IGDB', 'metadata', 'Primary game metadata provider'),
    PluginInfo('provider.steamgriddb', 'SteamGridDB', 'metadata', 'Cover / hero art'),
    PluginInfo('provider.hash_identify', 'Hash identify', 'metadata', 'Keyless community hash lookup for console ROMs after an IGDB + DAT miss (INSP-31)'),
    PluginInfo('arr.native', 'Native indexers', 'acquire', 'Torznab/Newznab registry + curated presets'),
    PluginInfo('arr.prowlarr', 'Prowlarr', 'acquire', 'Optional BYO indexer manager hub'),
    PluginInfo('arr.jackett', 'Jackett', 'acquire', 'Optional BYO indexer proxy hub'),
    PluginInfo('client.qbittorrent', 'qBittorrent', 'download', 'Primary torrent client'),
    PluginInfo('client.transmission', 'Transmission', 'download', 'Optional torrent client'),
    PluginInfo('client.deluge', 'Deluge', 'download', 'Optional torrent client'),
    PluginInfo('client.sabnzbd', 'SABnzbd', 'download', 'Optional Usenet client'),
    PluginInfo('client.nzbget', 'NZBGet', 'download', 'Optional Usenet client (RetroArr-class)'),
    PluginInfo('debrid.real_debrid', 'Real-Debrid', 'debrid', 'Magnet → cached HTTP'),
    PluginInfo('debrid.alldebrid', 'AllDebrid', 'debrid', 'Magnet → cached HTTP'),
    PluginInfo('debrid.premiumize', 'Premiumize', 'debrid', 'Optional third debrid'),
    PluginInfo('debrid.torbox', 'TorBox', 'debrid', 'Optional modern debrid API'),
    PluginInfo('emu.webretro', 'WebRetro', 'emulator', 'Browser WASM cores + cloud save bridge'),
    PluginInfo('emu.emulatorjs', 'EmulatorJS', 'emulator', 'Browser engine B — own shell + cores, operator-fetched (BP-2)'),
    PluginInfo('emu.retroarch', 'RetroArch', 'emulator', 'Native companion profiles'),
    PluginInfo('compat.anticheat', 'Anti-cheat reports', 'metadata', 'Community anti-cheat compatibility list, read-only; one keyless fetch a day (INSP-35)'),
    PluginInfo('compat.save_paths', 'Save locations', 'metadata', 'Community save-location manifest, read-only; one keyless fetch a day (INSP-1)'),
    PluginInfo('achievements.retroachievements', 'RetroAchievements', 'emulator', 'Community achievement sets matched by ROM hash; member progress read-only (R1/R2)'),
    PluginInfo('store.xbox', 'Xbox ownership', 'ownership', 'Register-only, opt-in, unofficial (xbox-webapi); CSV always (INSP-42)'),
    PluginInfo('store.psn', 'PlayStation ownership', 'ownership', 'Register-only, opt-in, unofficial (psnawp); CSV always (INSP-42)'),
    PluginInfo('export.esde', 'ES-DE export', 'export', 'gamelist.xml packs'),
    PluginInfo('export.pegasus', 'Pegasus export', 'export', 'metadata.pegasus.txt'),
    PluginInfo('assist.packs', 'Assist packs', 'assists', 'Single-player companion toggles'),
    PluginInfo('mods.tracking', 'Mod tracking', 'mods', 'Per-game community mod lists'),
    PluginInfo('mods.catalog.thunderstore', 'Thunderstore catalogue', 'mods', 'Browse BepInEx / MelonLoader communities, read-only, no key (INSP-22)'),
    PluginInfo('mods.catalog.modrinth', 'Modrinth catalogue', 'mods', 'Browse Minecraft mods, read-only, no key (INSP-22)'),
    PluginInfo('mods.catalog.gamebanana', 'GameBanana catalogue', 'mods', 'Browse long-tail UGC, read-only, no key, rate-limited (INSP-22)'),
    PluginInfo('mods.catalog.nexus', 'Nexus Mods catalogue', 'mods', 'Browse trending + latest behind NEXUS_API_KEY; never a download (INSP-22)'),
    PluginInfo('social.community_chat', 'Community chat link', 'social', 'BYO Stoat/Matrix deep-link'),
    PluginInfo('notify.apprise', 'Apprise API push', 'notify', 'BYO Apprise API server: admin alerts, opt-in social kinds (INSP-6)'),
    PluginInfo('notify.ntfy', 'ntfy push', 'notify', 'BYO ntfy topic: admin alerts, opt-in social kinds (INSP-6)'),
    PluginInfo('rtc.livekit', 'LiveKit voice', 'rtc', 'Optional household voice SFU (Wave 16)'),
    PluginInfo('remote_play.moonlight', 'Remote play', 'streaming', 'BYO Sunshine/Wolf Moonlight host'),
]


def _runtime_status_map() -> dict[str, str]:
    """Map plugin id → configured | available | disabled from live connectors."""
    status: dict[str, str] = {}
    try:
        from oneirodex.utils.arr_connectors import connector_status
        for row in connector_status():
            cid = row.get('id')
            configured = bool(row.get('configured'))
            if cid == 'native_indexers':
                status['arr.native'] = 'configured' if configured else 'available'
            elif cid == 'prowlarr':
                status['arr.prowlarr'] = 'configured' if configured else 'available'
            elif cid == 'jackett':
                status['arr.jackett'] = 'configured' if configured else 'available'
            elif cid == 'qbittorrent':
                status['client.qbittorrent'] = 'configured' if configured else 'available'
            elif cid == 'transmission':
                status['client.transmission'] = 'configured' if configured else 'available'
            elif cid == 'deluge':
                status['client.deluge'] = 'configured' if configured else 'available'
            elif cid == 'sabnzbd':
                status['client.sabnzbd'] = 'configured' if configured else 'available'
            elif cid == 'nzbget':
                status['client.nzbget'] = 'configured' if configured else 'available'
    except Exception:
        pass
    try:
        from oneirodex.utils.debrid_connectors import debrid_status
        for row in debrid_status():
            pid = row.get('id') or row.get('provider')
            configured = bool(row.get('configured'))
            if not pid:
                continue
            key = f'debrid.{pid}' if not str(pid).startswith('debrid.') else str(pid)
            status[key] = 'configured' if configured else 'available'
    except Exception:
        pass
    try:
        from oneirodex import db
        from oneirodex.models import GlobalSettings
        from sqlalchemy import select
        row = db.session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        if row and getattr(row, 'community_chat_url', None):
            status['social.community_chat'] = 'configured'
        else:
            status['social.community_chat'] = 'available'
    except Exception:
        status['social.community_chat'] = 'available'
    try:
        from oneirodex.utils.hash_identify import is_enabled as _hash_identify_enabled

        status['provider.hash_identify'] = 'configured' if _hash_identify_enabled() else 'disabled'
    except Exception:
        status['provider.hash_identify'] = 'available'
    try:
        from oneirodex.utils.livekit_rtc import livekit_config, livekit_enabled
        cfg = livekit_config()
        if livekit_enabled() and cfg['url'] and cfg['api_key'] and cfg['api_secret']:
            status['rtc.livekit'] = 'configured'
        elif livekit_enabled():
            status['rtc.livekit'] = 'available'
        else:
            status['rtc.livekit'] = 'disabled'
    except Exception:
        status['rtc.livekit'] = 'available'
    try:
        from oneirodex.utils.remote_play import get_remote_play_config, remote_play_enabled
        if remote_play_enabled() and get_remote_play_config().get('configured'):
            status['remote_play.moonlight'] = 'configured'
        elif remote_play_enabled():
            status['remote_play.moonlight'] = 'available'
        else:
            status['remote_play.moonlight'] = 'disabled'
    except Exception:
        status['remote_play.moonlight'] = 'available'
    try:
        from oneirodex.utils.emulatorjs import emulatorjs_installed

        status['emu.emulatorjs'] = 'installed' if emulatorjs_installed() else 'available'
    except Exception:
        status['emu.emulatorjs'] = 'available'
    try:
        from oneirodex.utils.notification_bus import apprise_urls, ntfy_url

        status['notify.apprise'] = 'configured' if apprise_urls() else 'available'
        status['notify.ntfy'] = 'configured' if ntfy_url() else 'available'
        from oneirodex.utils.store_ownership_common import unofficial_store_opt_in
        from oneirodex.utils.store_ownership_psn import client_available as psn_client
        from oneirodex.utils.store_ownership_xbox import client_available as xbox_client

        opted = unofficial_store_opt_in()
        for sid, has_client in (('xbox', xbox_client()), ('psn', psn_client())):
            if sid not in opted:
                status[f'store.{sid}'] = 'disabled'
            else:
                status[f'store.{sid}'] = 'configured' if has_client else 'available'
    except Exception:
        pass
    try:
        from oneirodex.utils.save_paths import status_summary as save_paths_status

        sp = save_paths_status()
        status['compat.save_paths'] = 'disabled' if not sp['enabled'] else ('configured' if sp['configured'] else 'available')
    except Exception:
        status['compat.save_paths'] = 'available'
    try:
        from oneirodex.utils.retroachievements import configured as ra_configured

        status['achievements.retroachievements'] = 'configured' if ra_configured() else 'available'
    except Exception:
        status['achievements.retroachievements'] = 'available'
    try:
        from oneirodex.utils.mod_catalog import catalog_enabled, source_configured, source_ids

        for sid in source_ids():
            if not catalog_enabled():
                status[f'mods.catalog.{sid}'] = 'disabled'
            else:
                status[f'mods.catalog.{sid}'] = 'configured' if source_configured(sid) else 'available'
    except Exception:
        pass
    try:
        from oneirodex.utils.anticheat_compat import status_summary as anticheat_status

        ac = anticheat_status()
        status['compat.anticheat'] = 'disabled' if not ac['enabled'] else ('configured' if ac['configured'] else 'available')
    except Exception:
        status['compat.anticheat'] = 'available'
    return status


def list_plugins(*, category: str | None = None) -> list[dict[str, Any]]:
    runtime = _runtime_status_map()
    rows = _BUILTIN
    if category:
        rows = [p for p in rows if p.category == category]
    out = []
    for plugin in rows:
        payload = plugin.to_dict()
        if plugin.id in runtime:
            payload['status'] = runtime[plugin.id]
        out.append(payload)
    return out


def get_plugin(plugin_id: str) -> dict[str, Any] | None:
    for plugin in _BUILTIN:
        if plugin.id == plugin_id:
            payload = plugin.to_dict()
            runtime = _runtime_status_map()
            if plugin_id in runtime:
                payload['status'] = runtime[plugin_id]
            return payload
    return None
