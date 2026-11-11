import {
  createAuthStore,
  describeTokenPaste,
  isOneirodexToken,
  normalizeBaseUrl,
  normalizeOneirodexToken,
} from './auth.js'
import { createDesktopApi, DesktopTransportError } from './api.js'
import { escapeHtml } from './html.js'
import { kickoffDownload, pickDownloadVersion } from './download.js'
import { cancelInstallArchive, kickoffInstall } from './install.js'
import { loadInstallsFromDisk } from './install-store.js'
import { canLaunchGame, kickoffLaunch, stopAllLaunchWatchers } from './launch.js'
import { kickoffUninstall, kickoffUpdate } from './uninstall.js'
import { kickoffApplyPatch, stagePatchFile } from './apply_patch.js'
import {
  fetchModsSummaryGameUuids,
  kickoffApplyModPack,
  modApplyBlockedReason,
  modApplyUiHint,
} from './apply_mods.js'
import { getOrCreateDeviceId, startClientHeartbeat, type HeartbeatScheduler } from './heartbeat.js'
import { getInstallsDir } from './download.js'
import { revealPathInOs } from './open-path.js'
import { expandSavePath, hasSavePlaceholder, tauriResolvers } from './save-paths.js'
import {
  fetchLibraryPreview,
  classifyConnectionError,
  isConnectionUnavailable,
  formatDesktopApiError,
  formatKeychainError,
  logCompanion,
  mergeUpdateSignalsFromLibrary,
  shapeInvalidConnectionResult,
  validateConnection,
} from './connect.js'
import { loadStoredConfig, saveStoredConfig } from './config-store.js'
import { openFullLibraryWindow } from './library-window.js'
import { openSocialCompanionWindow } from './social-window.js'
import { keychainAdapter } from './keychain.js'
import {
  formatTrustedShares,
  loadTrustedShares,
  parseTrustedShares,
  saveTrustedShares,
} from './trusted-shares.js'
import { buildLocalArchiveName } from './paths.js'
import {
  installedOfflineGames,
  clearOfflineInstalledShelf,
  loadOfflineInstalledShelf,
  saveOfflineInstalledShelf,
  type OfflineShelfGame,
} from './offline-shelf.js'
import { checkServerUrl } from './transport-policy.js'
import {
  hydrateLifecycleRegistry,
  pullLifecycleRegistryFromServer,
  syncLifecycleRegistryToServer,
  type LifecycleRegistry,
} from './lifecycle-store.js'
import { canPerformAction, type GameLifecycleState, type LifecycleAction } from './lifecycle.js'
import {
  connectionModeLabel,
  friendsOpenBlockedReason,
  friendsOpenStatus,
  isActionBlockedOffline,
  offlineBlockReason,
  resolveFriendsBaseUrl,
  type ConnectionMode,
} from './connection-ux.js'
import type { SearchResultItem } from '@oneirodex/api-client'
let auth = createAuthStore()
let connectionEpoch = 0
let profileWrites: Promise<void> = Promise.resolve()
function queueProfileWrite(write: () => Promise<void>): Promise<void> {
  const pending = profileWrites.catch(() => undefined).then(write)
  profileWrites = pending.catch(() => undefined)
  return pending
}
let lifecycle: LifecycleRegistry | null = null
/** True after a successful Connect that loaded library preview (kept through offline). */
let sessionActive = false
let connectionMode: ConnectionMode = 'disconnected'
let libraryGames: SearchResultItem[] = []
let verifiedAccountId = ''
let localInstalls: Record<
  string,
  { extractPath?: string; archivePath?: string; exePath?: string | null }
> = {}
let heartbeatScheduler: HeartbeatScheduler | null = null
let gamesWithEnabledMods = new Set<string>()
let modsTrackingEnabled = true
const gameActivity = new Map<string, string>()
const busyGames = new Set<string>()
const archiveInstallOperations = new Map<string, string>()
async function ensureLifecycleRegistry(): Promise<LifecycleRegistry> {
  if (!lifecycle) {
    lifecycle = await hydrateLifecycleRegistry(undefined, () => {
      setStatus(
        'Install status could not be saved on this device. Check storage space and permissions.',
        'error',
      )
    })
  }
  return lifecycle
}
function setConnectionMode(mode: ConnectionMode): void {
  connectionMode = mode
}
let els: {
  baseUrl: HTMLInputElement
  token: HTMLInputElement
  connectBtn: HTMLButtonElement
  status: HTMLParagraphElement
  authSummary: HTMLParagraphElement
  library: HTMLElement
  lifecyclePanel: HTMLElement
}
function setStatus(message: string, tone: 'info' | 'error' | 'success' = 'info'): void {
  if (els.status.textContent !== message) {
    els.status.textContent = message
  }
  els.status.dataset.tone = tone
}
function setGameActivity(gameUuid: string, message: string): void {
  if (message) {
    gameActivity.set(gameUuid, message)
  } else {
    gameActivity.delete(gameUuid)
  }
  const card = els.library.querySelector(`[data-game-uuid="${CSS.escape(gameUuid)}"]`)
  if (!(card instanceof HTMLElement)) {
    return
  }
  let activityEl = card.querySelector('.activity')
  if (!message) {
    activityEl?.remove()
    return
  }
  if (!(activityEl instanceof HTMLElement)) {
    activityEl = document.createElement('p')
    activityEl.className = 'activity'
    card.appendChild(activityEl)
  }
  activityEl.textContent = message
}
function renderAuthSummary(): void {
  const snapshot = auth.snapshot()
  const mode = connectionModeLabel(connectionMode)
  els.authSummary.textContent = snapshot.hasToken
    ? `Server: ${snapshot.baseUrl || '(not set)'} · token configured · ${mode}`
    : `Not connected — enter server URL and API token. · ${mode}`
}
async function renderLifecyclePanel(): Promise<void> {
  const registry = lifecycle
  if (!registry) {
    return
  }
  const records = registry
    .snapshot()
    .filter(
      (record) =>
        sessionActive &&
        libraryGames.some((game) => game.uuid === record.gameUuid) &&
        (connectionMode === 'online' ||
          (localInstalls[record.gameUuid] && canLaunchGame(record.state))),
    )
  if (records.length === 0) {
    els.lifecyclePanel.innerHTML =
      '<p class="muted">Lifecycle states appear after you load games (all start as <code>not_downloaded</code>).</p>'
    return
  }
  const installs = localInstalls
  const nameByUuid = new Map(
    libraryGames.map((g) => [g.uuid, typeof g.name === 'string' ? g.name : g.uuid]),
  )
  const rows = records
    .map((record) => {
      const install = installs[record.gameUuid]
      const title = nameByUuid.get(record.gameUuid) || record.gameUuid
      const stateClass = record.state === 'update_available' ? 'state-update' : 'state-ok'
      const pathBit = install?.extractPath
        ? `<div class="install-path"><code>${escapeHtml(install.extractPath)}</code></div>`
        : '<div class="install-path muted">No local install path</div>'
      const exeBit = install?.exePath
        ? `<div class="install-exe muted">exe: <code>${escapeHtml(install.exePath)}</code></div>`
        : ''
      const revealBit = install?.extractPath
        ? `<button type="button" class="action-btn secondary action-btn--reveal" data-action="reveal_path" data-uuid="${escapeHtml(record.gameUuid)}" title="Open install folder in Explorer / Finder">Show in Explorer</button>`
        : ''
      return `<li class="${stateClass}">
        <div><strong>${escapeHtml(title)}</strong> — <span class="state-pill">${escapeHtml(record.state)}</span></div>
        <div class="uuid muted"><code>${escapeHtml(record.gameUuid)}</code></div>
        ${pathBit}${exeBit}${revealBit}
      </li>`
    })
    .join('')
  els.lifecyclePanel.innerHTML = `<ul class="lifecycle-list">${rows}</ul>`
}
function lifecycleActionsFor(state: GameLifecycleState): LifecycleAction[] {
  const actions: LifecycleAction[] = ['download', 'install', 'update', 'uninstall']
  return actions.filter((action) => canPerformAction(state, action))
}
function renderLibrary(): void {
  const registry = lifecycle
  if (!sessionActive) {
    els.library.innerHTML = '<p class="muted">Connect to load your library preview.</p>'
    renderLifecyclePanel()
    return
  }
  if (!registry) {
    els.library.innerHTML = '<p class="muted">Loading lifecycle registry…</p>'
    return
  }
  const visibleGames =
    connectionMode !== 'online'
      ? installedOfflineGames(libraryGames as OfflineShelfGame[], localInstalls, (uuid) =>
          canLaunchGame(registry.get(uuid)),
        )
      : libraryGames
  if (visibleGames.length === 0) {
    els.library.innerHTML =
      connectionMode !== 'online'
        ? '<p class="muted">No locally installed games from this verified account are available offline. Connect while online to refresh the Installed shelf.</p>'
        : '<p class="muted">Connected, but no games returned from search. Try another server or query later.</p>'
    renderLifecyclePanel()
    return
  }
  const offlineBanner =
    connectionMode !== 'online'
      ? `<p class="offline-banner" role="status">Local Installed shelf — these titles were previously verified for this server account on this device. Play and Reveal use local files; anyone with OS-level access to those files may also access them. Reconnect to refresh server access.</p>`
      : ''
  const cards = visibleGames
    .map((game) => {
      const uuid = game.uuid
      const name = typeof game.name === 'string' ? game.name : uuid
      const state = registry.get(uuid)
      const actions = connectionMode !== 'online' ? [] : lifecycleActionsFor(state)
      const isBusy = busyGames.has(uuid)
      const activity = gameActivity.get(uuid)
      const actionButtons = actions
        .map((action) => {
          const blocked = isActionBlockedOffline(action, connectionMode)
          const title = blocked ? ` title="${escapeHtml(offlineBlockReason(action))}"` : ''
          const disabled = isBusy || blocked ? 'disabled' : ''
          const updateClass =
            action === 'update' && state === 'update_available' ? ' action-btn--update' : ''
          const label = action.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase())
          return `<button type="button" class="action-btn secondary${updateClass}" data-action="${action}" data-uuid="${escapeHtml(uuid)}"${title} ${disabled}>${label}</button>`
        })
        .join('')
      const cancelInstallButton = archiveInstallOperations.has(uuid)
        ? `<button type="button" class="action-btn secondary action-btn--cancel-install" data-action="cancel_install" data-uuid="${escapeHtml(uuid)}">Cancel install</button>`
        : ''
      const playButton = canLaunchGame(state)
        ? `<button type="button" class="action-btn primary play-btn" data-action="play" data-uuid="${escapeHtml(uuid)}" ${isBusy ? 'disabled' : ''}>Play</button>`
        : ''
      const modBlocked = modApplyBlockedReason({
        connectionOnline: connectionMode === 'online',
        modsTrackingEnabled,
        hasEnabledMods: gamesWithEnabledMods.has(uuid),
        installed: canLaunchGame(state),
      })
      const modTitle = modBlocked
        ? ` title="${escapeHtml(modBlocked)}"`
        : ` title="${escapeHtml(modApplyUiHint(connectionMode === 'online'))}"`
      const modDisabled = isBusy || Boolean(modBlocked) ? 'disabled' : ''
      const modButton =
        connectionMode === 'online' &&
        modsTrackingEnabled &&
        (gamesWithEnabledMods.has(uuid) || canLaunchGame(state))
          ? `<button type="button" class="action-btn secondary action-btn--mods" data-action="apply_mods" data-uuid="${escapeHtml(uuid)}"${modTitle} ${modDisabled}>Apply mods</button>`
          : ''
      const revealButton = canLaunchGame(state)
        ? `<button type="button" class="action-btn secondary action-btn--reveal" data-action="reveal_path" data-uuid="${escapeHtml(uuid)}" title="Open install folder in Explorer / Finder">Show in Explorer</button>`
        : ''
      const activityHtml = activity ? `<p class="activity">${escapeHtml(activity)}</p>` : ''
      return `
        <article class="game-card" data-game-uuid="${escapeHtml(uuid)}">
          <h3>${escapeHtml(name)}</h3>
          <p class="uuid">${escapeHtml(uuid)}</p>
          <p class="state">State: <strong>${escapeHtml(state)}</strong></p>
          ${activityHtml}
          <div class="actions">${playButton}${revealButton}${modButton}${cancelInstallButton}${actionButtons || (!playButton && !modButton && !revealButton && !cancelInstallButton ? '<span class="muted">No actions</span>' : '')}</div>
        </article>
      `
    })
    .join('')
  els.library.innerHTML = `${offlineBanner}<div class="game-grid">${cards}</div>`
  renderLifecyclePanel()
}
async function hydrateFromDisk(): Promise<void> {
  const stored = await loadStoredConfig()
  try {
    auth.setBaseUrl(stored.baseUrl)
  } catch (error) {
    // A URL saved by an older build that the transport policy now refuses (plain
    // http:// to a public host). It stays visible in the form so it can be
    // corrected, but never reaches the auth store — so no request carries the token.
    setStatus(error instanceof Error ? error.message : String(error), 'error')
  }
  auth.setToken(stored.token)
  try {
    await auth.hydrateFromKeychain(keychainAdapter)
  } catch (error) {
    logCompanion(
      'keyring',
      `hydrate failed: ${error instanceof Error ? error.message : String(error)}`,
    )
    setStatus(formatKeychainError(error), 'error')
  }
  els.baseUrl.value = auth.getBaseUrl() || stored.baseUrl
  const token = auth.getToken()
  els.token.value = token ? normalizeOneirodexToken(token) : ''
  renderAuthSummary()
}

interface VerifiedLocalShelf {
  accountId: string
  games: SearchResultItem[]
  installs: typeof localInstalls
}

async function loadVerifiedOfflineShelf(
  serverUrl: string,
  token: string,
): Promise<VerifiedLocalShelf | null> {
  try {
    const shelf = await loadOfflineInstalledShelf({
      serverUrl,
      deviceId: getOrCreateDeviceId(),
      token,
    })
    if (!shelf) return null
    const installs = await loadInstallsFromDisk()
    return {
      accountId: shelf.accountId,
      games: installedOfflineGames(shelf.games, installs, (uuid) =>
        Boolean(lifecycle && canLaunchGame(lifecycle.get(uuid))),
      ) as SearchResultItem[],
      installs,
    }
  } catch {
    return null
  }
}

class AccountIdentityChangedError extends Error {
  constructor() {
    super(
      'Server account identity changed. Reconnect with the intended account; previous catalog metadata has been cleared.',
    )
  }
}

function displayConnectionFailure(error: unknown, message = formatDesktopApiError(error)): void {
  const cause = classifyConnectionError(error)
  setConnectionMode(
    isConnectionUnavailable(error)
      ? 'offline'
      : cause === 'unauthorized' || cause === 'forbidden'
        ? 'denied'
        : 'error',
  )
  libraryGames = installedOfflineGames(libraryGames as OfflineShelfGame[], localInstalls, (uuid) =>
    Boolean(lifecycle && canLaunchGame(lifecycle.get(uuid))),
  ) as SearchResultItem[]
  if (error instanceof AccountIdentityChangedError) {
    heartbeatScheduler?.stop()
    heartbeatScheduler = null
    libraryGames = []
    verifiedAccountId = ''
    try {
      clearOfflineInstalledShelf()
    } catch {
      /* UI stays cleared even if local storage refuses. */
    }
  }
  sessionActive = libraryGames.length > 0
  const reason = connectionMode === 'denied' ? `Server access denied. ${message}` : message
  setStatus(
    `${reason}${sessionActive ? ' Showing local installs from this previously verified account; server actions remain unavailable.' : ''}`,
    'error',
  )
  renderAuthSummary()
  renderLibrary()
}

/** Identity and ACL must refresh before online actions or recovered commands resume. */
async function refreshAccount(
  connectionAuth: typeof auth,
  current: () => boolean,
  expectedAccountId: string,
): Promise<string | null> {
  const api = createDesktopApi(connectionAuth)
  const identity = await api.device.identity()
  if (!identity || typeof identity.account_id !== 'string' || !identity.account_id)
    throw new DesktopTransportError('protocol')
  if (expectedAccountId && identity.account_id !== expectedAccountId)
    throw new AccountIdentityChangedError()
  const games = await fetchLibraryPreview(api, 12, true)
  const installs = await loadInstallsFromDisk()
  const mods = await fetchModsSummaryGameUuids(connectionAuth).catch(() => ({
    gameUuids: new Set<string>(),
    trackingEnabled: false,
  }))
  if (!current()) return null
  let warning: string | null = null
  try {
    await saveOfflineInstalledShelf(
      {
        serverUrl: connectionAuth.getBaseUrl(),
        accountId: identity.account_id,
        deviceId: getOrCreateDeviceId(),
        token: connectionAuth.getToken()!,
      },
      games,
      localStorage,
      current,
    )
  } catch {
    warning = 'Connected, but the offline Installed shelf could not be saved on this device.'
  }
  if (!current()) return null
  verifiedAccountId = identity.account_id
  libraryGames = games
  localInstalls = installs
  gamesWithEnabledMods = mods.gameUuids
  modsTrackingEnabled = mods.trackingEnabled
  sessionActive = true
  return warning
}

async function handleConnect(): Promise<void> {
  if (busyGames.size > 0) {
    setStatus(
      'Finish or cancel the active local operation before switching the connection.',
      'info',
    )
    return
  }
  els.connectBtn.disabled = false
  const previousAuth = auth
  const epoch = ++connectionEpoch
  const current = () => epoch === connectionEpoch
  heartbeatScheduler?.stop()
  heartbeatScheduler = null
  sessionActive = false
  libraryGames = []
  localInstalls = {}
  verifiedAccountId = ''
  lastPlayedGameUuid = null
  auth = createAuthStore()
  setConnectionMode('disconnected')
  renderAuthSummary()
  renderLibrary()
  const baseUrl = normalizeBaseUrl(els.baseUrl.value)
  const token = normalizeOneirodexToken(els.token.value)
  logCompanion('connect', describeTokenPaste(els.token.value))
  els.baseUrl.value = baseUrl
  els.token.value = token
  if (!baseUrl) {
    setStatus('Enter a server base URL.', 'error')
    return
  }
  const serverCheck = checkServerUrl(baseUrl)
  if (!serverCheck.ok) {
    setStatus(serverCheck.message, 'error')
    return
  }
  if (!token || !isOneirodexToken(token)) {
    setStatus(shapeInvalidConnectionResult().message, 'error')
    return
  }
  if (previousAuth.getBaseUrl() !== baseUrl || previousAuth.getToken() !== token)
    stopAllLaunchWatchers()
  const connectionAuth = createAuthStore({ baseUrl, token })
  auth = connectionAuth
  els.connectBtn.disabled = true
  setConnectionMode('connecting')
  renderAuthSummary()
  setStatus('Connecting…', 'info')
  try {
    const cached = await loadVerifiedOfflineShelf(baseUrl, token)
    if (!current()) return
    const api = createDesktopApi(connectionAuth)
    const result = await validateConnection(api)
    if (!current()) return
    if (!result.ok) {
      if (cached) {
        libraryGames = cached.games
        localInstalls = cached.installs
        verifiedAccountId = cached.accountId
      }
      const mode: ConnectionMode =
        result.cause === 'network'
          ? 'offline'
          : result.cause === 'unauthorized' || result.cause === 'forbidden'
            ? 'denied'
            : 'error'
      setConnectionMode(mode)
      sessionActive = libraryGames.length > 0
      setStatus(
        `${mode === 'denied' ? 'Server access denied. ' : ''}${result.message}${sessionActive ? ' Showing local installs from this previously verified account; server actions remain unavailable.' : ''}`,
        'error',
      )
      renderAuthSummary()
      renderLibrary()
      return
    }
    // Retain matching historical local files if a subsequent identity/search/persistence request fails.
    if (cached) {
      libraryGames = cached.games
      localInstalls = cached.installs
      verifiedAccountId = cached.accountId
    }
    const warning = await refreshAccount(connectionAuth, current, cached?.accountId ?? '')
    if (!current()) return
    await queueProfileWrite(async () => {
      if (!current()) return
      await saveStoredConfig({ baseUrl, token })
      if (current()) await connectionAuth.persistToKeychain(keychainAdapter)
    })
    if (!current()) return
    setConnectionMode('online')
    const registry = await ensureLifecycleRegistry()
    if (!current()) return
    mergeUpdateSignalsFromLibrary(registry, libraryGames)
    setStatus(
      warning ??
        `Connected (${result.collectionCount} collection${result.collectionCount === 1 ? '' : 's'}).`,
      warning ? 'info' : 'success',
    )
    renderAuthSummary()
    renderLibrary()
    heartbeatScheduler = startClientHeartbeat(connectionAuth, {
      deviceKind: 'companion',
      unreachableAfterFailures: 2,
      onReachable: async () => {
        if (!current() || connectionMode === 'online') return
        const warning = await refreshAccount(connectionAuth, current, verifiedAccountId)
        if (!current()) return
        setConnectionMode('online')
        setStatus(
          warning ?? 'Server access refreshed — Download / Update re-enabled.',
          warning ? 'info' : 'success',
        )
        renderAuthSummary()
        renderLibrary()
      },
      onUnreachable: (error) => {
        if (current()) displayConnectionFailure(error)
      },
      onFailure: (error) => {
        if (current()) displayConnectionFailure(error)
      },
      onCommands: async (command) => {
        if (command.action === 'open_path') {
          // No `allowedRoots` here, deliberately: the path is a *server* path for a
          // library folder, and the companion cannot know which local mapping of it
          // (a drive letter, a mount) this PC uses — the server never tells it the
          // library roots. The guard for a hostile server is therefore the
          // validation in `revealPathInOs` and `validate_reveal_path` (Rust), which
          // refuse UNC and device paths before touching the filesystem.
          return runOpenPathCommand(command.path || '', { select: command.select })
        }
        if (isActionBlockedOffline(command.action, connectionMode)) {
          setStatus(offlineBlockReason(command.action), 'error')
          return 'busy'
        }
        if (command.action === 'apply_patch') {
          return runApplyPatchCommand(command.game_uuid, command.version_uuid)
        }
        if (command.action === 'apply_mod_pack') {
          return runApplyModPackCommand(command.game_uuid)
        }
        return runGameAction(command.action, command.game_uuid, {
          kind: command.kind,
          versionUuid: command.version_uuid,
        })
      },
    })
    // Server lifecycle is optional; catalog authority comes from identity and ACL-filtered search.
    await pullLifecycleRegistryFromServer(connectionAuth, registry)
    if (!current()) return
    await syncLifecycleRegistryToServer(
      connectionAuth,
      registry.snapshot().filter((row) => libraryGames.some((game) => game.uuid === row.gameUuid)),
    )
  } catch (error) {
    if (current()) displayConnectionFailure(error)
  } finally {
    if (current()) els.connectBtn.disabled = false
  }
}
/** Clear local profile metadata/credentials; installed files and running games remain OS-owned. */
async function forgetAccount(): Promise<void> {
  if (busyGames.size > 0) {
    setStatus('Finish or cancel the active local operation before forgetting the account.', 'info')
    return
  }
  const epoch = ++connectionEpoch
  stopAllLaunchWatchers()
  heartbeatScheduler?.stop()
  heartbeatScheduler = null
  auth = createAuthStore()
  sessionActive = false
  verifiedAccountId = ''
  libraryGames = []
  localInstalls = {}
  gamesWithEnabledMods = new Set()
  gameActivity.clear()
  lastPlayedGameUuid = null
  els.baseUrl.value = ''
  els.token.value = ''
  els.connectBtn.disabled = true
  setConnectionMode('disconnected')
  renderAuthSummary()
  renderLibrary()
  const problems: string[] = []
  try {
    clearOfflineInstalledShelf()
  } catch {
    problems.push('cached titles')
  }
  await queueProfileWrite(async () => {
    try {
      await saveStoredConfig({ baseUrl: '', token: null })
    } catch {
      problems.push('saved server URL')
    }
    try {
      await keychainAdapter.clear()
    } catch {
      problems.push('OS credential store')
    }
  })
  if (epoch !== connectionEpoch) return
  setStatus(
    problems.length
      ? `Could not fully forget this account: ${problems.join(', ')}. Retry after checking local access. The visible profile was cleared; game files and saves remain.`
      : 'Account and cached titles forgotten on this device. Game files and saves remain; running games are unchanged. Site sign-ins in other windows and the server token are separate.',
    problems.length ? 'error' : 'info',
  )
  els.connectBtn.disabled = false
}

/** The game most recently launched from this seat — the overlay's subject (INSP-45). */
let lastPlayedGameUuid: string | null = null

async function runPlayAction(uuid: string): Promise<void> {
  if (!lifecycle || busyGames.has(uuid)) {
    return
  }
  busyGames.add(uuid)
  const api = createDesktopApi(auth)
  try {
    setGameActivity(uuid, 'Launching…')
    renderLibrary()
    const { pid, sessionId } = await kickoffLaunch(api, uuid)
    lastPlayedGameUuid = uuid
    setGameActivity(uuid, `Playing (pid ${pid})`)
    renderLibrary()
    setStatus(
      sessionId === null
        ? `Launched ${uuid}. Playtime tracking is unavailable.`
        : `Launched ${uuid}.`,
      'success',
    )
  } finally {
    busyGames.delete(uuid)
    renderLibrary()
  }
}

/** Reveal a path from a queued web command (library / unmatched) or local install. */
async function runOpenPathCommand(
  rawPath: string,
  options: { select?: boolean; allowedRoots?: string[] } = {},
): Promise<'ok' | 'busy' | 'error'> {
  let target = rawPath
  if (hasSavePlaceholder(rawPath)) {
    // INSP-1: a save-location template from the community manifest — expand
    // it for this PC, or say which placeholder this machine cannot fill.
    const expanded = await expandSavePath(rawPath, await tauriResolvers())
    if (!expanded.ok) {
      setStatus(
        `Cannot open that save folder here: ${expanded.missing} is not known on this PC.`,
        'error',
      )
      return 'error'
    }
    target = expanded.path
  }
  const result = await revealPathInOs(target, {
    select: options.select,
    allowedRoots: options.allowedRoots,
  })
  if (!result.ok) {
    setStatus(result.error, 'error')
    return 'error'
  }
  setStatus(`Opened in file manager: ${result.path}`, 'success')
  return 'ok'
}

async function runRevealInstallAction(uuid: string): Promise<void> {
  try {
    const installs = await loadInstallsFromDisk()
    const extractPath = installs[uuid]?.extractPath
    if (!extractPath) {
      setStatus('No local install path to open.', 'error')
      return
    }
    let allowedRoots: string[] | undefined
    try {
      allowedRoots = [await getInstallsDir()]
    } catch {
      allowedRoots = undefined
    }
    await runOpenPathCommand(extractPath, { select: false, allowedRoots })
  } catch (error) {
    setStatus(formatDesktopApiError(error), 'error')
  }
}
async function runApplyPatchCommand(
  uuid: string,
  versionUuid?: string,
): Promise<'ok' | 'busy' | 'error'> {
  if (busyGames.has(uuid)) {
    return 'busy'
  }
  if (isActionBlockedOffline('apply_patch', connectionMode)) {
    setStatus(offlineBlockReason('apply_patch'), 'error')
    return 'busy'
  }
  if (!versionUuid) {
    setStatus('apply_patch requires a patch version', 'error')
    return 'error'
  }
  busyGames.add(uuid)
  let outcome: 'ok' | 'busy' | 'error' = 'ok'
  try {
    setGameActivity(uuid, 'Staging translation patch…')
    const authHeader = auth.authorizationHeader()
    const staged = await stagePatchFile({
      gameUuid: uuid,
      patchUuid: versionUuid,
      apiBase: auth.getBaseUrl() || undefined,
      authHeader: authHeader || undefined,
      filename: `${versionUuid}.bps`,
    })
    if (!staged.ok) {
      throw new Error(staged.error)
    }
    // Prefer a locally downloaded archive as the ROM source when present.
    const downloadsDir = await (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        return await invoke<string>('get_app_subdir', { subdir: 'downloads' })
      } catch {
        return ''
      }
    })()
    const romPath = downloadsDir
      ? `${downloadsDir.replace(/[/\\]+$/, '')}/${buildLocalArchiveName(uuid)}`
      : ''
    if (!romPath) {
      throw new Error(
        'No local ROM archive found. Download the base game in the companion first, then retry — or apply with Flips manually.',
      )
    }
    setGameActivity(uuid, 'Applying patch with Flips…')
    const applied = await kickoffApplyPatch({
      gameUuid: uuid,
      patchPath: staged.path,
      romPath,
    })
    if (!applied.ok) {
      throw new Error(applied.error)
    }
    setStatus(`Patched ROM written to ${applied.outputPath}`, 'success')
  } catch (error) {
    outcome = 'error'
    const message = formatDesktopApiError(error)
    setGameActivity(uuid, `Error: ${message}`)
    setStatus(message, 'error')
  } finally {
    busyGames.delete(uuid)
    if (outcome === 'ok') {
      setGameActivity(uuid, '')
    }
    renderLibrary()
  }
  return outcome
}
async function runApplyModPackCommand(uuid: string): Promise<'ok' | 'busy' | 'error'> {
  if (busyGames.has(uuid)) {
    return 'busy'
  }
  if (isActionBlockedOffline('apply_mods', connectionMode)) {
    setStatus(offlineBlockReason('apply_mods'), 'error')
    return 'busy'
  }
  busyGames.add(uuid)
  let outcome: 'ok' | 'busy' | 'error' = 'ok'
  try {
    setGameActivity(uuid, 'Fetching enabled mods…')
    renderLibrary()
    const applied = await kickoffApplyModPack(auth, uuid)
    if (!applied.ok) {
      throw new Error(applied.error)
    }
    setStatus(
      `Applied ${applied.appliedMods} mod pack(s) (${applied.filesApplied} file(s)) for ${uuid}${
        applied.profileName ? ` — profile ${applied.profileName}` : ''
      }.${applied.loaderHint ? ` ${applied.loaderHint}` : ''} WebRetro cannot load PC mods.`,
      'success',
    )
  } catch (error) {
    outcome = 'error'
    const message = formatDesktopApiError(error)
    setGameActivity(uuid, `Error: ${message}`)
    setStatus(message, 'error')
  } finally {
    busyGames.delete(uuid)
    if (outcome === 'ok') {
      setGameActivity(uuid, '')
    }
    renderLibrary()
  }
  return outcome
}
async function runApplyModPackAction(uuid: string): Promise<void> {
  if (!lifecycle || busyGames.has(uuid)) {
    return
  }
  await runApplyModPackCommand(uuid)
}
async function runGameAction(
  action: LifecycleAction,
  uuid: string,
  options: { kind?: 'base' | 'update' | 'extra'; versionUuid?: string } = {},
): Promise<'ok' | 'busy' | 'error'> {
  const registry = lifecycle
  if (!registry) {
    return 'error'
  }
  if (busyGames.has(uuid)) {
    return 'busy'
  }
  if (isActionBlockedOffline(action, connectionMode)) {
    setStatus(offlineBlockReason(action), 'error')
    return 'busy'
  }
  busyGames.add(uuid)
  const operationAuth = auth
  const operationEpoch = connectionEpoch
  const api = createDesktopApi(operationAuth)
  let outcome: 'ok' | 'busy' | 'error' = 'ok'
  try {
    if (action === 'download') {
      setGameActivity(uuid, 'Downloading…')
      const versionChoice = options.kind
        ? { kind: options.kind, versionUuid: options.versionUuid }
        : await pickDownloadVersion(api, uuid)
      if (versionChoice === null) {
        setStatus('Download canceled.', 'info')
        return 'ok'
      }
      await kickoffDownload(api, operationAuth, registry, uuid, {
        kind: versionChoice.kind,
        versionUuid: versionChoice.versionUuid,
        onProgress: ({ bytesReceived, totalBytes }) => {
          if (totalBytes) {
            const percent = Math.round((bytesReceived / totalBytes) * 100)
            setGameActivity(uuid, `Downloading… ${percent}%`)
          } else {
            setGameActivity(uuid, `Downloading… ${bytesReceived} bytes`)
          }
        },
      })
      setStatus(`Downloaded ${uuid}.`, 'success')
    } else if (action === 'install') {
      const operationId = crypto.randomUUID()
      archiveInstallOperations.set(uuid, operationId)
      setGameActivity(uuid, 'Extracting… 0%')
      renderLibrary()
      await kickoffInstall(registry, uuid, {
        operationId,
        onProgress: ({ bytes_extracted, total_bytes }) => {
          const percent =
            total_bytes > 0 ? Math.min(100, Math.round((bytes_extracted / total_bytes) * 100)) : 100
          setGameActivity(uuid, `Extracting… ${percent}%`)
        },
      })
      setStatus(`Installed ${uuid}.`, 'success')
    } else if (action === 'update') {
      setGameActivity(uuid, 'Updating…')
      await kickoffUpdate(api, operationAuth, registry, uuid, {
        kind: options.kind,
        versionUuid: options.versionUuid,
        onProgress: ({ bytesReceived, totalBytes }) => {
          if (totalBytes) {
            const percent = Math.round((bytesReceived / totalBytes) * 100)
            setGameActivity(uuid, `Updating… ${percent}%`)
          } else {
            setGameActivity(uuid, `Updating… ${bytesReceived} bytes`)
          }
        },
      })
      setStatus(`Updated ${uuid}.`, 'success')
    } else if (action === 'uninstall') {
      setGameActivity(uuid, 'Removing local files…')
      await kickoffUninstall(registry, uuid)
      setStatus(`Uninstalled ${uuid}.`, 'success')
    }
  } catch (error) {
    outcome = 'error'
    const message = formatDesktopApiError(error)
    if (action === 'install' && message.toLowerCase().includes('extraction canceled')) {
      setGameActivity(uuid, 'Install canceled; previous files are unchanged.')
      setStatus('Install canceled; the previous install was preserved.', 'info')
    } else {
      setGameActivity(uuid, `Error: ${message}`)
      setStatus(message, 'error')
    }
  } finally {
    busyGames.delete(uuid)
    archiveInstallOperations.delete(uuid)
    try {
      localInstalls = await loadInstallsFromDisk()
    } catch {
      // Keep the last known local install index; failed reads do not promote titles.
    }
    if (outcome === 'ok') {
      setGameActivity(uuid, '')
    }
    if (operationEpoch === connectionEpoch && connectionMode === 'online') {
      await syncLifecycleRegistryToServer(
        operationAuth,
        registry
          .snapshot()
          .filter((row) => libraryGames.some((game) => game.uuid === row.gameUuid)),
      )
    }
    renderLibrary()
  }
  return outcome
}
function handleLibraryClick(event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLButtonElement)) {
    return
  }
  const action = target.dataset.action
  const uuid = target.dataset.uuid
  if (!action || !uuid || !lifecycle) {
    return
  }
  if (action === 'reveal_path') {
    void runRevealInstallAction(uuid)
    return
  }
  if (action === 'cancel_install') {
    const operationId = archiveInstallOperations.get(uuid)
    if (operationId) {
      void cancelInstallArchive(operationId)
        .then((cancelled) => {
          if (cancelled) setGameActivity(uuid, 'Canceling extraction…')
        })
        .catch((error) => {
          setStatus(formatDesktopApiError(error), 'error')
        })
    }
    return
  }
  if (action === 'play') {
    void (async () => {
      try {
        await runPlayAction(uuid)
      } catch (error) {
        const message = formatDesktopApiError(error)
        setGameActivity(uuid, `Error: ${message}`)
        renderLibrary()
        setStatus(message, 'error')
      }
    })()
    return
  }
  if (action === 'apply_mods') {
    void (async () => {
      try {
        await runApplyModPackAction(uuid)
      } catch (error) {
        const message = formatDesktopApiError(error)
        setGameActivity(uuid, `Error: ${message}`)
        renderLibrary()
        setStatus(message, 'error')
      }
    })()
    return
  }
  if (
    action !== 'download' &&
    action !== 'install' &&
    action !== 'update' &&
    action !== 'uninstall'
  ) {
    return
  }
  void (async () => {
    try {
      await runGameAction(action, uuid)
    } catch (error) {
      const message = formatDesktopApiError(error)
      setGameActivity(uuid, `Error: ${message}`)
      renderLibrary()
      setStatus(message, 'error')
    }
  })()
}
function bindElements(root: HTMLElement): void {
  els = {
    baseUrl: root.querySelector('#base-url')!,
    token: root.querySelector('#token')!,
    connectBtn: root.querySelector('#connect-btn')!,
    status: root.querySelector('#status')!,
    authSummary: root.querySelector('#auth-summary')!,
    library: root.querySelector('#library')!,
    lifecyclePanel: root.querySelector('#lifecycle-panel')!,
  }
}
/**
 * The "Trusted network shares" editor. The list is stored and enforced by the
 * native side; this only reads it into the box and sends edits back, showing the
 * native validation message (which names the entry that is not `\\server\share`).
 */
function bindTrustedShares(root: HTMLElement): void {
  const box = root.querySelector<HTMLTextAreaElement>('#trusted-shares')!
  const status = root.querySelector<HTMLElement>('#trusted-shares-status')!
  const saveBtn = root.querySelector<HTMLButtonElement>('#trusted-shares-save')!
  const show = (message: string, tone: 'info' | 'error' | 'success') => {
    if (status.textContent !== message) {
      status.textContent = message
    }
    status.dataset.tone = tone
  }
  void loadTrustedShares()
    .then((roots) => {
      box.value = formatTrustedShares(roots)
    })
    .catch((error) => {
      show(error instanceof Error ? error.message : String(error), 'error')
    })
  saveBtn.addEventListener('click', () => {
    saveBtn.disabled = true
    void saveTrustedShares(parseTrustedShares(box.value))
      .then((stored) => {
        box.value = formatTrustedShares(stored)
        show(
          stored.length
            ? `Saved ${stored.length} trusted network share${stored.length === 1 ? '' : 's'}.`
            : 'Saved. No network shares are trusted.',
          'success',
        )
      })
      .catch((error) => {
        show(error instanceof Error ? error.message : String(error), 'error')
      })
      .finally(() => {
        saveBtn.disabled = false
      })
  })
}
export async function mountApp(root: HTMLElement): Promise<void> {
  root.innerHTML = `
    <main class="shell">
      <header>
        <h1>Oneirodex Desktop</h1>
        <p class="muted">Connect to your server, preview library, and track local install state.</p>
      </header>
      <section class="panel">
        <h2>Connection</h2>
        <p id="auth-summary" class="muted"></p>
        <form id="connect-form" class="connect-form">
          <label>
            Server URL
            <input id="base-url" name="baseUrl" type="url" placeholder="https://oneirodex.example.com" autocomplete="url" />
          </label>
          <label>
            API token
            <input id="token" name="token" type="password" placeholder="gt_… (paste from Account → API tokens)" autocomplete="off" />
          </label>
          <button id="connect-btn" type="submit" class="primary">Connect</button>
          <button id="forget-account-btn" type="button" class="secondary">Forget account and cached titles</button>
          <button id="open-library-btn" type="button" class="secondary">Open full library</button>
          <button id="friends-btn" type="button" class="secondary">Open friends window</button>
        </form>
        <p class="muted">To switch accounts, enter the new server and token, then Connect. Forget removes this device’s saved credentials and cached titles; game files and saves stay on disk. Library and Friends windows have separate site sign-ins.</p>
        <p id="status" class="status" data-tone="info" role="status" aria-live="polite" aria-atomic="true"></p>
      </section>
      <section class="panel">
        <h2>Trusted network shares</h2>
        <p class="muted">Network folders that Show in Explorer may open when your server asks for them, one per line (for example the library root of a Windows-hosted server). Opening a network path makes Windows sign in to that computer, so a share is never opened unless it is listed here.</p>
        <label>
          Shares
          <textarea id="trusted-shares" rows="3" spellcheck="false" autocomplete="off" placeholder="&#92;&#92;nas&#92;roms"></textarea>
        </label>
        <button id="trusted-shares-save" type="button" class="secondary">Save shares</button>
        <p id="trusted-shares-status" class="status" data-tone="info" role="status" aria-live="polite" aria-atomic="true"></p>
      </section>
      <section class="panel">
        <h2>Library preview</h2>
        <div id="library"></div>
      </section>
      <section class="panel">
        <h2>Lifecycle registry</h2>
        <div id="lifecycle-panel"></div>
      </section>
    </main>
  `
  bindElements(root)
  root.querySelector('#connect-form')!.addEventListener('submit', (event) => {
    event.preventDefault()
    void handleConnect()
  })
  root.querySelector('#forget-account-btn')!.addEventListener('click', () => {
    void forgetAccount()
  })
  root.querySelector('#friends-btn')!.addEventListener('click', () => {
    // Prefer the visible Server URL field — Friends must not require Connect,
    // and must not keep a stale auth base after the user edits the form.
    const base = normalizeBaseUrl(resolveFriendsBaseUrl(els.baseUrl.value, auth.getBaseUrl()))
    const blocked = friendsOpenBlockedReason(base)
    if (blocked) {
      console.warn('[friends]', blocked)
      setStatus(blocked, 'error')
      return
    }
    // The Friends window signs in with the site account — same plain-http rule.
    const serverCheck = checkServerUrl(base)
    if (!serverCheck.ok) {
      setStatus(serverCheck.message, 'error')
      return
    }
    void openSocialCompanionWindow(base, lastPlayedGameUuid)
      .then((how) => {
        const { message, tone } = friendsOpenStatus(how, connectionMode)
        setStatus(message, tone)
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : 'Could not open Friends window'
        console.error('[friends]', message, err)
        setStatus(message, 'error')
      })
  })
  root.querySelector('#open-library-btn')!.addEventListener('click', () => {
    const base = normalizeBaseUrl(els.baseUrl.value)
    if (!base) {
      setStatus('Enter a Server URL before opening the full library.', 'error')
      return
    }
    const serverCheck = checkServerUrl(base)
    if (!serverCheck.ok) {
      setStatus(serverCheck.message, 'error')
      return
    }
    void openFullLibraryWindow(base)
      .then((how) => {
        setStatus(
          how === 'focused'
            ? 'Full library window focused.'
            : 'Full library opened — sign in if prompted.',
          'info',
        )
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : 'Could not open full library'
        console.error('[library]', message, error)
        setStatus(message, 'error')
      })
  })
  bindTrustedShares(root)
  els.library.addEventListener('click', handleLibraryClick)
  els.lifecyclePanel.addEventListener('click', handleLibraryClick)
  await ensureLifecycleRegistry()
  await hydrateFromDisk()
  try {
    localInstalls = await loadInstallsFromDisk()
    const token = auth.getToken()
    if (token) {
      const shelf = await loadVerifiedOfflineShelf(auth.getBaseUrl(), token)
      libraryGames = shelf?.games ?? []
      localInstalls = shelf?.installs ?? {}
      verifiedAccountId = shelf?.accountId ?? ''
      if (libraryGames.length > 0) {
        sessionActive = true
        setConnectionMode('offline')
        setStatus(
          'Offline Installed shelf loaded from this previously verified account and device.',
          'info',
        )
      }
    }
  } catch {
    localInstalls = {}
  }
  renderLibrary()
  // Keep a hydrate failure (refused saved URL, keyring error) on screen.
  if (els.status.dataset.tone !== 'error' && !sessionActive) {
    setStatus('Enter credentials and click Connect.', 'info')
  }
}
