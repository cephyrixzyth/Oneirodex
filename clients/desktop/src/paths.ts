/** Join base URL and path segment without duplicate slashes. */
export function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.trim().replace(/\/+$/, '')
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${base}${suffix}`
}

/**
 * A game id is a server-supplied string that becomes a file name (`{id}.zip`) and
 * a directory name (`installs/{id}`). It must therefore be a single, plain path
 * segment: letters, digits, `_` and `-` only. `.` would name the installs root
 * itself, `..` its parent, and `/` or `\` would reach into other folders.
 */
export const GAME_UUID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

/** Client-made suffix for an isolated update generation (`update-<uuid>`). */
const GENERATION_ID_PATTERN = /^[A-Za-z0-9_-]{1,80}$/

export function isValidGameUuid(value: unknown): value is string {
  return typeof value === 'string' && GAME_UUID_PATTERN.test(value)
}

/** Throws unless `gameUuid` is safe to use as a path segment; returns it unchanged. */
export function assertValidGameUuid(gameUuid: string): string {
  if (!isValidGameUuid(gameUuid)) {
    throw new Error('Invalid game id from server — refusing to use it as a file name.')
  }
  return gameUuid
}

/** Server initiate endpoint for desktop/API clients. */
export function buildInitiateDownloadPath(gameUuid: string): string {
  return `/api/downloads/games/${assertValidGameUuid(gameUuid)}`
}

/** Web-compatible streaming path after initiate returns download_id. */
export function buildDownloadStreamPath(downloadId: number): string {
  return `/download_zip/${downloadId}`
}

/**
 * Local directory name for one game's files: `{uuid}`, or `{uuid}-{generation}`
 * for an isolated update generation. Both parts are validated.
 */
export function buildLocalInstallDirName(gameUuid: string, generation?: string): string {
  assertValidGameUuid(gameUuid)
  if (!generation) {
    return gameUuid
  }
  if (!GENERATION_ID_PATTERN.test(generation)) {
    throw new Error('Invalid update generation — refusing to use it as a file name.')
  }
  return `${gameUuid}-${generation}`
}

/** Local archive filename under the app-data downloads directory. */
export function buildLocalArchiveName(gameUuid: string, generation?: string): string {
  return `${buildLocalInstallDirName(gameUuid, generation)}.zip`
}
