import { describe, expect, it, vi, beforeEach } from 'vitest'

import { cancelInstallArchive, kickoffInstall } from './install.js'
import { createLifecycleRegistry } from './lifecycle.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
  Channel: class {
    onmessage: ((value: unknown) => void) | undefined
  },
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

vi.mock('./install-store.js', () => ({
  loadInstallsFromDisk: vi.fn(),
  saveInstallsToDisk: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'

describe('install helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
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
        onProgress: expect.any(Object),
      }),
    )
    expect(saveInstallsToDisk).toHaveBeenCalled()
    expect(next).toBe('installed')
    expect(registry.get('game-42')).toBe('installed')
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
