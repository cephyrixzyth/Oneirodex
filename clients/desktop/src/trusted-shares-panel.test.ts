/**
 * The "Trusted network shares" editor in the full companion window (`bindTrustedShares`
 * in app.ts). `trusted-shares.test.ts` covers the invoke wrapper and the text
 * helpers; these drive the panel itself - load into the box, Save, the canonical
 * list written back, the error tone and the button coming back - against a stub
 * root, since the window is built from a template string. A regression here would
 * leave a user with no way to trust a share, so nothing else would tell them.
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
  loadStoredConfig: vi.fn(async () => ({ baseUrl: '', token: null })),
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

// Keep the real list parser / formatter; only the two native calls are stubbed.
vi.mock('./trusted-shares.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./trusted-shares.js')>()
  return { ...actual, loadTrustedShares: vi.fn(), saveTrustedShares: vi.fn() }
})

import { loadTrustedShares, saveTrustedShares } from './trusted-shares.js'

const { mountApp } = await import('./app.js')

interface StubElement {
  value: string
  textContent: string
  innerHTML: string
  disabled: boolean
  dataset: Record<string, string>
  addEventListener: ReturnType<typeof vi.fn>
}

function stubRoot() {
  const elements = new Map<string, StubElement>()
  const el = (selector: string): StubElement => {
    let found = elements.get(selector)
    if (!found) {
      found = {
        value: '',
        textContent: '',
        innerHTML: '',
        disabled: false,
        dataset: {},
        addEventListener: vi.fn(),
      }
      elements.set(selector, found)
    }
    return found
  }
  const root = { innerHTML: '', querySelector: (selector: string) => el(selector) }
  return { root: root as unknown as HTMLElement, el }
}

/** Mount the window and hand back the three editor controls plus a way to press Save. */
async function mountEditor() {
  const { root, el } = stubRoot()
  await mountApp(root)
  const box = el('#trusted-shares')
  const status = el('#trusted-shares-status')
  const saveBtn = el('#trusted-shares-save')
  const clickSave = () => {
    const click = saveBtn.addEventListener.mock.calls.find(([type]) => type === 'click')?.[1]
    expect(click, 'Save has a click handler').toBeTypeOf('function')
    click()
  }
  return { root, box, status, saveBtn, clickSave }
}

/** A promise a test settles by hand, so the in-flight state can be looked at. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('Trusted network shares editor', () => {
  beforeEach(() => {
    vi.mocked(loadTrustedShares).mockReset().mockResolvedValue([])
    vi.mocked(saveTrustedShares).mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  })

  it('is part of the window and starts from the saved list', async () => {
    vi.mocked(loadTrustedShares).mockResolvedValue(['\\\\nas\\roms', '\\\\nas\\archive'])
    const { root, box, status } = await mountEditor()

    expect((root as unknown as { innerHTML: string }).innerHTML).toContain('id="trusted-shares"')
    // One share per line, exactly what the native side stored.
    await vi.waitFor(() => expect(box.value).toBe('\\\\nas\\roms\n\\\\nas\\archive'))
    expect(loadTrustedShares).toHaveBeenCalledTimes(1)
    expect(status.textContent).toBe('')
  })

  it('leaves the box empty when nothing is trusted yet', async () => {
    const { box, status } = await mountEditor()
    await vi.waitFor(() => expect(loadTrustedShares).toHaveBeenCalled())
    expect(box.value).toBe('')
    expect(status.textContent).toBe('')
    expect(status.dataset.tone).not.toBe('error')
  })

  it.each([
    ['an Error', new Error('trusted_shares.json is locked'), 'trusted_shares.json is locked'],
    ['a bare string', 'could not read the list', 'could not read the list'],
  ])('shows why the list could not be loaded when it rejects with %s', async (_, reason, text) => {
    vi.mocked(loadTrustedShares).mockRejectedValue(reason)
    const { status } = await mountEditor()
    await vi.waitFor(() => expect(status.textContent).toBe(text))
    expect(status.dataset.tone).toBe('error')
  })

  it('saves what was typed, one share per line, and shows the canonical form back', async () => {
    const { box, status, saveBtn, clickSave } = await mountEditor()
    const saved = deferred<string[]>()
    vi.mocked(saveTrustedShares).mockReturnValue(saved.promise)
    // Forward slashes, a trailing separator, blank lines and padding - as pasted.
    box.value = '//nas/roms/\n\n   \\\\NAS\\Archive  \r\n'

    clickSave()

    expect(saveTrustedShares).toHaveBeenCalledWith(['//nas/roms/', '\\\\NAS\\Archive'])
    // Pressed once, the button cannot be pressed again until the save settles.
    expect(saveBtn.disabled).toBe(true)

    saved.resolve(['\\\\nas\\roms', '\\\\NAS\\Archive'])
    await vi.waitFor(() => expect(saveBtn.disabled).toBe(false))
    // The box now shows what the native side stored, not what was typed.
    expect(box.value).toBe('\\\\nas\\roms\n\\\\NAS\\Archive')
    expect(status.textContent).toBe('Saved 2 trusted network shares.')
    expect(status.dataset.tone).toBe('success')
  })

  it('says so, in the singular, for one share, and when the list is cleared', async () => {
    const { box, status, clickSave, saveBtn } = await mountEditor()

    vi.mocked(saveTrustedShares).mockResolvedValueOnce(['\\\\nas\\roms'])
    box.value = '\\\\nas\\roms'
    clickSave()
    await vi.waitFor(() => expect(status.textContent).toBe('Saved 1 trusted network share.'))
    await vi.waitFor(() => expect(saveBtn.disabled).toBe(false))

    vi.mocked(saveTrustedShares).mockResolvedValueOnce([])
    box.value = '  \n'
    clickSave()
    expect(saveTrustedShares).toHaveBeenLastCalledWith([])
    await vi.waitFor(() => expect(status.textContent).toBe('Saved. No network shares are trusted.'))
    expect(status.dataset.tone).toBe('success')
    expect(box.value).toBe('')
  })

  it('shows the refusal in the error tone, keeps what was typed and gives the button back', async () => {
    const { box, status, saveBtn, clickSave } = await mountEditor()
    const refused = deferred<string[]>()
    vi.mocked(saveTrustedShares).mockReturnValue(refused.promise)
    box.value = 'C:\\Games\n\\\\nas\\roms'

    clickSave()
    expect(saveBtn.disabled).toBe(true)

    // `saveTrustedShares` rethrows the native message as an Error naming the entry.
    refused.reject(
      new Error('C:\\Games is not a network share path. Use the form \\\\server\\share'),
    )
    await vi.waitFor(() => expect(saveBtn.disabled).toBe(false))
    expect(status.textContent).toBe(
      'C:\\Games is not a network share path. Use the form \\\\server\\share',
    )
    expect(status.dataset.tone).toBe('error')
    // The text stays put so the bad line can be fixed rather than retyped.
    expect(box.value).toBe('C:\\Games\n\\\\nas\\roms')
  })

  it('gives the button back after a rejection that is not an Error, and a retry can succeed', async () => {
    const { box, status, saveBtn, clickSave } = await mountEditor()
    vi.mocked(saveTrustedShares).mockRejectedValueOnce('disk full')
    box.value = '\\\\nas\\roms'

    clickSave()
    await vi.waitFor(() => expect(status.textContent).toBe('disk full'))
    await vi.waitFor(() => expect(saveBtn.disabled).toBe(false))
    expect(status.dataset.tone).toBe('error')

    vi.mocked(saveTrustedShares).mockResolvedValueOnce(['\\\\nas\\roms'])
    clickSave()
    await vi.waitFor(() => expect(status.dataset.tone).toBe('success'))
    expect(status.textContent).toBe('Saved 1 trusted network share.')
    await vi.waitFor(() => expect(saveBtn.disabled).toBe(false))
  })
})
