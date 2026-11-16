import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  isTauriRuntime: vi.fn(() => false),
  getByLabel: vi.fn(),
  constructed: vi.fn(),
}))

vi.mock('@tauri-apps/api/webviewWindow', () => ({
  WebviewWindow: class {
    static getByLabel = mocks.getByLabel

    show = vi.fn(async () => undefined)
    setFocus = vi.fn(async () => undefined)
    close = vi.fn(async () => undefined)

    constructor(label: string, options: unknown) {
      mocks.constructed(label, options)
    }

    once(event: string, callback: (payload?: unknown) => void) {
      if (event === 'tauri://created') queueMicrotask(() => callback())
      return this
    }
  },
}))

vi.mock('./config-store.js', () => ({ isTauriRuntime: mocks.isTauriRuntime }))

const { buildFullLibraryUrl, openFullLibraryWindow, resetFullLibraryWindowForTests } =
  await import('./library-window.js')

describe('full library handoff', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    mocks.isTauriRuntime.mockReset().mockReturnValue(false)
    mocks.getByLabel.mockReset().mockResolvedValue(null)
    mocks.constructed.mockReset()
    resetFullLibraryWindowForTests()
  })

  it('targets the catalog route and includes no companion credential', () => {
    expect(buildFullLibraryUrl('https://games.example.com/')).toBe(
      'https://games.example.com/library',
    )
    expect(buildFullLibraryUrl('   ')).toBe('')
  })

  it('opens the full catalog in a browser when running outside Tauri', async () => {
    const open = vi.fn()
    vi.stubGlobal('window', { open })

    await expect(openFullLibraryWindow('https://games.example.com')).resolves.toBe('browser')

    expect(open).toHaveBeenCalledWith(
      'https://games.example.com/library',
      'od-full-library',
      'width=1280,height=800',
    )
  })

  it('creates a separate site-login window without placing the API token in its URL', async () => {
    mocks.isTauriRuntime.mockReturnValue(true)

    await expect(openFullLibraryWindow('https://games.example.com')).resolves.toBe('opened')

    expect(mocks.constructed).toHaveBeenCalledWith(
      'full-library',
      expect.objectContaining({
        url: 'https://games.example.com/library',
        title: 'Oneirodex Library',
      }),
    )
  })

  it('recreates the site window when the selected server changes', async () => {
    mocks.isTauriRuntime.mockReturnValue(true)
    const existing = {
      close: vi.fn(async () => undefined),
      show: vi.fn(async () => undefined),
      setFocus: vi.fn(async () => undefined),
    }
    mocks.getByLabel.mockResolvedValueOnce(null).mockResolvedValueOnce(existing)

    await openFullLibraryWindow('https://first.example.com')
    await expect(openFullLibraryWindow('https://second.example.com')).resolves.toBe('opened')

    expect(existing.close).toHaveBeenCalledOnce()
    expect(mocks.constructed).toHaveBeenLastCalledWith(
      'full-library',
      expect.objectContaining({ url: 'https://second.example.com/library' }),
    )
  })

  it('requires a server URL', async () => {
    await expect(openFullLibraryWindow('  ')).rejects.toThrow('Set Server URL first.')
  })
})
