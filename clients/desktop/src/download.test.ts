import { describe, expect, it, vi, beforeEach } from 'vitest'

import { createAuthStore } from './auth.js'
import {
  downloadGameArchive,
  kickoffDownload,
  resolveArchivePath,
  resolveExtractPath,
} from './download.js'
import { postClientHeartbeat } from './heartbeat.js'
import { createLifecycleRegistry } from './lifecycle.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

import { invoke } from '@tauri-apps/api/core'

describe('download kickoff helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(invoke).mockImplementation(async (command: string, args?: unknown) => {
      const typed = args as { subdir?: string } | undefined
      if (command === 'get_app_subdir') {
        return typed?.subdir === 'installs' ? '/appdata/installs' : '/appdata/downloads'
      }
      if (command === 'load_installs') {
        return { installs: {} }
      }
      return undefined
    })
  })

  it('marks a game downloaded after a successful download pipeline', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const registry = createLifecycleRegistry()
    const initiate = vi.fn().mockResolvedValue({
      download_id: 7,
      status: 'available',
      stream_url: '/download_zip/7',
    })
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-length': '4' }),
      arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
      body: null,
    })

    const api = {
      downloads: { initiateGameDownload: initiate },
    }

    const next = await kickoffDownload(api as never, auth, registry, 'game-42', { fetchImpl })

    expect(initiate).toHaveBeenCalledWith('game-42', {
      kind: undefined,
      versionUuid: undefined,
    })
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://example.com/download_zip/7',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer gt_prefix_secret',
        }),
      }),
    )
    expect(invoke).toHaveBeenCalledWith('write_file_bytes', {
      path: resolveArchivePath('/appdata/downloads', 'game-42'),
      bytes: expect.any(Uint8Array),
    })
    expect(invoke).toHaveBeenCalledWith('append_file_bytes', {
      path: resolveArchivePath('/appdata/downloads', 'game-42'),
      bytes: expect.any(Uint8Array),
    })
    expect(next).toBe('downloaded')
    expect(registry.get('game-42')).toBe('downloaded')
  })

  it('passes version options to initiate download', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const registry = createLifecycleRegistry()
    const initiate = vi.fn().mockResolvedValue({
      download_id: 8,
      status: 'available',
      stream_url: '/download_zip/8',
    })
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-length': '2' }),
      arrayBuffer: async () => new Uint8Array([9, 9]).buffer,
      body: null,
    })
    const api = {
      downloads: { initiateGameDownload: initiate },
    }

    await kickoffDownload(api as never, auth, registry, 'game-99', {
      fetchImpl,
      kind: 'update',
      versionUuid: 'upd-1',
    })

    expect(initiate).toHaveBeenCalledWith('game-99', {
      kind: 'update',
      versionUuid: 'upd-1',
    })
  })

  it('leaves lifecycle unchanged when download fails', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const registry = createLifecycleRegistry()
    const api = {
      downloads: {
        initiateGameDownload: vi.fn().mockRejectedValue(new Error('Missing scope')),
      },
    }

    await expect(kickoffDownload(api as never, auth, registry, 'game-42')).rejects.toThrow(
      'Missing scope',
    )
    expect(registry.get('game-42')).toBe('not_downloaded')
  })

  it.each(['.', '..', '../escape', 'a/b', 'a\\b', 'C:\\Windows', '', 'x'.repeat(65)])(
    'refuses game id %j before any request, download, or write',
    async (hostileId) => {
      const auth = createAuthStore()
      auth.setBaseUrl('https://example.com')
      auth.setToken('gt_prefix_secret')

      const registry = createLifecycleRegistry()
      const initiate = vi.fn()
      const fetchImpl = vi.fn()
      const api = { downloads: { initiateGameDownload: initiate } }

      await expect(
        kickoffDownload(api as never, auth, registry, hostileId, { fetchImpl }),
      ).rejects.toThrow(/Invalid game id/)
      await expect(
        downloadGameArchive(api as never, auth, hostileId, { fetchImpl }),
      ).rejects.toThrow(/Invalid game id/)

      expect(initiate).not.toHaveBeenCalled()
      expect(fetchImpl).not.toHaveBeenCalled()
      // Nothing was written, and no install record was persisted.
      const commands = vi.mocked(invoke).mock.calls.map(([command]) => command)
      expect(commands).not.toContain('write_file_bytes')
      expect(commands).not.toContain('append_file_bytes')
      expect(commands).not.toContain('save_installs')
    },
  )

  it('never resolves the installs or downloads root as a game path', () => {
    // `installs/.` is the installs root: the extract step wipes its destination.
    expect(() => resolveExtractPath('/appdata/installs', '.')).toThrow(/Invalid game id/)
    expect(() => resolveExtractPath('/appdata/installs/', '..')).toThrow(/Invalid game id/)
    expect(() => resolveArchivePath('/appdata/downloads', '..')).toThrow(/Invalid game id/)
    expect(resolveExtractPath('/appdata/installs/', 'game-42')).toBe('/appdata/installs/game-42')
  })

  it('keeps an update generation in its own archive and extract path', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const generation = 'update-11111111-1111-1111-1111-111111111111'
    const api = {
      downloads: {
        initiateGameDownload: vi.fn().mockResolvedValue({
          download_id: 9,
          status: 'available',
          stream_url: '/download_zip/9',
        }),
      },
    }
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers(),
      arrayBuffer: async () => new Uint8Array([1]).buffer,
      body: null,
    })

    const record = await downloadGameArchive(api as never, auth, 'game-42', {
      fetchImpl,
      generation,
    })

    expect(record.archivePath).toBe(`/appdata/downloads/game-42-${generation}.zip`)
    expect(record.extractPath).toBe(`/appdata/installs/game-42-${generation}`)
    expect(vi.mocked(invoke).mock.calls.map(([command]) => command)).not.toContain('save_installs')

    await expect(
      downloadGameArchive(api as never, auth, 'game-42', { fetchImpl, generation: '../x' }),
    ).rejects.toThrow(/Invalid update generation/)
  })
})

/**
 * Heartbeat goes through @oneirodex/api-client, whose requester reads
 * `headers.get('content-type')` and `text()` — so the fake has to be shaped
 * like a real Response, not just `{ ok, json }`.
 */
function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(body),
    json: async () => body,
  }
}

describe('client heartbeat helper', () => {
  it('posts heartbeat payload with bearer auth', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ commands: [] }))
    await postClientHeartbeat(auth, {
      deviceId: 'device-1',
      deviceName: 'Test Desktop',
      clientVersion: '0.1.0',
      fetchImpl,
    })

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('https://example.com/api/client/heartbeat')
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer gt_prefix_secret')
  })

  it('parses open_path commands that carry an absolute path', async () => {
    const auth = createAuthStore()
    auth.setBaseUrl('https://example.com')
    auth.setToken('gt_prefix_secret')

    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        commands: [
          {
            id: 'cmd-1',
            action: 'open_path',
            path: 'Z:\\games\\UnmatchedTitle',
            game_uuid: '',
          },
          {
            id: 'cmd-skip',
            action: 'open_path',
            game_uuid: 'game-1',
          },
        ],
      }),
    )
    const commands = await postClientHeartbeat(auth, {
      deviceId: 'device-1',
      fetchImpl,
    })
    expect(commands).toEqual([
      {
        id: 'cmd-1',
        game_uuid: '',
        action: 'open_path',
        path: 'Z:\\games\\UnmatchedTitle',
        select: true,
        created_at: undefined,
      },
    ])
  })
})
