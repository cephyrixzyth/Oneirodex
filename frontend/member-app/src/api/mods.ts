/** Tracked mods per game (MOD-3) and the read-only catalogue browse (INSP-22). */
import { deleteJson, getJson, patchJson, postJson } from './client'

export interface ModRow {
  id: string
  name: string
  version: string
  source_url: string
  url?: string
  notes: string
  enabled: boolean
  load_order: number
  /** INSP-36 — loader slug the mod needs; `''` when unsaid. */
  loader: string
  /** INSP-38 — ids of rows this one needs first. */
  requires?: string[]
  /** INSP-39 — newest version a registry showed for this row. */
  latest_seen_version?: string
}

export interface LoaderConflict {
  id: string
  name: string
  loader: string
  default_loader: string
}

export interface ModProfile {
  id: string
  name: string
  mod_ids: string[]
  unresolved?: string[]
  import_order?: string[]
  requirements?: Array<{
    id: string
    version: string
    loader: string
    source_url: string
    requires?: string[]
  }>
}

export interface ModPack {
  enabled: boolean
  game_uuid?: string
  default_loader: string
  loaders: string[]
  mods: ModRow[]
  /** INSP-37 — named sets of mod ids, and which one was last activated. */
  profiles: ModProfile[]
  active_profile: string
  /** INSP-38 — enabled rows whose loader disagrees with the pack default. */
  loader_conflicts: LoaderConflict[]
}

export interface ModProfileImportResult {
  profile: ModProfile
  matched: number
  missing: { name: string; version: string; loader: string; source_url: string }[]
  suggested_default_loader: string
}

export interface ModHit {
  name: string
  url: string
  source: string
  version: string
  loader: string
  summary: string
  author: string
  downloads: number | null
  updated: string | null
  categories: string[]
  /** INSP-38 — package names this one needs, when the registry says so. */
  dependencies?: string[]
  /** INSP-39 — set when the pack already tracks this hit by source URL. */
  tracked_id?: string
  update_available?: string | null
}

export interface ModCatalogResult {
  source: string
  status: 'ok' | 'unavailable' | 'unknown_source'
  hits: ModHit[] | null
  count?: number
  note?: string
}

export interface ModDraft {
  name: string
  version?: string
  source_url?: string
  notes?: string
  loader?: string
  enabled?: boolean
  requires?: string[]
  latest_seen_version?: string
}

export const MOD_CATALOG_SOURCES: { id: string; label: string }[] = [
  { id: 'thunderstore', label: 'Thunderstore' },
  { id: 'modrinth', label: 'Modrinth' },
  { id: 'gamebanana', label: 'GameBanana' },
  { id: 'nexus', label: 'Nexus Mods' },
]

function modsUrl(gameUuid: string, tail = '') {
  return `/api/games/${encodeURIComponent(gameUuid)}/mods${tail}`
}

export async function fetchMods(gameUuid: string): Promise<ModPack> {
  const data = (await getJson(modsUrl(gameUuid), { label: 'Could not load mods' })) ?? {}
  return {
    enabled: data.enabled !== false,
    game_uuid: data.game_uuid,
    default_loader: String(data.default_loader || ''),
    loaders: Array.isArray(data.loaders) ? data.loaders.map(String) : [],
    mods: Array.isArray(data.mods) ? (data.mods as ModRow[]) : [],
    profiles: Array.isArray(data.profiles) ? (data.profiles as ModProfile[]) : [],
    active_profile: String(data.active_profile || ''),
    loader_conflicts: Array.isArray(data.loader_conflicts)
      ? (data.loader_conflicts as LoaderConflict[])
      : [],
  }
}

export async function createModProfile(gameUuid: string, name: string, modIds?: string[]) {
  const body: { name: string; mod_ids?: string[] } = { name }
  if (modIds) body.mod_ids = modIds
  return postJson(modsUrl(gameUuid, '/profiles'), body, { label: 'Could not save the profile' })
}

export async function deleteModProfile(gameUuid: string, profileId: string) {
  return deleteJson(modsUrl(gameUuid, `/profiles/${encodeURIComponent(profileId)}`), undefined, {
    label: 'Could not remove the profile',
  })
}

export async function activateModProfile(gameUuid: string, profileId: string) {
  return postJson(
    modsUrl(gameUuid, `/profiles/${encodeURIComponent(profileId)}/activate`),
    {},
    {
      label: 'Could not activate the profile',
    },
  )
}

export async function exportModProfile(gameUuid: string, profileId: string): Promise<string> {
  const data = await getJson(
    modsUrl(gameUuid, `/profiles/${encodeURIComponent(profileId)}/export`),
    {
      label: 'Could not export the profile',
    },
  )
  return String(data?.code || '')
}

export async function importModProfile(
  gameUuid: string,
  code: string,
  name?: string,
): Promise<ModProfileImportResult> {
  const body: { code: string; name?: string } = { code: code.trim() }
  if (name) body.name = name
  const data = await postJson(modsUrl(gameUuid, '/profiles/import'), body, {
    label: 'Could not import the profile',
  })
  return {
    profile: data?.profile as ModProfile,
    matched: Number(data?.matched || 0),
    missing: Array.isArray(data?.missing) ? data.missing : [],
    suggested_default_loader: String(data?.suggested_default_loader || ''),
  }
}

export async function createMod(gameUuid: string, draft: ModDraft): Promise<ModRow> {
  const data = await postJson(modsUrl(gameUuid), draft, { label: 'Could not add the mod' })
  return data?.mod as ModRow
}

export async function updateMod(gameUuid: string, modId: string, patch: Partial<ModDraft>) {
  const data = await patchJson(modsUrl(gameUuid, `/${encodeURIComponent(modId)}`), patch, {
    label: 'Could not update the mod',
  })
  return data?.mod as ModRow
}

export async function deleteMod(gameUuid: string, modId: string) {
  return deleteJson(modsUrl(gameUuid, `/${encodeURIComponent(modId)}`), undefined, {
    label: 'Could not remove the mod',
  })
}

export async function setDefaultLoader(gameUuid: string, loader: string) {
  return patchJson(
    modsUrl(gameUuid, '/pack'),
    { default_loader: loader },
    { label: 'Could not save the loader' },
  )
}

export async function browseModCatalog(
  gameUuid: string,
  source: string,
  query = '',
  { signal }: { signal?: AbortSignal } = {},
): Promise<ModCatalogResult> {
  const params = new URLSearchParams({ source })
  if (query) params.set('q', query)
  const data =
    (await getJson(modsUrl(gameUuid, `/catalog?${params}`), {
      signal,
      label: 'Could not browse the catalogue',
    })) ?? {}
  return {
    source: String(data.source || source),
    status: (data.status as ModCatalogResult['status']) || 'unavailable',
    hits: Array.isArray(data.hits) ? (data.hits as ModHit[]) : null,
    count: typeof data.count === 'number' ? data.count : undefined,
    note: data.note ? String(data.note) : undefined,
  }
}
