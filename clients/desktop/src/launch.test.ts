import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createOneirodexClient } from '@oneirodex/api-client'

import { canLaunchGame, kickoffLaunch } from './launch.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

vi.mock('./install-store.js', () => ({
  loadInstallsFromDisk: vi.fn(),
  saveInstallsToDisk: vi.fn(),
}))

vi.mock('./install.js', () => ({
  getInstallRecord: vi.fn(),
}))

vi.mock('./playtime-session.js', () => ({
  watchPlaySession: vi.fn(() => ({ stop: vi.fn() })),
}))

import { invoke } from '@tauri-apps/api/core'
import { getInstallRecord } from './install.js'
import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'
import { watchPlaySession } from './playtime-session.js'

describe('launch helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(getInstallRecord).mockReset()
    vi.mocked(loadInstallsFromDisk).mockReset()
    vi.mocked(saveInstallsToDisk).mockReset()
    vi.mocked(watchPlaySession).mockReset()
  })

  it('allows play for installed and update_available states', () => {
    expect(canLaunchGame('installed')).toBe(true)
    expect(canLaunchGame('update_available')).toBe(true)
    expect(canLaunchGame('downloaded')).toBe(false)
  })

  it.each(['network', 'invalid-id', 'registry'])(
    'keeps native launch successful after %s failure',
    async (failure) => {
      vi.mocked(getInstallRecord).mockResolvedValue({
        archivePath: '/downloads/game.zip',
        extractPath: '/installs/game',
      })
      vi.mocked(invoke).mockResolvedValue({
        pid: 9001,
        resolved_exe_path: failure === 'registry' ? '/installs/game/game.exe' : null,
      })
      vi.mocked(loadInstallsFromDisk).mockResolvedValue({})
      vi.mocked(saveInstallsToDisk).mockRejectedValue(new Error('disk full'))
      const api = createOneirodexClient({
        baseUrl: 'https://example.com',
        getToken: () => 'test',
        fetchImpl: vi.fn(async () => {
          if (failure === 'network') throw new TypeError('offline')
          return new Response(JSON.stringify(failure === 'invalid-id' ? {} : { id: 15 }), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          })
        }),
      })
      const sessionId = failure === 'registry' ? 15 : null
      await expect(kickoffLaunch(api, 'game-offline')).resolves.toEqual({ pid: 9001, sessionId })
      expect(invoke).toHaveBeenCalledTimes(1)
      expect(watchPlaySession).toHaveBeenCalledWith(api, 9001, sessionId)
    },
  )

  it('launches exe, starts playtime session, and watches the process', async () => {
    vi.mocked(getInstallRecord).mockResolvedValue({
      archivePath: 'C:\\appdata\\downloads\\game-42.zip',
      extractPath: 'C:\\appdata\\installs\\game-42',
      exePath: 'C:\\appdata\\installs\\game-42\\game.exe',
    })
    vi.mocked(invoke).mockResolvedValue({
      pid: 9001,
      exe_path: 'C:\\appdata\\installs\\game-42\\game.exe',
      resolved_exe_path: null,
    })

    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/playtime/sessions') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 12, game_uuid: 'game-42' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('not found', { status: 404 })
    })

    const api = createOneirodexClient({
      baseUrl: 'https://example.com',
      getToken: () => 'gt_abcd_secret',
      fetchImpl,
    })

    const result = await kickoffLaunch(api, 'game-42')

    expect(invoke).toHaveBeenCalledWith('launch_game', {
      gameUuid: 'game-42',
      exePath: 'C:\\appdata\\installs\\game-42\\game.exe',
      extractPath: 'C:\\appdata\\installs\\game-42',
    })
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://example.com/api/playtime/sessions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ game_uuid: 'game-42', client: 'desktop' }),
      }),
    )
    expect(watchPlaySession).toHaveBeenCalledWith(api, 9001, 12)
    expect(saveInstallsToDisk).not.toHaveBeenCalled()
    expect(result).toEqual({ pid: 9001, sessionId: 12 })
  })

  it('persists a rescanned exe path when installs.json had none', async () => {
    vi.mocked(getInstallRecord).mockResolvedValue({
      archivePath: 'C:\\appdata\\downloads\\game-42.zip',
      extractPath: 'C:\\appdata\\installs\\game-42',
      exePath: null,
    })
    vi.mocked(invoke).mockResolvedValue({
      pid: 9001,
      exe_path: 'C:\\appdata\\installs\\game-42\\game.exe',
      resolved_exe_path: 'C:\\appdata\\installs\\game-42\\game.exe',
    })
    vi.mocked(loadInstallsFromDisk).mockResolvedValue({
      'game-42': {
        archivePath: 'C:\\appdata\\downloads\\game-42.zip',
        extractPath: 'C:\\appdata\\installs\\game-42',
        exePath: null,
      },
    })

    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/playtime/sessions') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 3, game_uuid: 'game-42' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response('not found', { status: 404 })
    })

    const api = createOneirodexClient({
      baseUrl: 'https://example.com',
      getToken: () => 'gt_abcd_secret',
      fetchImpl,
    })

    await kickoffLaunch(api, 'game-42')

    expect(saveInstallsToDisk).toHaveBeenCalledWith({
      'game-42': {
        archivePath: 'C:\\appdata\\downloads\\game-42.zip',
        extractPath: 'C:\\appdata\\installs\\game-42',
        exePath: 'C:\\appdata\\installs\\game-42\\game.exe',
      },
    })
  })

  it('keeps the pointers to retained and superseded files when it persists the exe path', async () => {
    // A reinstall from a retained snapshot where no exe was found: the first Play
    // resolves one and rewrites the record. Rebuilding the record from three
    // fields used to drop retainedPath, orphaning the snapshot.
    const record = {
      archivePath: 'C:\\appdata\\downloads\\game-42.zip',
      extractPath: 'C:\\appdata\\installs\\game-42.reinstall-1',
      exePath: null,
      retainedPath: 'C:\\appdata\\installs\\game-42.uninstalled-1',
      superseded: {
        archivePath: 'C:\\appdata\\downloads\\game-42-old.zip',
        extractPath: 'C:\\appdata\\installs\\game-42-old',
      },
    }
    vi.mocked(getInstallRecord).mockResolvedValue(record)
    vi.mocked(loadInstallsFromDisk).mockResolvedValue({ 'game-42': record })
    vi.mocked(invoke).mockResolvedValue({
      pid: 9001,
      exe_path: 'C:\\appdata\\installs\\game-42.reinstall-1\\game.exe',
      resolved_exe_path: 'C:\\appdata\\installs\\game-42.reinstall-1\\game.exe',
    })
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ id: 4, game_uuid: 'game-42' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    const api = createOneirodexClient({
      baseUrl: 'https://example.com',
      getToken: () => 'gt_abcd_secret',
      fetchImpl,
    })

    await kickoffLaunch(api, 'game-42')

    expect(saveInstallsToDisk).toHaveBeenCalledWith({
      'game-42': {
        ...record,
        exePath: 'C:\\appdata\\installs\\game-42.reinstall-1\\game.exe',
      },
    })
  })
})
