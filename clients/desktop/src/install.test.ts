import { describe, expect, it, vi, beforeEach } from 'vitest'

import { cancelInstallArchive, kickoffInstall } from './install.js'
import { createLifecycleRegistry } from './lifecycle.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn() }))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

vi.mock('./install-store.js', () => ({
  loadInstallsFromDisk: vi.fn(),
  saveInstallsToDisk: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'

describe('install helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(listen).mockReset()
    vi.mocked(loadInstallsFromDisk).mockReset()
    vi.mocked(saveInstallsToDisk).mockReset()
  })

  it('extracts archive and transitions lifecycle to installed', async () => {
    const registry = createLifecycleRegistry()
    registry.apply('game-42', 'download')

    vi.mocked(loadInstallsFromDisk).mockResolvedValue({
      'game-42': {
        archivePath: '/appdata/downloads/game-42.zip',
        extractPath: '/appdata/installs/game-42',
      },
    })
    vi.mocked(invoke).mockResolvedValue({
      extract_path: '/appdata/installs/game-42',
      exe_path: '/appdata/installs/game-42/game.exe',
    })

    const next = await kickoffInstall(registry, 'game-42')

    expect(invoke).toHaveBeenCalledWith(
      'extract_zip_archive',
      expect.objectContaining({
        archivePath: '/appdata/downloads/game-42.zip',
        destDir: '/appdata/installs/game-42',
        operationId: expect.any(String),
      }),
    )
    expect(saveInstallsToDisk).toHaveBeenCalled()
    expect(next).toBe('installed')
    expect(registry.get('game-42')).toBe('installed')
  })

  it('subscribes to matching extraction progress and removes the listener on completion', async () => {
    const registry = createLifecycleRegistry()
    registry.apply('game-42', 'download')
    const unlisten = vi.fn()
    vi.mocked(loadInstallsFromDisk).mockResolvedValue({
      'game-42': {
        archivePath: '/appdata/downloads/game-42.zip',
        extractPath: '/appdata/installs/game-42',
      },
    })
    vi.mocked(invoke).mockResolvedValue({ extract_path: '/appdata/installs/game-42' })
    vi.mocked(listen).mockResolvedValue(unlisten)
    const onProgress = vi.fn()

    await kickoffInstall(registry, 'game-42', {
      operationId: 'operation-42',
      onProgress,
    })

    expect(listen).toHaveBeenCalledWith('game-archive-progress', expect.any(Function))
    const listener = vi.mocked(listen).mock.calls[0][1] as (event: {
      payload: { operation_id: string; bytes_extracted: number; total_bytes: number }
    }) => void
    listener({ payload: { operation_id: 'other-operation', bytes_extracted: 1, total_bytes: 5 } })
    listener({ payload: { operation_id: 'operation-42', bytes_extracted: 3, total_bytes: 5 } })
    expect(onProgress).toHaveBeenCalledOnce()
    expect(onProgress).toHaveBeenCalledWith({ bytes_extracted: 3, total_bytes: 5 })
    expect(invoke).toHaveBeenCalledWith(
      'extract_zip_archive',
      expect.objectContaining({ operationId: 'operation-42' }),
    )
    expect(unlisten).toHaveBeenCalledOnce()
  })

  it('sends cancellation for the active extraction operation id', async () => {
    vi.mocked(invoke).mockResolvedValue(true)

    await expect(cancelInstallArchive('operation-42')).resolves.toBe(true)

    expect(invoke).toHaveBeenCalledWith('cancel_game_archive_install', {
      operationId: 'operation-42',
    })
  })

  it.each(['.', '..', 'a/b', 'a\\b', ''])(
    'refuses game id %j before it can name an extract destination',
    async (hostileId) => {
      const registry = createLifecycleRegistry({
        initial: [{ gameUuid: hostileId, state: 'downloaded' }],
      })
      vi.mocked(loadInstallsFromDisk).mockResolvedValue({
        [hostileId]: {
          archivePath: '/appdata/downloads/x.zip',
          extractPath: '/appdata/installs/.',
        },
      })

      await expect(kickoffInstall(registry, hostileId)).rejects.toThrow(/Invalid game id/)

      expect(invoke).not.toHaveBeenCalled()
      expect(saveInstallsToDisk).not.toHaveBeenCalled()
    },
  )
})
