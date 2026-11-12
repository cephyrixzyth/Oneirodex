import { act, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const { roots } = vi.hoisted(() => ({ roots: [] as Array<{ unmount(): void }> }))
vi.mock('react-dom/client', async (load) => {
  const actual = await load<typeof import('react-dom/client')>()
  return {
    ...actual,
    createRoot(...args: Parameters<typeof actual.createRoot>) {
      const root = actual.createRoot(...args)
      roots.push(root)
      return root
    },
  }
})
// The application body is an observable private marker. The actual entry point,
// shell parsing, providers and authentication boundary stay real.
vi.mock('./App', () => ({
  App: () => <p>OLD_BOOTSTRAP_PRIVATE_VIEW</p>,
}))
vi.mock('./GameDetailsApp', () => ({
  GameDetailsApp: () => null,
  parseGameDetailsRootConfig: () => ({}),
}))
const ACCOUNT = '11111111-1111-4111-8111-111111111111'
beforeEach(() => {
  vi.resetModules()
  localStorage.clear()
  document.body.innerHTML =
    '<div id="member-app-root" data-user-id="7" data-username="SyntheticOldAccount" data-account-id="' +
    ACCOUNT +
    '"></div>'
})
afterEach(async () => {
  await act(async () => {
    for (const root of roots.splice(0)) root.unmount()
  })
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
  localStorage.clear()
})
async function mount() {
  await act(async () => {
    await import('./main')
    await Promise.resolve()
  })
}
function hasPrivateView() {
  return document.body.textContent?.includes('OLD_BOOTSTRAP_PRIVATE_VIEW')
}
function identity(account_id: unknown = ACCOUNT) {
  return new Response(JSON.stringify({ account_id }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
test('matching live account can render the private member bootstrap', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(identity()))
  await mount()
  expect(hasPrivateView()).toBe(true)
})
test('a different live account never renders the old private HTML bootstrap', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(identity('22222222-2222-4222-8222-222222222222')),
  )
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('missing HTML account identity never falls back to old numeric viewer data', async () => {
  document.getElementById('member-app-root')!.removeAttribute('data-account-id')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(identity()))
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('a malformed live identity never authorizes the old bootstrap', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(identity({ id: ACCOUNT })))
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('unreachable identity service never falls back to old private content', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Synthetic offline failure')))
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('rejected identity lookup never falls back to old private content', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 403 })))
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('private content stays unmounted while live identity verification is pending', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => new Promise<Response>(() => {})),
  )
  await mount()
  expect(hasPrivateView()).toBe(false)
})
test('an auth boundary during pending verification cannot resurrect the old tree', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        }),
    ),
  )
  await mount()
  await act(async () => {
    window.dispatchEvent(new Event('od-auth-boundary'))
    // The existing entry does not issue an identity read; the control still
    // proves its established mounted-tree invalidation behavior.
    finish?.(identity())
    await Promise.resolve()
  })
  expect(hasPrivateView()).toBe(false)
})

async function underLegacyController(check: () => Promise<void>) {
  const previous = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker')
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { controller: { scriptURL: new URL('/vr/sw.js', location.href).href } },
  })
  try {
    await check()
  } finally {
    if (previous) Object.defineProperty(navigator, 'serviceWorker', previous)
    else Reflect.deleteProperty(navigator, 'serviceWorker')
  }
}
test('legacy worker readiness gates the new private identity read and bootstrap', async () => {
  await underLegacyController(async () => {
    let retire!: (value: boolean) => void
    vi.stubGlobal(
      'odPwaPrivacyReady',
      new Promise<boolean>((resolve) => {
        retire = resolve
      }),
    )
    const lookup = vi.fn().mockResolvedValue(identity())
    vi.stubGlobal('fetch', lookup)
    await mount()
    expect(hasPrivateView()).toBe(false)
    expect(lookup).not.toHaveBeenCalled()
    await act(async () => {
      retire(true)
      await Promise.resolve()
    })
    expect(hasPrivateView()).toBe(true)
  })
})
test('failed legacy worker retirement cannot authorize a private bootstrap', async () => {
  await underLegacyController(async () => {
    vi.stubGlobal('odPwaPrivacyReady', Promise.resolve(false))
    const lookup = vi.fn().mockResolvedValue(identity())
    vi.stubGlobal('fetch', lookup)
    await mount()
    expect(hasPrivateView()).toBe(false)
    expect(lookup).not.toHaveBeenCalled()
  })
})
test('an unrelated pending optional worker install does not block a valid member account', async () => {
  vi.stubGlobal('odPwaPrivacyReady', new Promise<boolean>(() => {}))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(identity()))
  await mount()
  expect(hasPrivateView()).toBe(true)
})

test('hung identity verification offers fresh sign-in after its bound', async () => {
  vi.useFakeTimers()
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => new Promise<Response>(() => {})),
    )
    await mount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(screen.getByRole('link', { name: /^Sign in$/ })).toHaveAttribute('href', '/login')
  } finally {
    vi.useRealTimers()
  }
})
