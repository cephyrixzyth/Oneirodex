import { getCsrfToken } from '@oneirodex/ui'
import { deleteJson, getJson, postJson, send } from './client'

/** LIB-04 connection states — see oneirodex/utils/store_connection_status.py. */
export type StoreConnectionState =
  | 'unavailable'
  | 'disabled'
  | 'import_only'
  | 'not_configured'
  | 'not_connected'
  | 'needs_credential'
  | 'connected'
  | 'syncing'
  | 'partial'
  | 'reauth_required'
  | 'failed'
  | 'cancelled'

export type StoreConnectionAction =
  'connect' | 'reconnect' | 'sync' | 'cancel' | 'import_csv' | 'import_file' | 'disconnect'

/** Catalogue text only: the server never forwards provider error text. */
export interface StoreSyncOutcome {
  reason: string
  message: string
  action:
    | 'reconnect'
    | 'retry'
    | 'retry_later'
    | 'contact_admin'
    | 'import_csv'
    | 'check_privacy'
    | 'none'
  retryable: boolean
  audience: 'member' | 'admin'
}

export interface StoreSyncJob {
  id: number
  store: string
  trigger: 'member' | 'schedule' | 'admin'
  status: 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
  outcome: StoreSyncOutcome | null
  cancellable: boolean
  cancel_requested: boolean
  progress: { pages: number; items_seen: number }
  synced: number | null
  matched: number | null
  started_at: string | null
  heartbeat_at: string | null
  finished_at: string | null
}

export interface StoreConnection {
  provider: string
  name: string
  authority: string
  state: StoreConnectionState
  live: boolean
  cancellable: boolean
  setup: { ready: boolean; missing: 'server_key' | 'opt_in' | 'client_package' | null }
  /** `unknown`: saved before LIB-04 on a server with a household sign-in, so it may be one. */
  credential: {
    source: 'member' | 'household' | 'unknown' | 'none' | 'not_required'
    household_available: boolean
  }
  account: {
    connected: boolean
    linked_at: string | null
    updated_at: string | null
    external_account_id?: string | null
  }
  records: { owned: number; matched: number; needs_review: number; last_recorded_at: string | null }
  last_sync: StoreSyncJob | null
  previous_failure: StoreSyncJob | null
  actions: StoreConnectionAction[]
}

export interface StoreConnectionsResponse {
  schema_version: number
  sync_enabled: boolean
  connections: StoreConnection[]
}

export interface OwnershipTitle {
  id: number
  store: string
  external_app_id: string
  name: string | null
  matched_game_uuid: string | null
  match_available: boolean
  match_revision: number
  match_reviewed: boolean
  /** Matched to a game in a library this member cannot open (uuid and name withheld). */
  match_hidden?: boolean
  /** ACL-filtered name/platform of the current match, when visible. */
  matched_game?: { name: string | null; platform: string | null } | null
}

export interface OwnershipTitlesPage {
  titles: OwnershipTitle[]
  next_after_id: number | null
}

export interface OwnershipCandidate {
  game_uuid: string
  name: string
  library_uuid: string
  platform: string | null
}

export interface OwnershipCandidates {
  title_id: number
  match_revision: number
  candidates: OwnershipCandidate[]
  truncated: boolean
}

export interface OwnershipDecision {
  title_id: number
  matched_game_uuid: string | null
  match_reviewed: boolean
  match_revision: number
}

export interface StoreSyncResponse {
  synced?: number
  matched?: number
  store: string
  cancelled?: boolean
  job?: StoreSyncJob
}

export interface StoreImportResponse {
  imported?: number
  matched?: number
  skipped?: number
}

/** One status contract for first-run and Settings. Stored facts only — no provider call. */
export async function fetchOwnershipConnections({ signal }: { signal?: AbortSignal } = {}) {
  return getJson('/api/ownership/connections', {
    signal,
    label: 'ownership_connections',
  }) as Promise<StoreConnectionsResponse>
}

/**
 * Link or reconnect through the store's existing connect route. `body` uses the
 * field names that route already reads; empty values are dropped so a
 * reconnect without a new token keeps the saved one.
 */
export async function connectStore(store: string, body: Record<string, string>) {
  const payload = Object.fromEntries(
    Object.entries(body).filter(([, value]) => typeof value === 'string' && value.trim() !== ''),
  )
  return postJson(`/api/ownership/${store}`, payload, { label: `connect_${store}` })
}

/** Live sync for any provider with a sync route (steam, gog, epic, amazon, xbox, psn). */
export async function syncStore(store: string) {
  return postJson(
    `/api/ownership/${store}/sync`,
    {},
    { label: `sync_${store}` },
  ) as Promise<StoreSyncResponse>
}

/** Honoured only between provider pages (GOG, Epic, Amazon); others answer not_cancellable. */
export async function cancelStoreSync(store: string) {
  return postJson(`/api/ownership/${store}/sync/cancel`, {}, { label: `cancel_sync_${store}` })
}

export async function disconnectStore(store: string) {
  return deleteJson(`/api/ownership/${store}`, undefined, { label: `disconnect_${store}` })
}

/** Playnite export (JSON or CSV file) — register-only ownership marks. */
export async function importPlayniteFile(file: File) {
  const body = new FormData()
  body.append('file', file)
  const token = getCsrfToken()
  if (token) {
    body.append('csrf_token', token)
  }
  return send('/api/imports/playnite', {
    method: 'POST',
    body,
    label: 'import_playnite',
  }) as Promise<StoreImportResponse>
}

export async function fetchOwnershipTitles(
  afterId = 0,
  {
    signal,
    status: show,
  }: { signal?: AbortSignal; status?: 'needs_review' | 'matched' | 'all' } = {},
) {
  const filter = show && show !== 'all' ? `&status=${encodeURIComponent(show)}` : ''
  return getJson(`/api/ownership/titles?after_id=${afterId}${filter}`, {
    signal,
    label: 'ownership_titles',
  }) as Promise<OwnershipTitlesPage>
}

export async function fetchOwnershipCandidates(
  titleId: number,
  { signal }: { signal?: AbortSignal } = {},
) {
  return getJson(`/api/ownership/titles/${titleId}/candidates`, {
    signal,
    label: 'ownership_candidates',
  }) as Promise<OwnershipCandidates>
}

export async function reviewOwnershipMatch(
  titleId: number,
  gameUuid: string | null,
  revision: number,
) {
  return postJson(
    `/api/ownership/titles/${titleId}/match`,
    { game_uuid: gameUuid, expected_revision: revision },
    { label: 'ownership_match' },
  ) as Promise<OwnershipDecision>
}

export async function undoOwnershipMatch(titleId: number, revision: number) {
  return postJson(
    `/api/ownership/titles/${titleId}/match/undo`,
    { expected_revision: revision },
    { label: 'ownership_match_undo' },
  ) as Promise<OwnershipDecision>
}

/** Implemented provider capabilities; this does not indicate a linked account. */
export async function fetchOwnershipProviders({ signal }: { signal?: AbortSignal } = {}) {
  return getJson('/api/ownership/providers', { signal, label: 'ownership_providers' })
}

export async function fetchOwnership({ signal }: LooseProps = {}) {
  return getJson('/api/ownership', { signal, label: 'ownership' })
}

export async function connectSteam(steamId: any) {
  return postJson('/api/ownership/steam', { steam_id: steamId }, { label: 'connect_steam' })
}

export async function disconnectSteam() {
  return deleteJson('/api/ownership/steam', undefined, { label: 'disconnect_steam' })
}

export async function syncSteam() {
  return postJson('/api/ownership/steam/sync', {}, { label: 'sync_steam' })
}

export async function connectGog(gogUserId: any, { refreshToken, accessToken }: LooseProps = {}) {
  return postJson(
    '/api/ownership/gog',
    {
      gog_user_id: gogUserId,
      ...(refreshToken ? { refresh_token: refreshToken } : {}),
      ...(accessToken ? { access_token: accessToken } : {}),
    },
    { label: 'connect_gog' },
  )
}

export async function disconnectGog() {
  return deleteJson('/api/ownership/gog', undefined, { label: 'disconnect_gog' })
}

export async function syncGog() {
  return postJson('/api/ownership/gog/sync', {}, { label: 'sync_gog' })
}

export async function connectEpic(epicAccountId: any, { deviceAuth }: LooseProps = {}) {
  return postJson(
    '/api/ownership/epic',
    {
      epic_account_id: epicAccountId,
      ...(deviceAuth ? { device_auth: deviceAuth } : {}),
    },
    { label: 'connect_epic' },
  )
}

export async function disconnectEpic() {
  return deleteJson('/api/ownership/epic', undefined, { label: 'disconnect_epic' })
}

export async function syncEpic() {
  return postJson('/api/ownership/epic/sync', {}, { label: 'sync_epic' })
}

export async function connectAmazon(
  amazonUserId: any,
  { credential, refreshToken, deviceSerial }: LooseProps = {},
) {
  return postJson(
    '/api/ownership/amazon',
    {
      amazon_user_id: amazonUserId,
      ...(credential ? { credential } : {}),
      ...(refreshToken ? { refresh_token: refreshToken } : {}),
      ...(deviceSerial ? { device_serial: deviceSerial } : {}),
    },
    { label: 'connect_amazon' },
  )
}

export async function disconnectAmazon() {
  return deleteJson('/api/ownership/amazon', undefined, { label: 'disconnect_amazon' })
}

export async function syncAmazon() {
  return postJson('/api/ownership/amazon/sync', {}, { label: 'sync_amazon' })
}

/**
 * The CSV endpoints accept either a JSON `csv` string or a multipart upload
 * under the `file` field, so pass whichever the member supplied.
 */
export async function importCsv(store: any, { csv, file }: LooseProps = {}) {
  const url = `/api/ownership/${store}/csv`
  const label = `import_${store}_csv`

  if (file) {
    const body = new FormData()
    body.append('file', file)
    const token = getCsrfToken()
    if (token) {
      body.append('csrf_token', token)
    }
    return send(url, { method: 'POST', body, label })
  }

  return postJson(url, { csv }, { label })
}

/** INSP-42 — Xbox / PlayStation: register-only, opt-in, unofficial. CSV always; live only when the server opted in. */
export async function connectXbox(
  xuid: string | null | undefined,
  { credential }: { credential?: string } = {},
) {
  return postJson(
    '/api/ownership/xbox',
    { ...(xuid ? { note: String(xuid) } : {}), ...(credential ? { credential } : {}) },
    { label: 'connect_xbox' },
  )
}

export async function disconnectXbox() {
  return deleteJson('/api/ownership/xbox', undefined, { label: 'disconnect_xbox' })
}

export async function syncXbox() {
  return postJson('/api/ownership/xbox/sync', {}, { label: 'sync_xbox' })
}

export async function connectPsn(
  onlineId: string | null | undefined,
  { npsso }: { npsso?: string } = {},
) {
  return postJson(
    '/api/ownership/psn',
    { ...(onlineId ? { online_id: String(onlineId) } : {}), ...(npsso ? { npsso } : {}) },
    { label: 'connect_psn' },
  )
}

export async function disconnectPsn() {
  return deleteJson('/api/ownership/psn', undefined, { label: 'disconnect_psn' })
}

export async function syncPsn() {
  return postJson('/api/ownership/psn/sync', {}, { label: 'sync_psn' })
}
