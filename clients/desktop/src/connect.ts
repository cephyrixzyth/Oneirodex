import type { OneirodexClient, SearchResultItem } from '@oneirodex/api-client'
import { OneirodexApiError } from '@oneirodex/api-client'

import { DesktopTransportError } from './api.js'

import type { LifecycleRegistry } from './lifecycle.js'

export interface ConnectionValidation {
  ok: true
  collectionCount: number
}

export interface ConnectionFailure {
  ok: false
  message: string
  /** Machine-oriented cause for companion console / local diagnostics. */
  cause?:
    | 'shape_invalid'
    | 'unauthorized'
    | 'forbidden'
    | 'not_found'
    | 'network'
    | 'keyring'
    | 'redirect_refused'
    | 'protocol'
    | 'unknown'
}

export type ConnectionResult = ConnectionValidation | ConnectionFailure

const TOKEN_401_HINT =
  'Unauthorized (401). Paste the full one-time secret (gt_<prefix>_<urlsafe-secret>) — hyphens in the secret are normal; truncating after the last "-" breaks verify.'

/** Companion console logger (safe for secrets — callers must not pass the token). */
export function logCompanion(scope: string, message: string, detail?: unknown): void {
  if (detail !== undefined) {
    console.warn(`[Oneirodex:${scope}] ${message}`, detail)
  } else {
    console.warn(`[Oneirodex:${scope}] ${message}`)
  }
}

function isNetworkFailure(error: unknown): boolean {
  if (error instanceof OneirodexApiError || error instanceof DesktopTransportError) {
    return false
  }
  if (!(error instanceof Error)) {
    return false
  }
  const msg = error.message
  if (
    /failed to fetch|networkerror|load failed|failed to load|cors|ssl|tls|certificate|cert_|econnrefused|enotfound|etimedout|network request failed|net::err/i.test(
      msg,
    )
  ) {
    return true
  }
  return false
}

/** Maps OS keyring / secure-store failures (e.g. keyring "Bad data") to clear copy. */
export function formatKeychainError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error)
  logCompanion('keyring', `persist/load failed: ${raw}`)
  if (
    /bad data|baddata|invalid data|platform error|credential|keyring|secure.?store|keychain|dpapi/i.test(
      raw,
    )
  ) {
    return `Could not save the API token in the OS credential store (${raw}). Check Windows Credential Manager access, then retry Connect.`
  }
  return `Could not save the API token in the OS credential store: ${raw}`
}

/** Maps API / runtime failures to short companion status copy. */
export function formatDesktopApiError(error: unknown): string {
  if (error instanceof OneirodexApiError) {
    switch (error.status) {
      case 401:
        return TOKEN_401_HINT
      case 403:
        return 'Token lacks required scope (403). Need read:library; write:download for installs.'
      case 404:
        return 'Server URL looks wrong (404). Check the base URL.'
      case 429:
        return 'Too many requests (429). Wait a moment and retry.'
      default:
        return error.message || `HTTP ${error.status}`
    }
  }
  if (isNetworkFailure(error)) {
    const detail = error instanceof Error ? error.message : String(error)
    return `Network/TLS/CORS error — check base URL, HTTPS cert, and that the server is reachable (${detail}).`
  }
  if (error instanceof Error) {
    const msg = error.message
    if (/not allowed|permission|denied|capability/i.test(msg)) {
      return `Companion permission error: ${msg}`
    }
    if (/ENOENT|no such file|not found/i.test(msg)) {
      return `Local file missing: ${msg}`
    }
    if (/bad data|baddata|keyring|secure.?store|credential/i.test(msg)) {
      return formatKeychainError(error)
    }
    return msg
  }
  return 'Connection failed'
}

export function classifyConnectionError(error: unknown): ConnectionFailure['cause'] {
  if (error instanceof DesktopTransportError) return error.cause
  if (error instanceof OneirodexApiError) {
    if (error.status === 401) return 'unauthorized'
    if (error.status === 403) return 'forbidden'
    if (error.status === 404) return 'not_found'
    return 'unknown'
  }
  if (isNetworkFailure(error)) {
    return 'network'
  }
  if (
    error instanceof Error &&
    /bad data|baddata|keyring|secure.?store|credential/i.test(error.message)
  ) {
    return 'keyring'
  }
  return 'unknown'
}

/** Validates credentials by listing collections (lightweight authenticated call). */
export async function validateConnection(api: OneirodexClient): Promise<ConnectionResult> {
  try {
    const collections = await api.browse.listCollections()
    if (!Array.isArray(collections)) throw new DesktopTransportError('protocol')
    return { ok: true, collectionCount: collections.length }
  } catch (error) {
    const cause = classifyConnectionError(error)
    const message = formatDesktopApiError(error)
    logCompanion('connect', `validate failed (${cause}): ${message}`, error)
    return { ok: false, message, cause }
  }
}

/** Client-side token shape reject before any network call. */
export function shapeInvalidConnectionResult(): ConnectionFailure {
  const message =
    'Enter a valid Oneirodex API token (gt_<prefix>_<urlsafe-secret>). Remove labels/HTML after paste; do not cut the secret at a hyphen — "-" inside the secret is normal.'
  logCompanion('connect', `validate skipped: shape_invalid`)
  return { ok: false, message, cause: 'shape_invalid' }
}

function extractSearchResults(response: {
  results?: SearchResultItem[]
  games?: SearchResultItem[]
}): SearchResultItem[] {
  return response.results ?? response.games ?? []
}

/** Fetches a small slice of the library via search (fallback queries if empty). */
export async function fetchLibraryPreview(
  api: OneirodexClient,
  limit = 12,
  strict = false,
): Promise<SearchResultItem[]> {
  const queries = ['', '*', 'a']
  for (const query of queries) {
    try {
      const response = await api.browse.search({ query })
      if (strict && (!response || !Array.isArray(response.results ?? response.games))) {
        throw new DesktopTransportError('protocol')
      }
      const items = extractSearchResults(response)
      if (items.length > 0) {
        return items.slice(0, limit)
      }
    } catch (error) {
      if (strict) throw error
      // try next query shape
    }
  }
  return []
}

/**
 * When local state is installed but search marks an update, flip to update_available.
 * Returns how many games were signaled.
 */
export function mergeUpdateSignalsFromLibrary(
  registry: LifecycleRegistry,
  games: SearchResultItem[],
): number {
  let signaled = 0
  for (const game of games) {
    const uuid = typeof game.uuid === 'string' ? game.uuid : ''
    if (!uuid || registry.get(uuid) !== 'installed') {
      continue
    }
    const hasUpdates = game.has_updates === true
    const lifecycle = game.lifecycle_state
    if (hasUpdates || lifecycle === 'update_available') {
      registry.signalUpdateAvailable(uuid)
      signaled += 1
    }
  }
  return signaled
}

/** Only transport/service unavailability is an outage; denial and protocol failures are separate. */
export function isConnectionUnavailable(error: unknown): boolean {
  return (
    isNetworkFailure(error) ||
    (error instanceof OneirodexApiError && [408, 502, 503, 504].includes(error.status))
  )
}
