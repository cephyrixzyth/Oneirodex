"""Framework-neutral feature toggle metadata shared by native and legacy APIs."""

# (form_name, config_key, label, help, safety_lock)
FEATURE_ENV_TOGGLES = (
    ('enable_arr_module', 'ENABLE_ARR_MODULE', 'Arr / indexer module', 'Native Torznab/Newznab + optional Prowlarr/Jackett hubs + presets', False),
    ('enable_debrid', 'ENABLE_DEBRID', 'Debrid acquire', 'Real-Debrid / AllDebrid / etc. when tokens set', False),
    ('enable_game_assists', 'ENABLE_GAME_ASSISTS', 'Game assists', 'Single-player assist packs', False),
    ('enable_vr_browse', 'ENABLE_VR_BROWSE', 'VR browse', '/vr PWA catalog', False),
    ('enable_ai_assist', 'ENABLE_AI_ASSIST', 'AI assist', 'Ollama suggestions (rename apply stays gated)', False),
    ('enable_livekit', 'ENABLE_LIVEKIT', 'LiveKit voice', 'Household voice rooms (needs LIVEKIT_* secrets)', False),
    ('enable_pcdos_browser', 'ENABLE_PCDOS_BROWSER', 'PC DOS browser play', 'Needs vendored dosbox WASM', False),
    ('enable_rom_patch_apply', 'ENABLE_ROM_PATCH_APPLY', 'ROM patch apply', 'Companion Flips apply', False),
    ('enable_patch_catalog', 'ENABLE_PATCH_CATALOG', 'Patch catalog', 'Operator YAML/JSON guides', False),
    ('enable_rom_ai_translate', 'ENABLE_ROM_AI_TRANSLATE', 'ROM AI translate hints', 'RetroArch AI Service overlay', False),
    ('enable_hardlink_helpers', 'ENABLE_HARDLINK_HELPERS', 'Hardlink helpers', 'Preview storage helpers', False),
    ('enable_malware_scan', 'ENABLE_MALWARE_SCAN', 'Malware scanner', 'ClamAV + filename heuristics', False),
    ('enable_activity_feed', 'ENABLE_ACTIVITY_FEED', 'Activity feed', 'Now playing / recent', False),
    ('enable_free_games', 'ENABLE_FREE_GAMES', 'Free games poller', 'News free-games feed', False),
    ('enable_mod_tracking', 'ENABLE_MOD_TRACKING', 'Mod tracking', 'Per-game mod notes', False),
    ('enable_ambient_lighting', 'ENABLE_AMBIENT_LIGHTING', 'Ambient lighting', 'Hyperion.ng / Home Assistant on play', False),
    ('enable_remote_play', 'ENABLE_REMOTE_PLAY', 'Remote play', 'BYO Sunshine/Wolf Moonlight host', False),
)
