// @vitest-environment jsdom
import { webcrypto } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const native = vi.hoisted(() => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({
  invoke: native.invoke,
  convertFileSrc: (value: string) => value,
}))
vi.mock('@tauri-apps/api/event', () => ({ listen: async () => () => undefined }))
const server = 'https://a.example'
const token = 'gt_abcdef01_fixtureA'
let root: HTMLElement
const field = (id: string) => root.querySelector<HTMLInputElement>(id)!
const submit = () =>
  root
    .querySelector('form')!
    .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
const settled = () =>
  vi.waitFor(() =>
    expect(root.querySelector<HTMLButtonElement>('#connect-btn')!.disabled).toBe(false),
  )

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('CSS', { escape: (value: string) => value })
  Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true })
  localStorage.clear()
  localStorage.setItem('oneirodex-device-id', 'device-review')
  const boundLaunches: Array<{
    profile: string
    game_uuid: string
    pid: number
    launch_id: string
  }> = []
  native.invoke
    .mockReset()
    .mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      switch (command) {
        case 'load_config':
          return { base_url: server, token: null }
        case 'secure_store_get':
          return token
        case 'load_installs':
          return {
            installs: {
              'game-a': {
                archive_path: 'C:/fixture/a.zip',
                extract_path: 'C:/fixture/a',
                exe_path: 'C:/fixture/a/game.exe',
              },
            },
          }
        case 'load_lifecycle_registry':
          return { records: [{ game_uuid: 'game-a', state: 'update_available' }] }
        case 'load_trusted_shares':
          return []
        case 'save_config':
        case 'secure_store_set':
        case 'save_lifecycle_registry':
          return undefined
        case 'secure_store_delete':
          return undefined
        case 'launch_game':
          if (typeof args?.profileBinding === 'string')
            boundLaunches.push({
              profile: args.profileBinding,
              game_uuid: String(args.gameUuid),
              pid: 42,
              launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0559',
            })
          return {
            pid: 42,
            launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0559',
            exe_path: 'C:/fixture/a/game.exe',
          }
        case 'is_process_running':
          return true
        case 'begin_launch_reporting':
          return '5d283155-6b33-45c9-b9cf-a8e872dd0562'
        case 'list_launches':
          return {
            supported: true,
            launches: boundLaunches.filter((record) => record.profile === args?.profileBinding),
            unverified: 0,
          }
        case 'acquire_launch_reporting':
          return '5d283155-6b33-45c9-b9cf-a8e872dd0563'
        case 'owns_launch_reporting':
          return true
        case 'release_launch_reporting':
          return undefined
        case 'forget_launch_bindings':
          boundLaunches.splice(0)
          return undefined
        default:
          throw new Error(`Unexpected native I/O in connection test: ${command}`)
      }
    })
  vi.stubGlobal('fetch', async () => {
    throw new Error('Unexpected network before Connect')
  })
  const { saveOfflineInstalledShelf } = await import('./offline-shelf.js')
  await saveOfflineInstalledShelf(
    { serverUrl: server, token, accountId: 'account-a', deviceId: 'device-review' },
    [{ uuid: 'game-a', name: 'Private A Title' }],
  )
  document.body.innerHTML = '<div id="review-root"></div>'
  root = document.querySelector('#review-root')!
  const { mountApp } = await import('./app.js')
  await mountApp(root)
})
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(window, '__TAURI_INTERNALS__')
  document.body.innerHTML = ''
  localStorage.clear()
})

describe('actual companion connection orchestration', () => {
  it('keeps local Play available if profile hashing becomes unavailable', async () => {
    vi.stubGlobal('crypto', {
      subtle: { digest: vi.fn().mockRejectedValue(new Error('profile hashing unavailable')) },
    })
    const network = vi.fn(async () => {
      throw new Error('No verified online reporting')
    })
    vi.stubGlobal('fetch', network)
    root.querySelector<HTMLButtonElement>('[data-action="play"]')!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/launched/i))
    expect(native.invoke).toHaveBeenCalledWith(
      'launch_game',
      expect.objectContaining({ profileBinding: null }),
    )
    expect(network).not.toHaveBeenCalled()
  })
  it('shows reporting uncertainty while preserving local game access', async () => {
    let lost = false
    const previous = native.invoke.getMockImplementation()!
    native.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) =>
      command === 'owns_launch_reporting' && lost ? false : previous(command, args),
    )
    vi.stubGlobal('fetch', async (url: string) => {
      const path = new URL(String(url)).pathname
      if (path === '/api/collections') return Response.json([])
      if (path === '/api/client/identity') return Response.json({ account_id: 'account-a' })
      if (path === '/api/search')
        return Response.json({ results: [{ uuid: 'game-a', name: 'Private A Title' }] })
      if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
      if (path === '/api/client/heartbeat') return Response.json({ commands: [] })
      if (path === '/api/client/lifecycle') return Response.json({ records: [] })
      if (path.startsWith('/api/playtime/')) return Response.json({ id: 7 })
      throw new Error(`Unexpected request ${path}`)
    })
    submit()
    await settled()
    root.querySelector<HTMLButtonElement>('[data-action="play"]')!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/launched/i))
    lost = true
    await vi.advanceTimersByTimeAsync(30_000)
    expect(field('#status').textContent).toMatch(/reporting.*unavailable/i)
    expect(root.textContent).toContain('Private A Title')
    expect(root.querySelector<HTMLButtonElement>('[data-action="play"]')!.disabled).toBe(false)
  })
  it('does not send server playtime from a cached identity before fresh verification', async () => {
    const network = vi.fn(async () => {
      throw new Error('No fresh account verification')
    })
    vi.stubGlobal('fetch', network)
    root.querySelector<HTMLButtonElement>('[data-action="play"]')!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/launched/i))
    expect(network).not.toHaveBeenCalled()
    expect(native.invoke).toHaveBeenCalledWith(
      'launch_game',
      expect.objectContaining({ profileBinding: expect.stringMatching(/^[a-f0-9]{64}$/) }),
    )
  })
  it.each(['allowed', 'denied'])(
    'recovers a live family only after fresh identity and ACL verification: %s',
    async (outcome) => {
      let verified = false
      const paths: string[] = []
      const previous = native.invoke.getMockImplementation()!
      native.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
        if (command === 'list_launches') {
          expect(verified).toBe(true)
          return {
            supported: true,
            launches: [
              { game_uuid: 'game-a', pid: 42, launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0559' },
            ],
            unverified: 0,
          }
        }
        return previous(command, args)
      })
      vi.stubGlobal('fetch', async (url: string) => {
        const path = new URL(String(url)).pathname
        paths.push(path)
        if (path === '/api/collections') return Response.json([])
        if (path === '/api/client/identity') {
          verified = true
          return Response.json({ account_id: 'account-a' })
        }
        if (path === '/api/search')
          return outcome === 'denied'
            ? Response.json({ error: 'denied' }, { status: 403 })
            : Response.json({ results: [{ uuid: 'game-a', name: 'Private A Title' }] })
        if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
        if (path === '/api/client/heartbeat') return Response.json({ commands: [] })
        if (path === '/api/client/lifecycle') return Response.json({ records: [] })
        if (path === '/api/playtime/sessions') return Response.json({ id: 7 }, { status: 201 })
        if (path === '/api/playtime/sessions/7/stop') return Response.json({})
        throw new Error(`Unexpected connection fixture request ${path}`)
      })
      submit()
      await settled()
      if (outcome === 'allowed')
        await vi.waitFor(() => expect(paths).toContain('/api/playtime/sessions'))
      else expect(paths).not.toContain('/api/playtime/sessions')
      if (outcome === 'denied')
        expect(native.invoke.mock.calls.some(([command]) => command === 'list_launches')).toBe(
          false,
        )
    },
  )
  it.each(['success', 'metadata-unavailable', 'concurrent'])(
    'refreshes a newly committed installed command outside preview: %s',
    async (outcome) => {
      const gameId = '11111111-2222-4333-8444-555555555555'
      const secondId = '22222222-3333-4444-8555-666666666666'
      let resolveOldDetails!: (value: Response) => void
      let detailsRequests = 0
      let installs = {
        installs: {
          'game-a': {
            archive_path: 'C:/fixture/a.zip',
            extract_path: 'C:/fixture/a',
            exe_path: 'C:/fixture/a/game.exe',
          },
          [gameId]: {
            archive_path: 'C:/fixture/new.zip',
            extract_path: 'C:/fixture/new',
            exe_path: null as string | null,
          },
          [secondId]: {
            archive_path: 'C:/fixture/second.zip',
            extract_path: 'C:/fixture/second',
            exe_path: null as string | null,
          },
        },
      }
      const previous = native.invoke.getMockImplementation()!
      native.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
        if (command === 'load_installs') return structuredClone(installs)
        if (command === 'save_installs') {
          installs = structuredClone(args!.installsFile) as typeof installs
          return
        }
        if (command === 'load_lifecycle_registry')
          return {
            records: [
              { game_uuid: 'game-a', state: 'installed' },
              { game_uuid: gameId, state: 'downloaded' },
              { game_uuid: secondId, state: 'downloaded' },
            ],
          }
        if (command === 'extract_zip_archive')
          return { extract_path: args!.destDir, exe_path: `${args!.destDir}/game.exe` }
        return previous(command, args)
      })
      vi.resetModules()
      const { mountApp } = await import('./app.js')
      await mountApp(root)
      const paths: string[] = []
      vi.stubGlobal('fetch', async (url: string) => {
        const path = new URL(String(url)).pathname
        paths.push(path)
        if (path === '/api/collections') return Response.json([])
        if (path === '/api/client/identity') return Response.json({ account_id: 'account-a' })
        if (path === '/api/search')
          return Response.json({
            results: [
              { uuid: 'game-a', name: 'Private A Title' },
              ...(outcome === 'concurrent'
                ? [{ uuid: secondId, name: 'Second Installed Title' }]
                : []),
            ],
          })
        if (path === `/api/games/${gameId}/details`) {
          detailsRequests += 1
          if (outcome === 'concurrent' && detailsRequests === 1)
            return new Promise<Response>((resolve) => {
              resolveOldDetails = resolve
            })
          return outcome !== 'metadata-unavailable'
            ? Response.json({ uuid: gameId, name: 'Newly Installed Outside Preview' })
            : Response.json({ error: 'Unavailable' }, { status: 503 })
        }
        if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
        if (path === '/api/client/lifecycle') return Response.json({ records: [] })
        if (path === '/api/client/heartbeat')
          return Response.json({
            commands: [{ id: 'install-outside-preview', game_uuid: gameId, action: 'install' }],
          })
        if (path === '/api/client/commands/ack') return Response.json({})
        throw new Error(`Unexpected request: ${path}`)
      })
      submit()
      await settled()
      if (outcome === 'concurrent') {
        await vi.waitFor(() => expect(resolveOldDetails).toBeTypeOf('function'))
        root
          .querySelector<HTMLButtonElement>(`[data-action="install"][data-uuid="${secondId}"]`)!
          .click()
        await vi.waitFor(() =>
          expect(
            JSON.parse(localStorage.getItem('oneirodex-offline-installed-shelf-v1')!).games,
          ).toContainEqual({ uuid: secondId, name: 'Second Installed Title' }),
        )
        resolveOldDetails(Response.json({ uuid: gameId, name: 'Newly Installed Outside Preview' }))
        await vi.waitFor(() => expect(paths).toContain('/api/client/commands/ack'))
        expect(
          JSON.parse(localStorage.getItem('oneirodex-offline-installed-shelf-v1')!).games,
        ).toContainEqual({ uuid: secondId, name: 'Second Installed Title' })
        return
      }
      await vi.waitFor(() => expect(paths).toContain('/api/client/commands/ack'))
      expect(installs.installs[gameId].exe_path).toBe('C:/fixture/new/game.exe')
      if (outcome === 'success') {
        expect(root.textContent).toContain('Newly Installed Outside Preview')
        const saved = JSON.parse(localStorage.getItem('oneirodex-offline-installed-shelf-v1')!)
        expect(saved.games).toContainEqual({
          uuid: gameId,
          name: 'Newly Installed Outside Preview',
        })
      } else {
        expect(field('#status').textContent).toMatch(/installed locally.*refresh/i)
        expect(
          JSON.parse(localStorage.getItem('oneirodex-offline-installed-shelf-v1')!).games,
        ).toEqual([{ uuid: 'game-a', name: 'Private A Title' }])
      }
    },
  )

  it('includes an authorized local install beyond the twelve-title preview in the saved shelf', async () => {
    const paths: string[] = []
    const preview = Array.from({ length: 12 }, (_, index) => ({
      uuid: `preview-${index}`,
      name: `Preview ${index}`,
    }))
    vi.stubGlobal('fetch', async (url: string) => {
      const path = new URL(String(url)).pathname
      paths.push(path)
      if (path === '/api/collections') return Response.json([])
      if (path === '/api/client/identity') return Response.json({ account_id: 'account-a' })
      if (path === '/api/search')
        return Response.json({ results: [...preview, { uuid: 'game-a', name: 'Private A Title' }] })
      if (path === '/api/games/game-a/details')
        return Response.json({ uuid: 'game-a', name: 'Private A Title' })
      if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
      if (path === '/api/client/lifecycle') return Response.json({ records: [] })
      if (path === '/api/client/heartbeat') return Response.json({ commands: [] })
      throw new Error(`Unexpected request: ${path}`)
    })
    submit()
    await settled()
    expect(root.querySelector('[data-game-uuid="game-a"]')).not.toBeNull()
    expect(paths).toContain('/api/games/game-a/details')
    const { loadOfflineInstalledShelf } = await import('./offline-shelf.js')
    expect(
      await loadOfflineInstalledShelf({
        serverUrl: server,
        accountId: 'account-a',
        deviceId: 'device-review',
        token,
      }),
    ).toMatchObject({ games: [{ uuid: 'game-a', name: 'Private A Title' }] })
  })

  it('keeps Connect usable when a new invalid attempt supersedes a pending request', async () => {
    let finish!: (value: Response) => void
    vi.stubGlobal(
      'fetch',
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        }),
    )
    submit()
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    field('#base-url').value = ''
    submit()
    expect(root.querySelector<HTMLButtonElement>('#connect-btn')!.disabled).toBe(false)
    finish(Response.json([]))
    await vi.advanceTimersByTimeAsync(0)
    expect(root.textContent).not.toContain('Private A Title')
  })

  it('finishes an in-flight keychain write before applying explicit forget', async () => {
    let finish!: () => void
    let started = false
    let storedSecret: unknown = token
    const write = new Promise<void>((resolve) => {
      finish = resolve
    })
    const previous = native.invoke.getMockImplementation()!
    native.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'secure_store_set') {
        started = true
        await write
        storedSecret = args?.secret
        return
      }
      if (command === 'secure_store_delete') {
        storedSecret = null
        return
      }
      return previous(command, args)
    })
    vi.stubGlobal('fetch', async (url: string) => {
      const path = new URL(String(url)).pathname
      if (path === '/api/collections') return Response.json([])
      if (path === '/api/client/identity') return Response.json({ account_id: 'account-a' })
      if (path === '/api/search')
        return Response.json({ results: [{ uuid: 'game-a', name: 'Private A Title' }] })
      if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
      throw new Error(`Unexpected request: ${path}`)
    })
    submit()
    await vi.waitFor(() => expect(started).toBe(true))
    root.querySelector<HTMLButtonElement>('#forget-account-btn')!.click()
    await vi.advanceTimersByTimeAsync(0)
    finish()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/forgotten/i))
    await vi.advanceTimersByTimeAsync(0)
    expect(storedSecret).toBeNull()
    expect(root.textContent).not.toContain('Private A Title')
  })

  it('ends profile playtime tracking on explicit forget without stopping the game', async () => {
    const paths: string[] = []
    vi.stubGlobal('fetch', async (url: string) => {
      const path = new URL(String(url)).pathname
      paths.push(path)
      if (path === '/api/collections') return Response.json([])
      if (path === '/api/client/identity') return Response.json({ account_id: 'account-a' })
      if (path === '/api/search')
        return Response.json({ results: [{ uuid: 'game-a', name: 'Private A Title' }] })
      if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
      if (path === '/api/client/heartbeat') return Response.json({ commands: [] })
      if (path === '/api/client/lifecycle') return Response.json({ records: [] })
      if (path.startsWith('/api/playtime/')) return Response.json({ id: 7 })
      throw new Error(`Unexpected request ${path}`)
    })
    submit()
    await settled()
    root.querySelector<HTMLButtonElement>('[data-action="play"]')!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/launched/i))
    const button = root.querySelector<HTMLButtonElement>('#forget-account-btn')
    expect(button).not.toBeNull()
    const beforeForget = paths.length
    button!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/forgotten/i))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(paths).toContain('/api/playtime/sessions/7/stop')
    expect(paths.slice(beforeForget).some((value) => value.endsWith('/heartbeat'))).toBe(false)
    expect(
      native.invoke.mock.calls.some(([command]) => /kill|remove_path/.test(String(command))),
    ).toBe(false)
  })

  it('explicitly forgets credentials and cached titles while preserving native install records', async () => {
    const button = root.querySelector<HTMLButtonElement>('#forget-account-btn')
    expect(button, 'account forget action must exist').not.toBeNull()
    button!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/forgotten/i))
    expect(root.textContent).not.toContain('Private A Title')
    expect(field('#base-url').value).toBe('')
    expect(field('#token').value).toBe('')
    expect(localStorage.getItem('oneirodex-offline-installed-shelf-v1')).toBeNull()
    expect(native.invoke.mock.calls).toContainEqual([
      'secure_store_delete',
      { account: 'api_token' },
    ])
    expect(
      native.invoke.mock.calls.some(([command]) =>
        /remove_path|save_installs|save_lifecycle_registry|launch_game/.test(String(command)),
      ),
    ).toBe(false)
  })

  it('reports partial forget when the OS credential store refuses deletion', async () => {
    const previous = native.invoke.getMockImplementation()!
    native.invoke.mockImplementation(async (command: string, ...args: unknown[]) => {
      if (command === 'secure_store_delete') throw new Error('Credential store refused deletion')
      return previous(command, ...args)
    })
    const button = root.querySelector<HTMLButtonElement>('#forget-account-btn')
    expect(button).not.toBeNull()
    button!.click()
    await vi.waitFor(() => expect(field('#status').textContent).toMatch(/could not fully forget/i))
    expect(root.textContent).not.toContain('Private A Title')
    expect(field('#token').value).toBe('')
    expect(field('#status').dataset.tone).toBe('error')
  })

  it.each([401, 403])(
    'keeps same verified local shelf with HTTP %s denial status',
    async (status) => {
      vi.stubGlobal('fetch', async () => Response.json({ error: 'denied' }, { status }))
      submit()
      await settled()
      expect(field('#status').textContent).toMatch(/access denied/i)
      expect(field('#status').textContent).not.toMatch(/unreachable/i)
      expect(root.textContent).toContain('Private A Title')
      expect(root.querySelector<HTMLButtonElement>('[data-action="play"]')?.disabled).toBe(false)
      expect(root.querySelector<HTMLButtonElement>('[data-action="reveal_path"]')?.disabled).toBe(
        false,
      )
      expect(root.querySelector('[data-action="update"]:not([disabled])')).toBeNull()
      expect(
        native.invoke.mock.calls.some(([cmd]) => /remove|delete|launch/.test(String(cmd))),
      ).toBe(false)
    },
  )

  it('hides all previous-account titles and paths while another identity is connecting', async () => {
    let resolve!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      () =>
        new Promise<Response>((done) => {
          resolve = done
        }),
    )
    field('#base-url').value = 'https://b.example'
    field('#token').value = 'gt_abcdef02_fixtureB'
    submit()
    expect(root.textContent).not.toContain('Private A Title')
    expect(root.textContent).not.toContain('C:/fixture/a')
    await vi.advanceTimersByTimeAsync(0)
    resolve(Response.json({ error: 'denied' }, { status: 403 }))
    await settled()
    expect(root.querySelector('[data-action="play"]')).toBeNull()
    expect(root.textContent).not.toContain('Private A Title')
  })

  it.each(['catalog', 'denied', 'identity-changed'])(
    'revalidates %s before recovery becomes online',
    async (outcome) => {
      let phase: 'initial' | 'outage' | 'recovered' = 'initial'
      let heartbeatCount = 0
      const identities: string[] = []
      vi.stubGlobal('fetch', async (url: string) => {
        const path = new URL(String(url)).pathname
        if (path === '/api/client/heartbeat') {
          heartbeatCount += 1
          return phase === 'outage'
            ? Response.json({ error: 'unavailable' }, { status: 503 })
            : Response.json({
                device_id: 'device-review',
                device_name: null,
                client_version: null,
                last_seen_at: null,
                commands: [],
              })
        }
        if (path === '/api/collections') return Response.json([{ id: 1, name: 'Allowed' }])
        if (path === '/api/client/identity') {
          identities.push(phase)
          return Response.json({
            account_id:
              phase === 'recovered' && outcome === 'identity-changed'
                ? 'account-other'
                : 'account-a',
          })
        }
        if (path === '/api/search')
          return phase === 'recovered' && outcome === 'denied'
            ? Response.json({ error: 'denied' }, { status: 403 })
            : Response.json({
                results:
                  phase === 'recovered'
                    ? [{ uuid: 'game-b', name: 'Current Allowed Title' }]
                    : [{ uuid: 'game-a', name: 'Private A Title' }],
              })
        if (path === '/api/games/game-a/details')
          return Response.json({ error: 'Library access removed' }, { status: 403 })
        if (path === '/api/mods/summary') return Response.json({ enabled: false, games: [] })
        if (path === '/api/client/lifecycle') return Response.json({ records: [] })
        throw new Error(`Unexpected request: ${path}`)
      })
      submit()
      await settled()
      await vi.advanceTimersByTimeAsync(0)
      phase = 'outage'
      await vi.advanceTimersByTimeAsync(120_000)
      expect(field('#auth-summary').textContent).toMatch(/offline/i)
      phase = 'recovered'
      await vi.advanceTimersByTimeAsync(60_000)
      await vi.waitFor(() => expect(identities).toContain('recovered'))
      if (outcome !== 'catalog') {
        expect(field('#auth-summary').textContent).not.toMatch(/· Online/)
        expect(root.querySelector('[data-action="update"]:not([disabled])')).toBeNull()
        if (outcome === 'identity-changed') {
          expect(root.textContent).not.toContain('Private A Title')
          const before = heartbeatCount
          await vi.advanceTimersByTimeAsync(60_000)
          expect(heartbeatCount).toBe(before)
          expect(field('#auth-summary').textContent).not.toMatch(/· Online/)
        } else expect(field('#status').textContent).toMatch(/access denied/i)
        return
      }
      await vi.waitFor(() => expect(root.textContent).toContain('Current Allowed Title'))
      expect(identities).toContain('recovered')
      expect(root.textContent).not.toContain('Private A Title')
      expect(root.textContent).not.toContain('C:/fixture/a')
      expect(field('#auth-summary').textContent).toMatch(/online/i)
    },
  )
})
