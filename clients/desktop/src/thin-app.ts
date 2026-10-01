import { WebviewWindow } from '@tauri-apps/api/webviewWindow'

import {
  createAuthStore,
  describeTokenPaste,
  isOneirodexToken,
  normalizeBaseUrl,
  normalizeOneirodexToken,
} from './auth.js'
import { createDesktopApi } from './api.js'
import { isTauriRuntime, loadStoredConfig, saveStoredConfig } from './config-store.js'
import {
  formatKeychainError,
  logCompanion,
  shapeInvalidConnectionResult,
  validateConnection,
} from './connect.js'
import { startClientHeartbeat, type HeartbeatScheduler } from './heartbeat.js'
import { keychainAdapter } from './keychain.js'
import { joinUrl } from './paths.js'
import { openSocialCompanionWindow } from './social-window.js'
import { checkServerUrl } from './transport-policy.js'

const LIBRARY_LABEL = 'library'

let thinPresence: HeartbeatScheduler | undefined

/**
 * Register this seat as `device_kind=thin`.
 *
 * Without it a thin seat never appears in the Ops device list at all — it holds
 * a token, opens webviews, and is invisible to the operator, which defeats the
 * one thing `device_kind` was added for (TC-1). Presence needs the optional thin
 * token (`write:presence`); with no token there is nothing to authenticate with
 * and the webviews fall back to site login, so we simply stay quiet.
 *
 * Install commands are never delivered here: the server gates that on
 * `device_kind == companion` *and* a download/lifecycle scope, and the thin
 * preset has neither. No `onCommands` handler is wired for the same reason.
 */
function startThinPresence(baseUrl: string, token: string): void {
  thinPresence?.stop()
  thinPresence = undefined
  if (!baseUrl || !token) {
    return
  }
  let auth: ReturnType<typeof createAuthStore>
  try {
    auth = createAuthStore({ baseUrl, token })
  } catch (error) {
    // Saved by an older build, refused now (plain http:// to a public host): stay
    // quiet rather than send the token there. Save / Validate show the reason.
    logCompanion(
      'thin',
      `presence skipped: ${error instanceof Error ? error.message : String(error)}`,
    )
    return
  }
  thinPresence = startClientHeartbeat(auth, {
    deviceKind: 'thin',
    deviceName: 'Oneirodex Thin',
    onUnreachable: (error) => {
      logCompanion(
        'thin',
        `presence offline: ${error instanceof Error ? error.message : String(error)}`,
      )
    },
  })
}

/**
 * Library URL for the thin webview, marked as a thin seat.
 *
 * The SPA cannot otherwise tell it is inside the thin shell — it is a cookie
 * session in a plain webview, identical on the wire to a browser tab — so it
 * would keep offering Install / Update / Uninstall that this seat can never
 * complete. The marker is latched by `utils/seatMode.js` and survives in-app
 * navigation from there (TC-3).
 */
export function joinLibraryUrl(baseUrl: string): string {
  const base = baseUrl.trim()
  if (!base) {
    return ''
  }
  return `${joinUrl(base, '/')}?seat=thin`
}

async function openLibraryWindow(baseUrl: string): Promise<'opened' | 'focused' | 'browser'> {
  const url = joinLibraryUrl(baseUrl)
  if (!url) {
    throw new Error('Set Server URL first.')
  }
  if (!isTauriRuntime()) {
    window.open(url, 'od-thin-library', 'width=1280,height=800')
    return 'browser'
  }
  const existing = await WebviewWindow.getByLabel(LIBRARY_LABEL)
  if (existing) {
    await existing.show()
    await existing.setFocus()
    return 'focused'
  }
  const webview = new WebviewWindow(LIBRARY_LABEL, {
    url,
    title: 'Oneirodex Library',
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    resizable: true,
    focus: true,
  })
  await new Promise<void>((resolve, reject) => {
    webview.once('tauri://created', () => resolve())
    webview.once('tauri://error', (event) => {
      reject(
        new Error(
          String((event as { payload?: string }).payload || 'Failed to open library window'),
        ),
      )
    })
  })
  return 'opened'
}

/**
 * Thin client shell — connect-only. No download/install/launch.
 * Opens member SPA + Friends in least-privilege webviews.
 * Token normalize / shape / optional validate share the full companion path.
 */
export async function mountThinApp(root: HTMLElement): Promise<void> {
  root.innerHTML = `
    <header class="header">
      <h1>Oneirodex Thin</h1>
      <p class="tagline">Browse, social &amp; browser play — no local install pipeline</p>
    </header>
    <section class="connect panel">
      <label>Server URL <input id="baseUrl" type="url" placeholder="https://games.example.com" autocomplete="url" /></label>
      <p class="hint">Sign in with your site account inside the library / friends windows. API token optional for presence only.</p>
      <label>Thin API token (optional) <input id="token" type="password" placeholder="gt_… thin preset" autocomplete="off" /></label>
      <div class="actions">
        <button type="button" id="saveBtn">Save</button>
        <button type="button" id="validateBtn">Validate token</button>
        <button type="button" id="openLibraryBtn" class="primary">Open library</button>
        <button type="button" id="openFriendsBtn">Open friends</button>
      </div>
      <p id="status" class="status" data-tone="info">Enter your Oneirodex URL to begin.</p>
    </section>
    <section class="panel honesty">
      <h2>What this client does</h2>
      <ul>
        <li>Opens your household library in a dedicated window</li>
        <li>Friends popup (bottom-right, always-on-top)</li>
        <li>Uses thin device capabilities (no download / install / native play)</li>
        <li>With a token, reports presence as a <strong>thin</strong> seat so it shows up in Ops</li>
      </ul>
      <p class="hint">Need Install / Update / Play for PC titles? Use the full <strong>Oneirodex</strong> desktop companion.</p>
    </section>
  `

  const baseUrlEl = root.querySelector<HTMLInputElement>('#baseUrl')!
  const tokenEl = root.querySelector<HTMLInputElement>('#token')!
  const statusEl = root.querySelector<HTMLParagraphElement>('#status')!
  const setStatus = (message: string, tone: 'info' | 'error' | 'success' = 'info') => {
    statusEl.textContent = message
    statusEl.dataset.tone = tone
  }

  function readNormalizedToken(): string {
    const raw = tokenEl.value
    logCompanion('thin', describeTokenPaste(raw))
    const token = normalizeOneirodexToken(raw)
    tokenEl.value = token
    return token
  }

  async function persistThinConfig(baseUrl: string, token: string): Promise<void> {
    // Config JSON never stores the token; optional thin token lives in the OS keyring.
    await saveStoredConfig({ baseUrl, token: null })
    try {
      if (token) {
        await keychainAdapter.save(token)
      } else {
        await keychainAdapter.clear()
      }
    } catch (error) {
      throw new Error(formatKeychainError(error))
    }
    startThinPresence(baseUrl, token)
  }

  /**
   * Same normalize → shape → (optional) validateConnection path as full companion.
   * Empty token is allowed (site session in webviews).
   */
  async function prepareThinCredentials(options: {
    requireValidate: boolean
  }): Promise<{ baseUrl: string; token: string } | null> {
    const baseUrl = normalizeBaseUrl(baseUrlEl.value)
    baseUrlEl.value = baseUrl
    if (!baseUrl) {
      setStatus('Enter a server base URL.', 'error')
      return null
    }
    const serverCheck = checkServerUrl(baseUrl)
    if (!serverCheck.ok) {
      setStatus(serverCheck.message, 'error')
      return null
    }
    const token = readNormalizedToken()
    if (token && !isOneirodexToken(token)) {
      setStatus(shapeInvalidConnectionResult().message, 'error')
      return null
    }
    if (token && options.requireValidate) {
      const auth = createAuthStore({ baseUrl, token })
      const api = createDesktopApi(auth)
      const result = await validateConnection(api)
      if (!result.ok) {
        setStatus(result.message, 'error')
        return null
      }
    }
    return { baseUrl, token }
  }

  try {
    const stored = await loadStoredConfig()
    if (stored.baseUrl) baseUrlEl.value = stored.baseUrl
    const fromKeychain = await keychainAdapter.load()
    const token = stored.token || fromKeychain
    if (token) tokenEl.value = normalizeOneirodexToken(token)
    // Announce the seat on startup, not only after the next Save.
    if (stored.baseUrl && tokenEl.value) {
      startThinPresence(normalizeBaseUrl(stored.baseUrl), tokenEl.value)
    }
  } catch (error) {
    logCompanion(
      'thin',
      `hydrate failed: ${error instanceof Error ? error.message : String(error)}`,
    )
    // first run / keyring load noise
  }

  root.querySelector('#saveBtn')!.addEventListener('click', () => {
    void (async () => {
      try {
        const prepared = await prepareThinCredentials({ requireValidate: false })
        if (!prepared) return
        await persistThinConfig(prepared.baseUrl, prepared.token)
        setStatus(
          prepared.token
            ? 'Saved. Use Validate token to confirm the secret, or open library / friends.'
            : 'Saved. Open library or friends when ready.',
          'success',
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : String(err), 'error')
      }
    })()
  })

  root.querySelector('#validateBtn')!.addEventListener('click', () => {
    void (async () => {
      try {
        const prepared = await prepareThinCredentials({ requireValidate: true })
        if (!prepared) return
        if (!prepared.token) {
          setStatus(
            'Paste a thin API token to validate (optional for library/friends site login).',
            'error',
          )
          return
        }
        await persistThinConfig(prepared.baseUrl, prepared.token)
        setStatus(
          'Token validated against the server. Open library or friends when ready.',
          'success',
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : String(err), 'error')
      }
    })()
  })

  root.querySelector('#openLibraryBtn')!.addEventListener('click', () => {
    void (async () => {
      try {
        const prepared = await prepareThinCredentials({ requireValidate: false })
        if (!prepared) return
        await persistThinConfig(prepared.baseUrl, prepared.token)
        const result = await openLibraryWindow(prepared.baseUrl)
        setStatus(
          result === 'focused'
            ? 'Library window focused.'
            : 'Library window opened — sign in if prompted.',
          'success',
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : String(err), 'error')
      }
    })()
  })

  root.querySelector('#openFriendsBtn')!.addEventListener('click', () => {
    void (async () => {
      try {
        const prepared = await prepareThinCredentials({ requireValidate: false })
        if (!prepared) return
        await persistThinConfig(prepared.baseUrl, prepared.token)
        const result = await openSocialCompanionWindow(prepared.baseUrl)
        setStatus(
          result === 'focused'
            ? 'Friends window focused.'
            : 'Friends window opened — sign in if prompted.',
          'success',
        )
      } catch (err) {
        setStatus(err instanceof Error ? err.message : String(err), 'error')
      }
    })()
  })
}
