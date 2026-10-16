/** Types shared by GameDetailsPage and the sections extracted from it (H-D.2). */

/** A nested payload object the page only ever reads field-by-field. */
export type DetailsRecord = Record<string, unknown>

export interface TranslationPatch {
  uuid: string
  label: string
  patch_format?: string | null
  target_language?: string | null
  source_url?: string | null
}

/**
 * The `/api/games/<uuid>/details` payload as the page actually reads it.
 *
 * Built from every `game.<field>` the page and its sections touch, typed to
 * the shape the server writes (`build_game_details_payload`). Fields the
 * server may omit are optional; the index signature keeps the payload's long
 * tail reachable without widening every access to `any`.
 */
export type AnticheatStatus = 'supported' | 'running' | 'planned' | 'broken' | 'denied' | 'unknown'

export interface AnticheatReport {
  status: AnticheatStatus | string
  anticheats?: string[] | null
  reports?: number | null
  source_url?: string | null
  updated?: string | null
}

export interface DetailsGame {
  uuid: string
  name: string
  summary?: string | null
  storyline?: string | null
  developer?: string | null
  publisher?: string | null
  category?: string | null
  status_label?: string | null
  lifecycle_state?: string | null
  first_release_date?: string | null
  rating?: number | null
  rating_count?: number | null
  hltb_main_story?: number | null
  playtime?: { total_seconds?: number | null; session_count?: number | null } | null
  times_downloaded?: number | null
  size?: number | string | null
  cover_url?: string | null
  backdrop_url?: string | null
  url?: string | null
  url_igdb?: string | null
  steam_url?: string | null
  steam_app_id?: number | string | null
  play_url?: string | null
  play_blocker?: string | null
  cheat_surface?: string | null
  companion_hint?: string | null
  library_platform?: string | null
  local_version?: string | null
  remote_version_summary?: string | null
  freshness_status?: string | null
  freshness_confidence?: number | null
  rom_region?: string | null
  rom_languages?: string[] | string | null
  preferred_game_locale?: string | null
  emulator_core?: string | null
  emulator_cores?: string[] | null
  screenshots?: string[] | null
  genres?: DetailsRecord[] | null
  themes?: DetailsRecord[] | null
  game_modes?: DetailsRecord[] | null
  player_perspectives?: DetailsRecord[] | null
  platforms?: DetailsRecord[] | null
  urls?: DetailsRecord[] | null
  translation_patches?: TranslationPatch[] | null
  vr_compat?: 'native_vr' | 'injector_profile' | 'flat' | null
  /** INSP-40 — headset records behind the VR line; deep links only. */
  vr_profiles?: {
    kind: 'native' | 'injector' | 'flat'
    runtime: 'openxr' | 'openvr' | null
    profile_url: string | null
    notes: string
    source: 'librarian' | 'community'
  }[]
  /** INSP-1 — where the saves live; templated paths the companion expands. null = manifest silent. */
  save_paths?: SavePath[] | null
  /** INSP-35 — community anti-cheat reports; null when the list is silent. */
  anticheat?: AnticheatReport | null
  store_specs?: DetailsRecord | null
  is_admin?: boolean
  is_favorite?: boolean
  can_edit?: boolean
  can_play_in_browser?: boolean
  client_connected?: boolean
  has_english?: boolean
  needs_translation?: boolean
  show_translations_block?: boolean
  patch_catalog_enabled?: boolean
  rom_patch_apply_enabled?: boolean
  rom_ai_translate?: {
    show_panel?: boolean
    note?: string | null
    target_lang?: string | null
    service_url_hint?: string | null
  } | null
  preferred_locale_matches?: boolean
  [key: string]: unknown
}

/** One admin path row from `adminPathRows(game)`. */
export interface SavePath {
  path: string
  os: 'windows' | 'linux' | 'mac' | string | null
  store: string | null
}

export interface PathRow {
  label: string
  path: string
}

/** What the Open-path dialog needs; a `PathRow` satisfies it. */
export interface PathModalRequest {
  label?: string
  path: string
}

/** One hit from the translation-patch catalogue search. */
export interface CatalogHit {
  id: string | number
  title?: string | null
  provider?: string | null
  patch_format?: string | null
  target_language?: string | null
  notes?: string | null
  source_url?: string | null
  [key: string]: unknown
}

/** `extrasPanelModel(game, versions)` — the Extras & DLC rows plus where they came from. */
export interface ExtrasModel {
  rows: DetailsRecord[]
  source: string
  loading?: boolean
}

/** One row of `/api/games/<uuid>/versions`. */
export interface VersionRow {
  kind: string
  uuid?: string | null
  label?: string | null
  [key: string]: unknown
}

/** The download / cleanup state and handlers `useVersionActions` owns. */
export interface VersionActions {
  busyVersionKey: string | null
  setBusyVersionKey: (key: string | null) => void
  versionActionStatus: string | null
  setVersionActionStatus: (status: string | null) => void
  cleanupBusy: boolean
  handleVersionDownload: (args: {
    kind?: string
    versionUuid?: string | null
    label?: string
  }) => Promise<void>
  handleCleanupOrphans: () => Promise<void>
}
