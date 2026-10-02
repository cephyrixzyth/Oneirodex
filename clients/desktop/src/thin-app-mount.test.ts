/**
 * What the thin client shows on start-up. The window is built by `mountThinApp`
 * from a template string, so these run it against a stub root that records what
 * is written to the status line — enough to check the user is told, without a DOM.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tauri-apps/api/webviewWindow', () => ({
  WebviewWindow: class {
    static getByLabel = vi.fn()
    once = vi.fn()
  },
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: vi.fn(() => false),
  loadStoredConfig: vi.fn(),
  saveStoredConfig: vi.fn(async () => undefined),
}))

vi.mock('./keychain.js', () => ({
  keychainAdapter: {
    load: vi.fn(async () => null),
    save: vi.fn(async () => undefined),
    clear: vi.fn(async () => undefined),
  },
}))

vi.mock('./heartbeat.js', () => ({
  startClientHeartbeat: vi.fn(() => ({ stop: vi.fn() })),
}))

import { loadStoredConfig } from './config-store.js'
import { startClientHeartbeat } from './heartbeat.js'
import { keychainAdapter } from './keychain.js'

const { mountThinApp } = await import('./thin-app.js')

interface StubElement {
  value: string
  textContent: string
  dataset: Record<string, string>
  addEventListener: ReturnType<typeof vi.fn>
}

function stubRoot() {
  const elements = new Map<string, StubElement>()
  const el = (selector: string): StubElement => {
    let found = elements.get(selector)
    if (!found) {
      found = { value: '', textContent: '', dataset: {}, addEventListener: vi.fn() }
      elements.set(selector, found)
    }
    return found
  }
  const root = { innerHTML: '', querySelector: (selector: string) => el(selector) }
  return { root: root as unknown as HTMLElement, el }
}

describe('thin client start-up', () => {
  beforeEach(() => {
    vi.mocked(loadStoredConfig).mockReset()
    vi.mocked(startClientHeartbeat).mockClear()
    vi.mocked(keychainAdapter.load).mockReset().mockResolvedValue(null)
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  })

  it('tells the user when a saved server URL is refused now, instead of going quiet', async () => {
    // Saved by an older build; plain http:// to a public host is refused today.
    vi.mocked(loadStoredConfig).mockResolvedValue({
      baseUrl: 'http://games.example.com',
      token: null,
    })
    vi.mocked(keychainAdapter.load).mockResolvedValue('gt_abcd_secretsecretsecret')
    const { root, el } = stubRoot()

    await mountThinApp(root)

    // The URL stays in the box so it can be corrected, with the reason beside it.
    expect(el('#baseUrl').value).toBe('http://games.example.com')
    expect(el('#status').textContent).toMatch(/Refusing http:\/\/ for games\.example\.com/)
    expect(el('#status').dataset.tone).toBe('error')
    // And presence never started: nothing carried the token to that host.
    expect(startClientHeartbeat).not.toHaveBeenCalled()
  })

  it.each([
    'http://tower.lan:5006',
    'http://nas.home.arpa',
    'http://100.101.102.103:5006',
    'https://games.example.com',
  ])('stays quiet and reports presence for the saved URL %s', async (baseUrl) => {
    vi.mocked(loadStoredConfig).mockResolvedValue({ baseUrl, token: null })
    vi.mocked(keychainAdapter.load).mockResolvedValue('gt_abcd_secretsecretsecret')
    const { root, el } = stubRoot()

    await mountThinApp(root)

    expect(el('#status').dataset.tone).not.toBe('error')
    expect(startClientHeartbeat).toHaveBeenCalledTimes(1)
    expect(vi.mocked(startClientHeartbeat).mock.calls[0]![1]).toMatchObject({ deviceKind: 'thin' })
  })

  it('shows no error for a first run with nothing saved', async () => {
    vi.mocked(loadStoredConfig).mockResolvedValue({ baseUrl: '', token: null })
    const { root, el } = stubRoot()

    await mountThinApp(root)

    expect(el('#status').dataset.tone).not.toBe('error')
    expect(startClientHeartbeat).not.toHaveBeenCalled()
  })
})
