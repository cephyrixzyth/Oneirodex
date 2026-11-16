import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  openFullLibraryWindow: vi.fn(async () => 'opened' as const),
  loadStoredConfig: vi.fn(async () => ({
    baseUrl: 'https://saved.example.com',
    token: null,
  })),
  loadTrustedShares: vi.fn(async () => []),
  hydrateLifecycleRegistry: vi.fn(async () => ({ snapshot: () => [] })),
  loadInstallsFromDisk: vi.fn(async () => ({})),
  keychainLoad: vi.fn(async () => null),
}))

vi.mock('./library-window.js', () => ({
  openFullLibraryWindow: mocks.openFullLibraryWindow,
}))
vi.mock('./config-store.js', () => ({
  loadStoredConfig: mocks.loadStoredConfig,
  saveStoredConfig: vi.fn(async () => undefined),
  isTauriRuntime: vi.fn(() => false),
}))
vi.mock('./trusted-shares.js', () => ({
  formatTrustedShares: vi.fn(() => ''),
  loadTrustedShares: mocks.loadTrustedShares,
  parseTrustedShares: vi.fn(() => []),
  saveTrustedShares: vi.fn(async () => []),
}))
vi.mock('./lifecycle-store.js', () => ({
  hydrateLifecycleRegistry: mocks.hydrateLifecycleRegistry,
  pullLifecycleRegistryFromServer: vi.fn(),
  syncLifecycleRegistryToServer: vi.fn(),
}))
vi.mock('./install-store.js', () => ({ loadInstallsFromDisk: mocks.loadInstallsFromDisk }))
vi.mock('./keychain.js', () => ({
  keychainAdapter: {
    load: mocks.keychainLoad,
    save: vi.fn(async () => undefined),
    clear: vi.fn(async () => undefined),
  },
}))

const { mountApp } = await import('./app.js')

interface ElementStub {
  value: string
  textContent: string
  innerHTML: string
  disabled: boolean
  dataset: Record<string, string>
  addEventListener: ReturnType<typeof vi.fn>
  listeners: Map<string, (event?: unknown) => void>
}

function stubRoot() {
  const elements = new Map<string, ElementStub>()
  const element = (selector: string): ElementStub => {
    let found = elements.get(selector)
    if (!found) {
      const listeners = new Map<string, (event?: unknown) => void>()
      found = {
        value: '',
        textContent: '',
        innerHTML: '',
        disabled: false,
        dataset: {},
        listeners,
        addEventListener: vi.fn((event: string, callback: (event?: unknown) => void) => {
          listeners.set(event, callback)
        }),
      }
      elements.set(selector, found)
    }
    return found
  }
  return {
    root: { innerHTML: '', querySelector: element } as unknown as HTMLElement,
    element,
  }
}

describe('full library button in the companion', () => {
  beforeEach(() => {
    mocks.openFullLibraryWindow.mockClear().mockResolvedValue('opened')
    mocks.loadStoredConfig.mockResolvedValue({
      baseUrl: 'https://saved.example.com',
      token: null,
    })
    mocks.loadTrustedShares.mockResolvedValue([])
    mocks.hydrateLifecycleRegistry.mockResolvedValue({ snapshot: () => [] })
    mocks.loadInstallsFromDisk.mockResolvedValue({})
    mocks.keychainLoad.mockResolvedValue(null)
  })

  it('uses the current form URL and rejects missing or unsafe URLs before opening', async () => {
    const { root, element } = stubRoot()
    await mountApp(root)
    const button = element('#open-library-btn')
    const click = button.listeners.get('click')
    expect(click).toBeDefined()

    element('#base-url').value = ''
    click?.()
    expect(element('#status').textContent).toContain('Enter a Server URL')

    element('#base-url').value = 'http://public.example.com'
    click?.()
    expect(element('#status').textContent).toMatch(/Refusing http:\/\//i)
    expect(mocks.openFullLibraryWindow).not.toHaveBeenCalled()

    element('#base-url').value = 'https://selected.example.com/'
    click?.()
    await vi.waitFor(() => expect(mocks.openFullLibraryWindow).toHaveBeenCalledOnce())
    expect(mocks.openFullLibraryWindow).toHaveBeenCalledWith('https://selected.example.com')
    await vi.waitFor(() =>
      expect(element('#status').textContent).toBe('Full library opened — sign in if prompted.'),
    )
  })
})
