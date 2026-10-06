import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ModsPanel } from './ModsPanel'
import { stubFetch } from '../testJsonResponse'

const PACK = {
  ok: true,
  enabled: true,
  default_loader: 'bepinex',
  loaders: ['bepinex', 'melonloader', 'none'],
  mods: [
    {
      id: 'm1',
      name: 'Configuration Manager',
      version: '18.0',
      source_url: 'https://thunderstore.io/c/x/p/a/ConfigurationManager/',
      notes: 'In-game settings window',
      enabled: true,
      load_order: 0,
      loader: '',
    },
  ],
}

const CATALOG = {
  ok: true,
  status: 'ok',
  source: 'thunderstore',
  count: 1,
  hits: [
    {
      name: 'BepInExPack',
      url: 'https://thunderstore.io/c/x/p/bbepis/BepInExPack/',
      source: 'thunderstore',
      version: '5.4.2100',
      loader: 'bepinex',
      summary: 'The loader everything needs',
      author: 'bbepis',
      downloads: 10000000,
      updated: null,
      categories: ['Libraries'],
    },
  ],
}

function routeFetch(overrides: Record<string, unknown> = {}) {
  const calls: { url: string; method: string; body: unknown }[] = []
  stubFetch(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method || 'GET').toUpperCase()
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    let payload: unknown = PACK
    if (url.includes('/mods/catalog')) payload = overrides.catalog ?? CATALOG
    else if (method === 'POST') payload = { ok: true, mod: { ...PACK.mods[0], id: 'm2' } }
    else if (url.includes('/mods/pack')) payload = PACK
    else if (method !== 'GET') payload = { ok: true }
    else if (overrides.pack) payload = overrides.pack
    return { ok: true, status: 200, json: async () => payload }
  })
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test('a member sees the tracked list with the pack default loader, and no controls', async () => {
  routeFetch()
  render(<ModsPanel gameUuid="g1" />)
  expect(await screen.findByText('Configuration Manager')).toBeTruthy()
  // The row has no loader of its own, so the pack default shows and says so
  const chip = screen.getByText('bepinex')
  expect(chip.getAttribute('title')).toBe('Pack default loader')
  expect(screen.queryByRole('button', { name: 'Browse catalogue' })).toBeNull()
  expect(screen.queryByText('Add a mod')).toBeNull()
})

test('renders nothing when tracking is off, or when empty for a member', async () => {
  routeFetch({ pack: { ok: true, enabled: false, mods: [] } })
  const { container, unmount } = render(<ModsPanel gameUuid="g1" canEdit />)
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
  await waitFor(() => expect(container).toBeEmptyDOMElement())
  unmount()
  routeFetch({ pack: { ok: true, enabled: true, default_loader: '', loaders: [], mods: [] } })
  const second = render(<ModsPanel gameUuid="g1" />)
  await waitFor(() => expect(second.container).toBeEmptyDOMElement())
})

test('a librarian adds a catalogue hit as a tracked row with the registry page as its source', async () => {
  const calls = routeFetch()
  const user = userEvent.setup()
  render(<ModsPanel gameUuid="g1" canEdit />)
  await screen.findByText('Configuration Manager')
  await user.click(screen.getByRole('button', { name: 'Browse catalogue' }))
  expect(await screen.findByText('BepInExPack')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Registry page' }).getAttribute('href')).toContain(
    '/p/bbepis/BepInExPack/',
  )
  await user.click(screen.getByRole('button', { name: 'Add to list' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
  const post = calls.find((c) => c.method === 'POST')!
  expect(post.url).toMatch(/\/api\/games\/g1\/mods$/)
  expect(post.body).toMatchObject({
    name: 'BepInExPack',
    version: '5.4.2100',
    loader: 'bepinex',
    source_url: 'https://thunderstore.io/c/x/p/bbepis/BepInExPack/',
  })
})

test('the drawer says when a registry had no data rather than showing an empty list', async () => {
  routeFetch({
    catalog: {
      ok: true,
      status: 'unavailable',
      source: 'modrinth',
      hits: null,
      note: 'Modrinth had no data for this title.',
    },
  })
  const user = userEvent.setup()
  render(<ModsPanel gameUuid="g1" canEdit />)
  await screen.findByText('Configuration Manager')
  await user.click(screen.getByRole('button', { name: 'Browse catalogue' }))
  expect(await screen.findByText('Modrinth had no data for this title.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Add to list' })).toBeNull()
})

test('profiles: a librarian saves the enabled set, activates it, and copies its code (INSP-37)', async () => {
  const withProfile = {
    ...PACK,
    profiles: [{ id: 'vanilla', name: 'Vanilla+', mod_ids: ['m1'] }],
    active_profile: '',
  }
  const calls: { url: string; method: string; body: unknown }[] = []
  stubFetch(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method || 'GET').toUpperCase()
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (url.endsWith('/profiles/vanilla/export'))
      return { ok: true, status: 200, json: async () => ({ ok: true, code: 'od-mod:abc' }) }
    if (url.endsWith('/profiles/vanilla/activate'))
      return {
        ok: true,
        status: 200,
        json: async () => ({ ...withProfile, active_profile: 'vanilla' }),
      }
    if (url.endsWith('/profiles') && method === 'POST')
      return {
        ok: true,
        status: 201,
        json: async () => ({ ok: true, profile: { id: 'x', name: 'X', mod_ids: [] } }),
      }
    return { ok: true, status: 200, json: async () => withProfile }
  })
  // user-event installs its own clipboard; read it back rather than stubbing.
  const user = userEvent.setup()
  render(<ModsPanel gameUuid="g1" canEdit />)
  expect(await screen.findByText('Vanilla+')).toBeTruthy()
  expect(screen.getByText('1 mod')).toBeTruthy()

  await user.click(screen.getByRole('button', { name: 'Activate' }))
  await waitFor(() =>
    expect(calls.some((c) => c.url.endsWith('/profiles/vanilla/activate'))).toBe(true),
  )

  await user.click(screen.getByRole('button', { name: 'Copy code' }))
  await waitFor(async () => expect(await navigator.clipboard.readText()).toBe('od-mod:abc'))
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeTruthy()

  await user.type(screen.getByPlaceholderText('e.g. Vanilla+'), 'Everything')
  await user.click(screen.getByRole('button', { name: 'Save profile' }))
  await waitFor(() =>
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/profiles'))).toBe(true),
  )
  const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/profiles'))!
  expect(post.body).toEqual({ name: 'Everything' })
})

test('profiles: a member sees the active profile and can copy, but has no Activate', async () => {
  const withProfile = {
    ...PACK,
    profiles: [{ id: 'vanilla', name: 'Vanilla+', mod_ids: ['m1'] }],
    active_profile: 'vanilla',
  }
  stubFetch(async () => ({ ok: true, status: 200, json: async () => withProfile }))
  render(<ModsPanel gameUuid="g1" />)
  expect(await screen.findByText(/active: Vanilla\+/)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Copy code' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /Activate|Active/ })).toBeNull()
  expect(screen.queryByText('Save profile')).toBeNull()
})

test('catalogue: a hit with dependencies is added with them, and a tracked hit offers Mark updated (INSP-38/39)', async () => {
  const hits = [
    {
      name: 'BepInExPack',
      url: 'https://ts/p/bbepis/BepInExPack/',
      source: 'thunderstore',
      version: '5.4',
      loader: 'bepinex',
      summary: '',
      author: 'bbepis',
      downloads: 1,
      updated: null,
      categories: [],
      dependencies: [],
    },
    {
      name: 'Big Mod',
      url: 'https://ts/p/a/BigMod/',
      source: 'thunderstore',
      version: '2.0',
      loader: 'bepinex',
      summary: '',
      author: 'a',
      downloads: 1,
      updated: null,
      categories: [],
      dependencies: ['BepInExPack'],
    },
    {
      name: 'Configuration Manager',
      url: 'https://thunderstore.io/c/x/p/a/ConfigurationManager/',
      source: 'thunderstore',
      version: '19.0',
      loader: 'bepinex',
      summary: '',
      author: 'a',
      downloads: 1,
      updated: null,
      categories: [],
      dependencies: [],
      tracked_id: 'm1',
      update_available: '19.0',
    },
  ]
  const calls: { url: string; method: string; body: Record<string, unknown> | undefined }[] = []
  let nextId = 10
  stubFetch(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method || 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, method, body })
    if (url.includes('/mods/catalog'))
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: 'ok', source: 'thunderstore', hits }),
      }
    if (method === 'POST')
      return {
        ok: true,
        status: 201,
        json: async () => ({
          ok: true,
          mod: { ...PACK.mods[0], id: `m${nextId++}`, name: body?.name },
        }),
      }
    if (method === 'PATCH')
      return { ok: true, status: 200, json: async () => ({ ok: true, mod: PACK.mods[0] }) }
    return { ok: true, status: 200, json: async () => ({ ...PACK, loader_conflicts: [] }) }
  })
  const user = userEvent.setup()
  render(<ModsPanel gameUuid="g1" canEdit />)
  await screen.findByText('Configuration Manager')
  await user.click(screen.getByRole('button', { name: 'Browse catalogue' }))
  expect(await screen.findByText('Big Mod')).toBeTruthy()
  expect(screen.getByText('Needs: BepInExPack')).toBeTruthy()
  expect(screen.getByText('update: v19.0')).toBeTruthy()

  await user.click(screen.getByRole('button', { name: 'Add with 1 needed' }))
  await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(2))
  const posts = calls.filter((c) => c.method === 'POST')
  expect(posts[0].body?.name).toBe('BepInExPack')
  expect(posts[1].body?.name).toBe('Big Mod')
  expect(posts[1].body?.requires).toEqual(['m10'])

  await user.click(screen.getByRole('button', { name: 'Mark updated to v19.0' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
  const patch = calls.find((c) => c.method === 'PATCH')!
  expect(patch.url).toMatch(/\/mods\/m1$/)
  expect(patch.body).toEqual({ version: '19.0', latest_seen_version: '19.0' })
})

test('a loader mismatch is said plainly on the panel', async () => {
  stubFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      ...PACK,
      loader_conflicts: [
        {
          id: 'm1',
          name: 'Configuration Manager',
          loader: 'melonloader',
          default_loader: 'bepinex',
        },
      ],
    }),
  }))
  render(<ModsPanel gameUuid="g1" />)
  expect(await screen.findByRole('note')).toHaveTextContent(/Loader mismatch/)
  expect(screen.getByRole('note')).toHaveTextContent('Configuration Manager (melonloader)')
})

test('a hostile source scheme from a stored mod pack is not rendered as a link', async () => {
  routeFetch({
    pack: {
      ...PACK,
      mods: [{ ...PACK.mods[0], source_url: 'javascript:alert(1)' }],
    },
  })
  render(<ModsPanel gameUuid="g1" />)
  expect(await screen.findByText('Configuration Manager')).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Source' })).toBeNull()
})
