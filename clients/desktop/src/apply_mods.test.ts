import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

vi.mock('./install-store.js', () => ({
  loadInstallsFromDisk: vi.fn(async () => ({
    'game-42': { extractPath: 'C:\\Oneirodex\\installs\\game-42', archivePath: 'x.zip' },
  })),
}))

import { invoke } from '@tauri-apps/api/core'
import {
  checkDownloadIntegrity,
  fetchGameMods,
  loaderConflicts,
  loaderLabel,
  loaderRequirementHint,
  requiredLoaders,
  fetchModsSummaryGameUuids,
  isModArchiveFilename,
  kickoffApplyModPack,
  modApplyBlockedReason,
  modApplyUiHint,
  pickModFilename,
  resolveModApplyPath,
  resolveModStageDir,
  safeModFilename,
  safeModRelativePath,
  sortEnabledMods,
  stageModFromUrl,
} from './apply_mods.js'

describe('apply_mods helpers', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
  })

  it('sanitizes mod filenames and relative paths', () => {
    expect(safeModFilename('../evil.dll')).toBe('evil.dll')
    expect(safeModRelativePath('textures/hd.png')).toBe('textures/hd.png')
    expect(safeModRelativePath('../escape')).toBeNull()
  })

  it('resolves stage dir under mods root', () => {
    expect(resolveModStageDir('/appdata/mods/', 'abc-123', 'mod-9')).toBe(
      '/appdata/mods/abc-123/mod-9',
    )
  })

  it('resolves apply paths only under install root', () => {
    const root = 'C:\\Oneirodex\\installs\\game-42'
    expect(resolveModApplyPath(root, 'mods/foo.dll')).toBe(
      'C:\\Oneirodex\\installs\\game-42\\mods\\foo.dll',
    )
    expect(resolveModApplyPath(root, '..\\..\\windows\\system32')).toBeNull()
  })

  it('detects mod archives', () => {
    expect(isModArchiveFilename('pack.zip')).toBe(true)
    expect(isModArchiveFilename('pack.7Z')).toBe(true)
    expect(isModArchiveFilename('readme.txt')).toBe(false)
  })

  it('places a required row before its dependent, whatever the load order says (INSP-38)', () => {
    const rows = [
      {
        id: 'dep',
        name: 'Dependent',
        version: '',
        source_url: 'https://x/d',
        enabled: true,
        load_order: 0,
        loader: '',
        requires: ['lib'],
      },
      {
        id: 'lib',
        name: 'Library',
        version: '',
        source_url: 'https://x/l',
        enabled: true,
        load_order: 5,
        loader: '',
        requires: [],
      },
      {
        id: 'off',
        name: 'Off',
        version: '',
        source_url: 'https://x/o',
        enabled: false,
        load_order: 1,
        loader: '',
        requires: [],
      },
      {
        id: 'loop-a',
        name: 'A',
        version: '',
        source_url: 'https://x/a',
        enabled: true,
        load_order: 9,
        loader: '',
        requires: ['loop-b'],
      },
      {
        id: 'loop-b',
        name: 'B',
        version: '',
        source_url: 'https://x/b',
        enabled: true,
        load_order: 8,
        loader: '',
        requires: ['loop-a'],
      },
    ]
    // In a cycle, the first row's declared dependency still lands first.
    expect(sortEnabledMods(rows).map((r) => r.id)).toEqual(['lib', 'dep', 'loop-a', 'loop-b'])
  })

  it('loaderConflicts lists enabled rows that disagree with the pack default', () => {
    const pack = {
      default_loader: 'bepinex',
      mods: [
        {
          id: '1',
          name: 'Fine',
          version: '',
          source_url: '',
          enabled: true,
          load_order: 0,
          loader: 'bepinex',
          requires: [],
        },
        {
          id: '2',
          name: 'Quiet',
          version: '',
          source_url: '',
          enabled: true,
          load_order: 0,
          loader: '',
          requires: [],
        },
        {
          id: '3',
          name: 'Manual',
          version: '',
          source_url: '',
          enabled: true,
          load_order: 0,
          loader: 'manual',
          requires: [],
        },
        {
          id: '4',
          name: 'Odd',
          version: '',
          source_url: '',
          enabled: true,
          load_order: 0,
          loader: 'melonloader',
          requires: [],
        },
        {
          id: '5',
          name: 'Off',
          version: '',
          source_url: '',
          enabled: false,
          load_order: 0,
          loader: 'smapi',
          requires: [],
        },
      ],
    }
    expect(loaderConflicts(pack).map((c) => c.id)).toEqual(['4'])
    expect(loaderConflicts({ ...pack, default_loader: '' })).toEqual([])
  })

  it('checkDownloadIntegrity refuses empty and short bodies (INSP-39)', () => {
    expect(checkDownloadIntegrity(new ArrayBuffer(0), null, 'X')).toMatch(/empty/)
    expect(checkDownloadIntegrity(new ArrayBuffer(10), '20', 'X')).toMatch(
      /short \(10 of 20 bytes\)/,
    )
    expect(checkDownloadIntegrity(new ArrayBuffer(20), '20', 'X')).toBeNull()
    expect(checkDownloadIntegrity(new ArrayBuffer(20), 'nonsense', 'X')).toBeNull()
  })

  it('sorts enabled mods by load order', () => {
    const sorted = sortEnabledMods([
      {
        id: 'b',
        name: 'B',
        version: '',
        source_url: 'https://x/b.zip',
        enabled: true,
        load_order: 2,
      },
      { id: 'a', name: 'A', version: '', source_url: '', enabled: true, load_order: 0 },
      {
        id: 'c',
        name: 'C',
        version: '',
        source_url: 'https://x/c.zip',
        enabled: false,
        load_order: 1,
      },
    ])
    expect(sorted.map((row) => row.id)).toEqual(['b'])
  })

  it('pickModFilename prefers URL basename', () => {
    expect(
      pickModFilename('https://cdn.example/mod-pack.zip', {
        id: 'm1',
        name: 'Pack',
        version: '',
        source_url: 'https://cdn.example/mod-pack.zip',
        enabled: true,
        load_order: 0,
      }),
    ).toBe('mod-pack.zip')
  })

  it('fetchGameMods parses API rows', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        mods: [
          { id: 'm1', name: 'HD', source_url: 'https://x/hd.zip', enabled: true, load_order: 1 },
        ],
      }),
    })) as unknown as typeof fetch

    const result = await fetchGameMods(
      { getBaseUrl: () => 'https://gt.example', getToken: () => 'gt_x_y' } as never,
      'game-1',
      { fetchImpl },
    )
    expect(result.mods).toHaveLength(1)
    expect(result.mods[0].source_url).toBe('https://x/hd.zip')
    expect(result.mods[0].loader).toBe('')
    expect(result.default_loader).toBe('')
  })

  it('reads loader on rows and the pack default, and says which loaders are needed (INSP-36)', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        default_loader: 'bepinex',
        mods: [
          { id: 'm1', name: 'HD', source_url: 'https://x/hd.zip', enabled: true, load_order: 1 },
          {
            id: 'm2',
            name: 'ML',
            source_url: 'https://x/ml.zip',
            enabled: true,
            load_order: 2,
            loader: 'melonloader',
          },
          {
            id: 'm3',
            name: 'Off',
            source_url: 'https://x/off.zip',
            enabled: false,
            load_order: 3,
            loader: 'smapi',
          },
          {
            id: 'm4',
            name: 'Manual',
            source_url: 'https://x/m.zip',
            enabled: true,
            load_order: 4,
            loader: 'manual',
          },
        ],
      }),
    })) as unknown as typeof fetch

    const pack = await fetchGameMods(
      { getBaseUrl: () => 'https://gt.example', getToken: () => 'gt_x_y' } as never,
      'game-1',
      { fetchImpl },
    )
    expect(pack.default_loader).toBe('bepinex')
    expect(pack.active_profile_name).toBe('')
    expect(pack.mods[1].loader).toBe('melonloader')
    expect(requiredLoaders(pack)).toEqual(['bepinex', 'melonloader'])
    expect(loaderRequirementHint(pack)).toBe(
      'Needs BepInEx, MelonLoader installed — not managed here.',
    )
    expect(loaderRequirementHint({ mods: [], default_loader: 'bepinex' })).toBeNull()
    expect(loaderLabel('my-own-loader')).toBe('my-own-loader')
  })

  it('fetchModsSummaryGameUuids collects games with enabled mods', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        games: [
          { game_uuid: 'g1', enabled_count: 2 },
          { game_uuid: 'g2', enabled_count: 0 },
        ],
      }),
    })) as unknown as typeof fetch

    const uuids = await fetchModsSummaryGameUuids(
      { getBaseUrl: () => 'https://gt.example', getToken: () => 'gt_x_y' } as never,
      { fetchImpl },
    )
    expect(uuids.gameUuids.has('g1')).toBe(true)
    expect(uuids.gameUuids.has('g2')).toBe(false)
    expect(uuids.trackingEnabled).toBe(true)
  })

  it('stageModFromUrl writes under app_data/mods via write_file_bytes', async () => {
    vi.mocked(invoke).mockImplementation(async (command: string) => {
      if (command === 'get_app_subdir') {
        return '/appdata/mods'
      }
      return undefined
    })
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new TextEncoder().encode('PK').buffer,
    })) as unknown as typeof fetch

    const result = await stageModFromUrl({
      gameUuid: 'game-42',
      mod: {
        id: 'hd',
        name: 'HD',
        version: '1',
        source_url: 'https://cdn.example/hd.zip',
        enabled: true,
        load_order: 0,
      },
      fetchImpl,
    })

    expect(result).toEqual({ ok: true, path: '/appdata/mods/game-42/hd/hd.zip' })
    expect(invoke).toHaveBeenCalledWith('write_file_bytes', {
      path: '/appdata/mods/game-42/hd/hd.zip',
      bytes: expect.any(Array),
    })
  })

  describe('stageModFromUrl transport policy', () => {
    const modAt = (source_url: string) => ({
      id: 'hd',
      name: 'HD',
      version: '1',
      source_url,
      enabled: true,
      load_order: 0,
      loader: '',
      requires: [],
    })
    const okFetch = () =>
      vi.fn(async () => ({
        ok: true,
        arrayBuffer: async () => new TextEncoder().encode('PK').buffer,
      }))

    beforeEach(() => {
      vi.mocked(invoke).mockImplementation(async (command: string) =>
        command === 'get_app_subdir' ? '/appdata/mods' : undefined,
      )
    })

    it('refuses plain http:// from a public host without fetching or writing', async () => {
      const fetchImpl = okFetch()
      const result = await stageModFromUrl({
        gameUuid: 'game-42',
        mod: modAt('http://cdn.example.com/hd.zip'),
        fetchImpl: fetchImpl as unknown as typeof fetch,
      })
      expect(result.ok).toBe(false)
      expect(result.ok === false && result.error).toMatch(/https:\/\//)
      expect(fetchImpl).not.toHaveBeenCalled()
      expect(invoke).not.toHaveBeenCalledWith('write_file_bytes', expect.anything())
    })

    it('refuses non-http(s) schemes and junk', async () => {
      for (const source of [
        'ftp://cdn.example.com/hd.zip',
        'file:///C:/x.zip',
        'cdn.example/hd.zip',
      ]) {
        const fetchImpl = okFetch()
        const result = await stageModFromUrl({
          gameUuid: 'game-42',
          mod: modAt(source),
          fetchImpl: fetchImpl as unknown as typeof fetch,
        })
        expect(result.ok, source).toBe(false)
        expect(fetchImpl).not.toHaveBeenCalled()
      }
    })

    it('allows http:// on the local network (LAN address, .local, bare name, loopback)', async () => {
      for (const source of [
        'http://192.168.1.20:8080/hd.zip',
        'http://nas.local/hd.zip',
        'http://nas/hd.zip',
        'http://127.0.0.1:9000/hd.zip',
        'https://cdn.example.com/hd.zip',
      ]) {
        const fetchImpl = okFetch()
        const result = await stageModFromUrl({
          gameUuid: 'game-42',
          mod: modAt(source),
          fetchImpl: fetchImpl as unknown as typeof fetch,
        })
        expect(result.ok, source).toBe(true)
        expect(fetchImpl).toHaveBeenCalledWith(source)
      }
    })

    it('refuses an https source that redirects to plain http:// on a public host', async () => {
      const fetchImpl = vi.fn(async () => ({
        ok: true,
        redirected: true,
        url: 'http://evil.example.com/hd.zip',
        arrayBuffer: async () => new TextEncoder().encode('PK').buffer,
      }))
      const result = await stageModFromUrl({
        gameUuid: 'game-42',
        mod: modAt('https://cdn.example.com/hd.zip'),
        fetchImpl: fetchImpl as unknown as typeof fetch,
      })
      expect(result.ok).toBe(false)
      expect(invoke).not.toHaveBeenCalledWith('write_file_bytes', expect.anything())
    })

    it('accepts an https source that redirects to another https URL', async () => {
      const fetchImpl = vi.fn(async () => ({
        ok: true,
        redirected: true,
        url: 'https://objects.example.net/hd.zip',
        arrayBuffer: async () => new TextEncoder().encode('PK').buffer,
      }))
      const result = await stageModFromUrl({
        gameUuid: 'game-42',
        mod: modAt('https://cdn.example.com/hd.zip'),
        fetchImpl: fetchImpl as unknown as typeof fetch,
      })
      expect(result.ok).toBe(true)
    })
  })

  it('kickoffApplyModPack stages and applies each enabled mod', async () => {
    vi.mocked(invoke).mockImplementation(async (command: string) => {
      if (command === 'get_app_subdir') {
        return '/appdata/mods'
      }
      if (command === 'apply_staged_mod') {
        return { applied: 3 }
      }
      return undefined
    })

    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes('/mods')) {
        return {
          ok: true,
          json: async () => ({
            enabled: true,
            mods: [
              {
                id: 'm1',
                name: 'One',
                source_url: 'https://cdn.example/one.zip',
                enabled: true,
                load_order: 0,
              },
            ],
          }),
        }
      }
      return {
        ok: true,
        arrayBuffer: async () => new TextEncoder().encode('PK').buffer,
      }
    }) as unknown as typeof fetch

    const result = await kickoffApplyModPack(
      { getBaseUrl: () => 'https://gt.example', getToken: () => 'gt_x_y' } as never,
      'game-42',
      { fetchImpl },
    )

    expect(result).toEqual({
      ok: true,
      appliedMods: 1,
      filesApplied: 3,
      loaderHint: null,
      profileName: '',
    })
    expect(invoke).toHaveBeenCalledWith('apply_staged_mod', {
      sourcePath: '/appdata/mods/game-42/m1/one.zip',
      installRoot: 'C:\\Oneirodex\\installs\\game-42',
    })
  })

  it('modApplyBlockedReason explains offline and install requirements', () => {
    expect(
      modApplyBlockedReason({
        connectionOnline: false,
        modsTrackingEnabled: true,
        hasEnabledMods: true,
        installed: true,
      }),
    ).toMatch(/offline/i)
    expect(
      modApplyBlockedReason({
        connectionOnline: true,
        modsTrackingEnabled: true,
        hasEnabledMods: true,
        installed: false,
      }),
    ).toMatch(/Install/i)
    expect(
      modApplyBlockedReason({
        connectionOnline: true,
        modsTrackingEnabled: true,
        hasEnabledMods: true,
        installed: true,
      }),
    ).toBeNull()
  })

  it('modApplyUiHint mentions WebRetro limitation', () => {
    expect(modApplyUiHint(false)).toMatch(/WebRetro/i)
    expect(modApplyUiHint(true)).toMatch(/WebRetro/i)
  })
})
